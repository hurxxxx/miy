"""Request idempotency and fenced local delivery; no model-authored success evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Callable
from functools import wraps
import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import UserSystemRole, utcnow_naive
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.delivery_contracts import DeploymentInput, DeploymentOut
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppBuildVerification,
    AppDeploymentRequest,
    AppRuntimeSlot,
    AppDeliveryDelegation,
)
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppReleaseRecord,
)
from miy_api.domains.independent_apps.verification import trusted_release


@dataclass(frozen=True)
class RuntimeSpec:
    request_id: str
    installation_id: str
    app_id: str
    image_id: str
    origin: str
    health_path: str
    environment: str = "development"
    runtime_profile: str = "web-api-v1"


@dataclass(frozen=True)
class Observation:
    active: bool
    healthy: bool
    image_id: str | None
    candidate_exists: bool
    ingress_absent: bool = False


class RuntimeFailure(Exception):
    def __init__(self, code: str, *, uncertain: bool = True):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


class AppRuntime(Protocol):
    def prepare(self, spec: RuntimeSpec) -> None: ...
    def activate(self, spec: RuntimeSpec) -> None: ...
    def observe(self, spec: RuntimeSpec) -> Observation: ...
    def discard(self, spec: RuntimeSpec) -> None: ...
    def retire(self, spec: RuntimeSpec) -> None: ...


def deployment_out(record: AppDeploymentRequest) -> DeploymentOut:
    return DeploymentOut.model_validate(record, from_attributes=True)


def _exclusive_runtime_operation(
    operation: Callable[[Session, str, AppRuntime], DeploymentOut],
) -> Callable[[Session, str, AppRuntime], DeploymentOut]:
    @wraps(operation)
    def guarded(db: Session, request_id: str, runtime: AppRuntime) -> DeploymentOut:
        # An independent transaction retains ownership across the durable intent
        # and cutover commits. A row lock alone leaves commit/reacquire windows.
        # Transaction scope releases the advisory lock on close/crash, without
        # leaving a session lock on a pooled connection. One extra connection is
        # held by the single active local deployment; contenders never wait.
        identity = f"miy:independent-delivery:{UUID(request_id)}".encode()
        key = int.from_bytes(hashlib.sha256(identity).digest()[:8], signed=True)
        with Session(bind=db.get_bind().engine) as ownership:
            acquired = ownership.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
            )
            if not acquired:
                record = db.get(AppDeploymentRequest, request_id, populate_existing=True)
                if record is None:
                    service.fail("not_found", 404)
                result = deployment_out(record)
                db.rollback()
                return result
            return operation(db, request_id, runtime)

    return guarded


def verified_release(
    db: Session, installation: AppInstallationRecord, release_id: str
) -> AppReleaseRecord:
    release = trusted_release(db, installation, release_id)
    if release is None:
        service.fail("verification_required", 409)
    if installation.environment != "development" or not release.artifact.startswith("sha256:"):
        service.fail("local_delivery_only", 409)
    return release


def request_deployment(
    db: Session,
    app_id: str,
    data: DeploymentInput,
    context: AuthContext,
    *,
    delegation_id: str | None = None,
) -> DeploymentOut:
    definition = service.owned_definition(db, app_id, context)
    payload = data.model_dump(mode="json") | {
        "app_id": app_id,
        "actor_user_id": context.user.id,
        "delegation_id": delegation_id,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = db.get(AppDeploymentRequest, str(data.request_id))
    if existing:
        if existing.actor_user_id != context.user.id or existing.request_hash != digest:
            service.fail("conflict", 409)
        return deployment_out(existing)
    installation = db.get(AppInstallationRecord, str(data.installation_id))
    if installation is None or installation.app_id != app_id:
        service.fail("not_found", 404)
    if not service.admitted(db, installation, context.user, verify_current_release=False):
        service.fail("forbidden")
    release = verified_release(db, installation, str(data.release_id))
    expected_release = str(data.expected_release_id) if data.expected_release_id else None
    if (installation.generation, installation.release_id) != (
        data.expected_generation,
        expected_release,
    ):
        service.fail("conflict", 409)
    if data.action == "deploy" and (release.source_revision, release.definition_digest) != (
        definition.source_revision,
        definition.definition_digest,
    ):
        service.fail("conflict", 409)
    if (
        data.action == "rollback"
        and db.scalar(
            select(AppDeploymentRequest.id).where(
                AppDeploymentRequest.installation_id == installation.id,
                AppDeploymentRequest.release_id == release.id,
                AppDeploymentRequest.state == "succeeded",
            )
        )
        is None
    ):
        service.fail("verification_required", 409)
    record = AppDeploymentRequest(
        id=str(data.request_id),
        actor_user_id=context.user.id,
        source_session_id=context.session.id,
        delegation_id=delegation_id,
        installation_id=installation.id,
        release_id=release.id,
        action=data.action,
        request_hash=digest,
        expected_generation=data.expected_generation,
        expected_release_id=expected_release,
        previous_release_id=installation.release_id,
        previous_runtime_ref=installation.runtime_ref,
    )
    db.add(record)
    service._audit(db, context, "deployment.request", app_id)
    service._commit(db)
    return deployment_out(record)


def read_deployment(
    db: Session, app_id: str, request_id: str, context: AuthContext
) -> DeploymentOut:
    service.owned_definition(db, app_id, context)
    record = db.get(AppDeploymentRequest, request_id)
    installation = db.get(AppInstallationRecord, record.installation_id) if record else None
    if installation is None or installation.app_id != app_id:
        service.fail("not_found", 404)
    return deployment_out(record)


def _reserve_preview(db: Session, installation_id: str) -> bool:
    if db.get(AppRuntimeSlot, installation_id):
        return True
    for slot in range(4):
        try:
            with db.begin_nested():
                db.add(
                    AppRuntimeSlot(installation_id=installation_id, executor_id="local", slot=slot)
                )
                db.flush()
            return True
        except IntegrityError:
            continue
    return False


def _finish(
    db: Session, record: AppDeploymentRequest, state: str, code: str | None = None
) -> DeploymentOut:
    record.state = state
    record.failure_code = code
    record.active_slot = 1 if state in {"running", "unknown", "cleanup"} else None
    record.updated_at = utcnow_naive()
    db.commit()
    return deployment_out(record)


def _discard_failed(
    db: Session, record: AppDeploymentRequest, runtime: AppRuntime, spec: RuntimeSpec, code: str
) -> DeploymentOut:
    try:
        runtime.discard(spec)
    except RuntimeFailure:
        return _finish(db, record, "unknown", "cleanup_required")
    # Only definitive cleanup releases a first preview's capacity reservation.
    if record.previous_runtime_ref is None:
        slot = db.get(AppRuntimeSlot, record.installation_id)
        if slot:
            db.delete(slot)
    return _finish(db, record, "failed", code)


def _current_authority(
    db: Session, record: AppDeploymentRequest
) -> tuple[AppInstallationRecord, AppReleaseRecord]:
    db.expire_all()  # Recheck policy/source/verification after slow daemon work.
    user, source_session = service._source_user(db, record.source_session_id)
    roles = frozenset(
        db.scalars(select(UserSystemRole.role).where(UserSystemRole.user_id == user.id))
    )
    installation = db.scalar(
        select(AppInstallationRecord)
        .where(AppInstallationRecord.id == record.installation_id)
        .with_for_update()
    )
    if installation is None or user.id != record.actor_user_id:
        service.fail("forbidden")
    context = AuthContext(user=user, session=source_session, system_roles=roles)
    definition = service.owned_definition(db, installation.app_id, context)
    if record.delegation_id:
        from miy_api.domains.independent_apps.delegation import validate

        validate(
            db,
            db.get(AppDeliveryDelegation, record.delegation_id, populate_existing=True),
            record.action,
            installation.app_id,
            installation.id,
        )
    if not service.admitted(db, installation, user, verify_current_release=False):
        service.fail("forbidden")
    if (installation.generation, installation.release_id) != (
        record.expected_generation,
        record.expected_release_id,
    ):
        service.fail("conflict", 409)
    release = verified_release(db, installation, record.release_id)
    if record.action == "deploy" and (release.source_revision, release.definition_digest) != (
        definition.source_revision,
        definition.definition_digest,
    ):
        service.fail("conflict", 409)
    if not set(installation.granted_permissions).issubset(
        release.definition_snapshot["requested_permissions"]
    ):
        service.fail("forbidden")
    return installation, release


def _commit_observation(
    db: Session, record: AppDeploymentRequest, observation: Observation
) -> DeploymentOut:
    installation, release = _current_authority(db, record)
    if (
        not observation.active
        or not observation.healthy
        or observation.image_id != release.artifact
    ):
        raise RuntimeFailure("runtime_not_confirmed")
    installation.release_id = release.id
    installation.runtime_ref = record.id
    installation.generation += 1
    installation.state = "ready"
    record.observed_image_id = observation.image_id
    return _finish(db, record, "cleanup")


def _complete_cleanup(
    db: Session, record: AppDeploymentRequest, runtime: AppRuntime
) -> DeploymentOut:
    record = db.scalar(
        select(AppDeploymentRequest)
        .where(AppDeploymentRequest.id == record.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.state not in {"cleanup", "unknown"}:
        return deployment_out(record)
    if record.previous_runtime_ref:
        previous = db.get(AppDeploymentRequest, record.previous_runtime_ref)
        if previous is None or previous.runtime_config is None:
            return _finish(db, record, "unknown", "previous_runtime_unknown")
        try:
            runtime.retire(RuntimeSpec(**previous.runtime_config))
        except RuntimeFailure:
            return _finish(db, record, "unknown", "retirement_required")
    return _finish(db, record, "succeeded")


@_exclusive_runtime_operation
def execute_deployment(db: Session, request_id: str, runtime: AppRuntime) -> DeploymentOut:
    record = db.scalar(
        select(AppDeploymentRequest).where(AppDeploymentRequest.id == request_id).with_for_update()
    )
    if record is None:
        service.fail("not_found", 404)
    if record.state != "queued":
        db.rollback()
        return deployment_out(record)  # No blind replay of running/unknown/finished side effects.
    try:
        installation, release = _current_authority(db, record)
    except HTTPException:
        return _finish(db, record, "failed", "authority_changed")
    if not _reserve_preview(db, installation.id):
        return _finish(db, record, "queued", "preview_capacity")
    spec = RuntimeSpec(
        record.id,
        installation.id,
        installation.app_id,
        release.artifact,
        installation.origin,
        release.definition_snapshot["entrypoints"]["health"],
        installation.environment,
        release.definition_snapshot["runtime_profile"],
    )
    record.runtime_config = asdict(spec)
    record.state = "running"
    record.active_slot = 1
    record.failure_code = None
    try:
        db.commit()  # Persist intent and slot before the first daemon side effect.
    except IntegrityError:
        db.rollback()
        record = db.scalar(
            select(AppDeploymentRequest)
            .where(AppDeploymentRequest.id == request_id)
            .with_for_update()
        )
        if record.state != "queued":
            return deployment_out(record)
        return _finish(db, record, "queued", "executor_busy")
    # Durable intent survives a crash; the row lock fences a live executor from
    # a simultaneous recovery process throughout daemon work.
    record = db.scalar(
        select(AppDeploymentRequest)
        .where(AppDeploymentRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.state != "running":
        db.rollback()
        return deployment_out(record)
    activated = False
    try:
        runtime.prepare(spec)
        # Fence installation changes while switching and confirming the ingress.
        _current_authority(db, record)
        runtime.activate(spec)
        activated = True
        observed = runtime.observe(spec)
        _commit_observation(db, record, observed)
        return _complete_cleanup(db, record, runtime)
    except HTTPException:
        if activated:
            return _finish(db, record, "unknown", "authority_changed")
        return _discard_failed(db, record, runtime, spec, "authority_changed")
    except RuntimeFailure as exc:
        if activated and record.previous_runtime_ref:
            previous = db.get(AppDeploymentRequest, record.previous_runtime_ref)
            try:
                if previous is None or previous.runtime_config is None:
                    raise RuntimeFailure("previous_runtime_unknown")
                previous_spec = RuntimeSpec(**previous.runtime_config)
                runtime.activate(previous_spec)
                old = runtime.observe(previous_spec)
                if not old.active or not old.healthy or old.image_id != previous_spec.image_id:
                    raise RuntimeFailure("rollback_not_confirmed")
                return _discard_failed(db, record, runtime, spec, exc.code)
            except RuntimeFailure:
                return _finish(db, record, "unknown", "rollback_not_confirmed")
        if exc.uncertain:
            return _finish(db, record, "unknown", exc.code)
        return _discard_failed(db, record, runtime, spec, exc.code)


@_exclusive_runtime_operation
def reconcile_deployment(db: Session, request_id: str, runtime: AppRuntime) -> DeploymentOut:
    record = db.scalar(
        select(AppDeploymentRequest).where(AppDeploymentRequest.id == request_id).with_for_update()
    )
    if record is None:
        service.fail("not_found", 404)
    if record.state not in {"running", "unknown", "cleanup"} or record.runtime_config is None:
        return deployment_out(record)
    spec = RuntimeSpec(**record.runtime_config)
    try:
        observed = runtime.observe(spec)
        if observed.active and observed.healthy and observed.image_id == spec.image_id:
            installation = db.get(AppInstallationRecord, record.installation_id)
            if (
                installation.runtime_ref != record.id
                or installation.release_id != record.release_id
            ):
                _commit_observation(db, record, observed)
            return _complete_cleanup(db, record, runtime)
        if record.previous_runtime_ref:
            previous = db.get(AppDeploymentRequest, record.previous_runtime_ref)
            if previous and previous.runtime_config:
                old_spec = RuntimeSpec(**previous.runtime_config)
                old = runtime.observe(old_spec)
                if old.active and old.healthy and old.image_id == old_spec.image_id:
                    return _discard_failed(db, record, runtime, spec, "previous_release_retained")
        elif observed.ingress_absent:
            return _discard_failed(db, record, runtime, spec, "activation_not_started")
        return _finish(db, record, "unknown", "runtime_not_confirmed")
    except (RuntimeFailure, HTTPException):
        return _finish(db, record, "unknown", "reconciliation_required")


def start_build_job(
    db: Session, app_id: str, revision: str, build_id: str
) -> tuple[AppBuildJob, bool]:
    build_id = str(UUID(build_id))
    job = db.scalar(select(AppBuildJob).where(AppBuildJob.id == build_id).with_for_update())
    if job is not None:
        if (job.app_id, job.source_revision) != (app_id, revision):
            service.fail("conflict", 409)
        if job.state != "queued":
            db.rollback()
            return job, False
    definition = db.get(AppDefinitionRecord, app_id, populate_existing=True)
    if (
        definition is None
        or definition.source_revision != revision
        or (job is not None and job.definition_digest != definition.definition_digest)
    ):
        if job is None:
            service.fail("conflict", 409)
        job.state, job.failure_code, job.active_slot = "failed", "source_changed", None
        job.updated_at = utcnow_naive()
        db.commit()
        return job, False
    if job is None:
        job = AppBuildJob(
            id=build_id,
            app_id=app_id,
            source_revision=revision,
            definition_digest=definition.definition_digest,
        )
        db.add(job)
        service._commit(db)
        job = db.scalar(select(AppBuildJob).where(AppBuildJob.id == build_id).with_for_update())
    if (job.app_id, job.source_revision, job.definition_digest) != (
        app_id,
        revision,
        definition.definition_digest,
    ):
        service.fail("conflict", 409)
    if job.state != "queued":
        db.rollback()
        return job, False
    from miy_api.domains.independent_apps.delegation import require_build_authority

    try:
        require_build_authority(db, job)
    except HTTPException:
        job.state, job.failure_code, job.active_slot = "failed", "authority_changed", None
        job.updated_at = utcnow_naive()
        db.commit()
        return job, False
    job.state = "running"
    job.active_slot = 1
    try:
        db.commit()
        return job, True
    except IntegrityError:
        db.rollback()
        job = db.scalar(select(AppBuildJob).where(AppBuildJob.id == build_id).with_for_update())
        if job.state == "queued":
            job.failure_code = "build_capacity"
        db.commit()
    return job, False


def persist_verified_build(db: Session, job: AppBuildJob, evidence) -> AppReleaseRecord:
    from miy_api.domains.independent_apps.builds import BuildEvidence
    from miy_api.domains.independent_apps.delegation import require_build_authority

    db.expire_all()  # The builder may have run while its source/grant changed.
    if not isinstance(evidence, BuildEvidence) or job.state != "running" or job.active_slot != 1:
        service.fail("verification_required", 409)
    require_build_authority(db, job)
    if (job.app_id, job.source_revision, job.definition_digest) != (
        evidence.app_id,
        evidence.source_revision,
        evidence.definition_digest,
    ):
        service.fail("verification_required", 409)
    definition = db.get(AppDefinitionRecord, job.app_id)
    if definition is None or (definition.source_revision, definition.definition_digest) != (
        job.source_revision,
        job.definition_digest,
    ):
        service.fail("conflict", 409)
    if (
        evidence.target_environment != "development"
        or not evidence.checks
        or any(code != 0 for code in evidence.checks.values())
    ):
        service.fail("verification_required", 409)
    verification = AppBuildVerification(id=str(uuid4()), build_job_id=job.id, **asdict(evidence))
    db.add(verification)
    db.flush()
    release = db.scalar(
        select(AppReleaseRecord).where(
            AppReleaseRecord.app_id == job.app_id,
            AppReleaseRecord.artifact == evidence.artifact_digest,
        )
    )
    if release is None:
        release = AppReleaseRecord(
            id=str(uuid4()),
            app_id=job.app_id,
            definition_digest=job.definition_digest,
            definition_snapshot=definition.manifest,
            source_revision=job.source_revision,
            artifact=evidence.artifact_digest,
        )
        db.add(release)
    elif (release.source_revision, release.definition_digest) != (
        job.source_revision,
        job.definition_digest,
    ):
        service.fail("conflict", 409)
    release.verification_id = verification.id
    release.verified_at = utcnow_naive()
    db.flush()
    job.release_id = release.id
    job.state = "succeeded"
    job.active_slot = None
    job.updated_at = utcnow_naive()
    db.commit()
    return release
