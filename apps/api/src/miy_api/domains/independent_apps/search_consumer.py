"""Core-only materialization and cleanup; no engine/credential input from apps."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import signal
from threading import Event
from uuid import UUID, uuid5

from sqlalchemy import func, select

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.data_store import DataStoreError, configured_store
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.search_backends import (
    PROFILE,
    CoreSearchBackends,
    SearchFailure,
    names,
    resolve_embedding_dimensions,
)
from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
from miy_api.domains.independent_apps.search_store import SearchSourceStore
from miy_api.domains.independent_apps.verification import trusted_release, verified_artifact

_PREPARE_NAMESPACE = UUID("53306008-6dbf-42e9-8e1d-45ae3119b7c2")


def prepare_binding(
    factory,
    *,
    installation_id,
    workspace_id,
    release_id,
    settings,
    embedding_dimensions=None,
):
    """Private Core call. Dimensions, if given, were resolved by the approved profile.

    A declaration-identical update reuses the ready resources. Changed search/profile
    allocates a separate immutable search generation, independent of admission epochs.
    """
    backend = CoreSearchBackends(settings)
    try:
        with factory() as db:
            installation = db.scalar(
                select(AppInstallationRecord)
                .where(AppInstallationRecord.id == str(UUID(installation_id)))
                .with_for_update()
            )
            release = (
                verified_artifact(
                    db, installation.app_id, release_id, target_environment="development"
                )
                if installation
                else None
            )
            if (
                not installation
                or installation.environment != "development"
                or installation.state == "archived"
                or not release
            ):
                raise SearchFailure("search_binding_invalid", uncertain=False)
            definition = AppDefinition.model_validate(release.definition_snapshot)
            if definition.search is None:
                raise SearchFailure("search_binding_invalid", uncertain=False)
            workspace_id = str(UUID(workspace_id))
            search_hash = definition.search.content_hash()
            reusable_query = select(AppSearchBindingRecord).where(
                AppSearchBindingRecord.installation_id == installation.id,
                AppSearchBindingRecord.workspace_id == workspace_id,
                AppSearchBindingRecord.search_spec_sha256 == search_hash,
                AppSearchBindingRecord.embedding_config_sha256 == backend.profile_hash,
                AppSearchBindingRecord.state == "ready",
            )
            if embedding_dimensions is not None:
                reusable_query = reusable_query.where(
                    AppSearchBindingRecord.embedding_dimensions == embedding_dimensions
                )
            reusable = db.scalar(
                reusable_query.order_by(AppSearchBindingRecord.generation.desc())
                .limit(1)
                .with_for_update()
            )
            if reusable is not None:
                backend._binding(reusable)
                reusable.candidate_release_id = release.id
                reusable.definition_digest = release.definition_digest
                db.commit()
                return "ready"
            existing = db.scalar(
                select(AppSearchBindingRecord)
                .where(
                    AppSearchBindingRecord.installation_id == installation.id,
                    AppSearchBindingRecord.state.in_(["preparing", "unknown"]),
                )
                .limit(1)
            )
            if existing is not None:
                # A saved preparing/unknown operation may already have external effects.
                raise SearchFailure("search_preparation_held", uncertain=False)
            # The installation row lock serializes allocation, including the first
            # generation. Failed app health checks leave ready resources intact,
            # and removed generations remain reserved in the durable history.
            generation = (
                db.scalar(
                    select(func.max(AppSearchBindingRecord.generation)).where(
                        AppSearchBindingRecord.installation_id == installation.id
                    )
                )
                or 0
            ) + 1
            index, collection = names(workspace_id, generation)
            if embedding_dimensions is None:
                embedding_dimensions = resolve_embedding_dimensions(settings)
            binding = AppSearchBindingRecord(
                installation_id=installation.id,
                workspace_id=workspace_id,
                generation=generation,
                search_spec_sha256=search_hash,
                candidate_release_id=release.id,
                definition_digest=release.definition_digest,
                opensearch_index=index,
                qdrant_collection=collection,
                embedding_profile=PROFILE,
                embedding_config_sha256=backend.profile_hash,
                embedding_dimensions=embedding_dimensions,
                state="preparing",
            )
            db.add(binding)
            db.commit()  # exact targets are saved before any external effects
            try:
                data = configured_store(settings)
                request_id = str(
                    uuid5(
                        _PREPARE_NAMESPACE,
                        f"{installation.id}:{workspace_id}:{generation}:{release.artifact}",
                    )
                )
                arguments = dict(
                    installation_id=installation.id,
                    app_id=installation.app_id,
                    environment=installation.environment,
                    artifact_digest=release.artifact,
                    request_id=request_id,
                )
                data.prepare(**arguments)
                data.prepare_search(
                    **arguments,
                    generation=generation,
                    workspace_id=workspace_id,
                    search_spec_sha256=search_hash,
                )
                backend.prepare(binding)
                binding.state = "ready"
                db.commit()
                return "ready"
            except Exception:
                binding.state = "unknown"
                db.commit()
                raise
    finally:
        backend.close()


def _text(payload, declaration):
    value = "\n".join(
        payload[field] for field in declaration.text_fields if isinstance(payload.get(field), str)
    )
    try:
        bounded = len(value.encode("utf-8")) <= 16384
    except UnicodeEncodeError:
        bounded = False
    if not bounded:
        raise SearchFailure("search_source_invalid", uncertain=False)
    return value


def run_once(
    factory, *, installation_id, settings, release_id=None, backend_factory=CoreSearchBackends
):
    """Materialize the current runtime, or an explicitly verified Core candidate.

    release_id is not an app API field; it permits warming a candidate without
    interrupting the active release's older definition/resources.
    """
    backend = None
    with factory() as db:
        installation = db.get(AppInstallationRecord, str(UUID(installation_id)))
        if installation is None:
            return "held"
        if release_id is None:
            release = (
                trusted_release(db, installation, installation.release_id)
                if installation.release_id and installation.enabled
                else None
            )
        else:
            release = (
                verified_artifact(
                    db, installation.app_id, release_id, target_environment="development"
                )
                if installation.environment == "development"
                else None
            )
        if release is None:
            return "held"
        definition = AppDefinition.model_validate(release.definition_snapshot)
        if definition.search is None:
            return "idle"
        binding = db.scalar(
            select(AppSearchBindingRecord)
            .where(
                AppSearchBindingRecord.installation_id == installation.id,
                AppSearchBindingRecord.search_spec_sha256 == definition.search.content_hash(),
                AppSearchBindingRecord.state == "ready",
            )
            .order_by(AppSearchBindingRecord.generation.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if binding is None:
            return "held"
        source = SearchSourceStore(configured_store(settings))
        try:
            backend = backend_factory(settings)
            with source.next_projection(installation, binding) as selected:
                if selected is None:
                    return "held" if source.has_held(installation, binding) else "idle"
                conn, projection = selected
                declaration = definition.search.collections.get(projection.collection)
                if declaration is None:
                    source.acknowledge(conn, projection, "complete", binding.generation)
                    return "succeeded"
                try:
                    text = _text(projection.payload, declaration)
                    # A record with no declared text removes its old materialization;
                    # its authoritative PostgreSQL row remains unchanged.
                    materialized = (
                        replace(projection, deleted=True) if not text.strip() else projection
                    )
                    if "keyword" in declaration.modes and not projection.keyword_applied:
                        backend.write_keyword(binding, materialized, text)
                        source.acknowledge(conn, projection, "keyword", binding.generation)
                    if "semantic" in declaration.modes and not projection.semantic_applied:
                        backend.write_semantic(binding, materialized, text)
                        source.acknowledge(conn, projection, "semantic", binding.generation)
                    source.acknowledge(conn, projection, "complete", binding.generation)
                    return "succeeded"
                except SearchFailure:
                    # Unknown effects retain their acknowledged phases and exact event.
                    # No automatic replay with a new event/operation identity.
                    source.acknowledge(conn, projection, "held", binding.generation)
                    return "held"
        except DataStoreError:
            return "held"
        finally:
            if backend is not None:
                backend.close()


def cleanup_binding(factory, *, installation_id, generation, settings):
    backend = CoreSearchBackends(settings)
    try:
        with factory() as db:
            binding = db.get(
                AppSearchBindingRecord,
                (str(UUID(installation_id)), generation),
                with_for_update=True,
            )
            if binding is None:
                raise SearchFailure("search_cleanup_held", uncertain=False)
            if binding.state == "removed":
                return "removed"
            if not (
                (binding.state == "stopped" and binding.cleanup_phase is None)
                or (
                    binding.state == "cleanup_pending"
                    and binding.cleanup_phase in {"verified", "keyword_removed", "vector_removed"}
                )
            ):
                raise SearchFailure("search_cleanup_held", uncertain=False)
            installation = db.get(AppInstallationRecord, binding.installation_id)
            if installation is None or installation.environment != "development":
                raise SearchFailure("search_cleanup_held", uncertain=False)
            # Core workspace caller proves writer/admission stop and exact ownership.
            configured_store(settings).stop_search_generation(
                installation_id=installation.id,
                app_id=installation.app_id,
                environment=installation.environment,
                generation=binding.generation,
            )

            def persist_phase(phase):
                binding.cleanup_phase = phase
                binding.state = "cleanup_pending"
                db.commit()

            backend.cleanup(binding, persist_phase=persist_phase)
            binding.state = "removed"
            db.commit()
            return "removed"
    finally:
        backend.close()


def serve(factory, *, settings, stop, interval=1):
    """One Core-owned poller; source advisory fences serialize multiple consumers."""
    while not stop.is_set():
        with factory() as db:
            identities = db.scalars(
                select(AppInstallationRecord.id).where(AppInstallationRecord.enabled.is_(True))
            ).all()
        for identity in identities:
            if stop.is_set():
                break
            try:
                run_once(factory, installation_id=identity, settings=settings)
            except Exception:
                # No raw engine/model/actor data is logged. Original event remains held.
                pass
        stop.wait(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("once", "cleanup", "serve"))
    parser.add_argument("--installation-id")
    parser.add_argument("--release-id")
    parser.add_argument("--generation", type=int)
    arguments = parser.parse_args()
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        settings, factory = get_settings(), get_session_factory()
        if arguments.action == "serve":
            if arguments.installation_id or arguments.release_id or arguments.generation:
                parser.error("serve has no per-app input")
            serve(factory, settings=settings, stop=stop)
            state = "stopped"
        elif not arguments.installation_id:
            parser.error("an exact installation ID is required")
        elif arguments.action == "cleanup":
            if arguments.generation is None or arguments.release_id:
                parser.error("cleanup requires only installation ID and generation")
            state = cleanup_binding(
                factory,
                installation_id=arguments.installation_id,
                generation=arguments.generation,
                settings=settings,
            )
        else:
            if arguments.generation:
                parser.error("once uses the release search declaration")
            state = run_once(
                factory,
                installation_id=arguments.installation_id,
                release_id=arguments.release_id,
                settings=settings,
            )
    except Exception:
        state = "held"
    print(json.dumps({"state": state}))
    return 0 if state in {"idle", "succeeded", "removed", "stopped"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
