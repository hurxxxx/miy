"""Scoped candidate definitions and resource ownership for managed app work."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select, update

from miy_api.core.settings import get_settings
from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps import delegation, service
from miy_api.domains.independent_apps.builds import _identity as repository_identity
from miy_api.domains.independent_apps.contracts import (
    AppDefinition,
    InstallationInput,
    RegisterDefinition,
)
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps.workspace_models import (
    AppWorkspaceCandidate,
    AppWorkspaceRecord,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def profile_for(workspace, settings=None):
    settings = settings or get_settings()
    profile = next(
        (p for p in settings.independent_app_workspace_profiles if p.id == workspace.profile_id),
        None,
    )
    if profile is None or profile.identity() != workspace.profile_digest:
        service.fail("local_delivery_only", 409)
    return profile


def for_installation(db, installation_id):
    if installation_id is None:
        return None
    return db.scalar(
        select(AppWorkspaceRecord).where(AppWorkspaceRecord.installation_id == installation_id)
    )


def definition_for_installation(db, app_id, installation_id):
    workspace = for_installation(db, installation_id)
    if workspace is None:
        return db.get(AppDefinitionRecord, app_id, populate_existing=True)
    if workspace.app_id != app_id or workspace.state != "ready":
        return None
    candidate = db.get(AppWorkspaceCandidate, workspace.candidate_id)
    if candidate is None or (candidate.workspace_id, candidate.app_id) != (workspace.id, app_id):
        return None
    return candidate


def require(db, workspace_id, grant, context, *, lock=False):
    query = select(AppWorkspaceRecord).where(AppWorkspaceRecord.id == str(UUID(str(workspace_id))))
    if lock:
        query = query.with_for_update()
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None or (row.app_id, row.parent_installation_id, row.owner_user_id) != (
        grant.app_id,
        grant.installation_id,
        context.user.id,
    ):
        service.fail("not_found", 404)
    profile_for(row)
    return row


def snapshot(db, row):
    installation = db.get(AppInstallationRecord, row.installation_id)
    candidate = db.get(AppWorkspaceCandidate, row.candidate_id)
    profile = profile_for(row)
    return {
        "id": row.id,
        "app_id": row.app_id,
        "version": row.version,
        "state": row.state,
        "profile_id": row.profile_id,
        "definition": candidate.manifest if candidate else None,
        "definition_digest": candidate.definition_digest if candidate else None,
        "source_revision": candidate.source_revision if candidate else None,
        "installation": service.installation_out(installation).model_dump(mode="json"),
        "portal_url": f"{profile.platform_origin}/apps/{row.app_id}/installed/{row.installation_id}",
        "permanent_portal_url": f"{profile.platform_origin}/apps/{row.app_id}/installed/{row.parent_installation_id}",
        "integration_revision": row.integration_revision,
        "integration_deployment_id": (row.resources or {}).get("integration_deployment_id"),
        "source_handoff_complete": bool(
            row.integration_revision and (row.resources or {}).get("integration_deployment_id")
        ),
    }


def _candidate(db, workspace, definition, revision):
    manifest = definition.model_dump(mode="json")
    candidate_id = digest({"workspace": workspace.id, "manifest": manifest, "revision": revision})
    candidate = db.get(AppWorkspaceCandidate, candidate_id)
    if candidate is None:
        candidate = AppWorkspaceCandidate(
            id=candidate_id,
            workspace_id=workspace.id,
            app_id=workspace.app_id,
            manifest=manifest,
            definition_digest=definition.content_digest(),
            source_revision=revision,
        )
        db.add(candidate)
        db.flush()
    workspace.candidate_id = candidate.id
    workspace.updated_at = utcnow_naive()
    return candidate


def prepare(db, workspace_id, data, grant, context):
    workspace_id = str(UUID(str(workspace_id)))
    profile = next(
        (p for p in get_settings().independent_app_workspace_profiles if p.id == data.profile_id),
        None,
    )
    if profile is None:
        service.fail("local_delivery_only", 409)
    manifest = data.definition.model_dump(mode="json")
    if (
        data.definition.app_id != grant.app_id
        or repository_identity(data.definition.source.repository)
        != repository_identity(profile.repository)
        or data.definition.source.directory != f"personal-apps/{grant.app_id}"
        or delegation.definition_policy(manifest) != grant.definition_policy
    ):
        service.fail("forbidden")
    creation = digest(data.model_dump(mode="json"))
    # The parent's row serializes creates for one app; the DB unique slot also
    # prevents other apps taking the same operator origin in parallel.
    parent = db.scalar(
        select(AppInstallationRecord)
        .where(AppInstallationRecord.id == grant.installation_id)
        .with_for_update()
    )
    existing = db.get(AppWorkspaceRecord, workspace_id)
    if existing:
        row = require(db, workspace_id, grant, context)
        if row.creation_digest != creation:
            service.fail("conflict", 409)
        return snapshot(db, row)
    used = set(
        db.scalars(
            select(AppWorkspaceRecord.slot).where(
                AppWorkspaceRecord.profile_id == profile.id, AppWorkspaceRecord.slot.is_not(None)
            )
        )
    )
    slot = next((i for i in range(len(profile.origins)) if i not in used), None)
    if slot is None:
        service.fail("local_delivery_only", 409)
    endpoint = profile.origins[slot]
    installation = service.stage_installation(
        db,
        grant.app_id,
        InstallationInput(
            environment="development",
            origin=endpoint.origin,
            enabled=True,
            audience="selected",
            user_ids=[context.user.id],
            group_ids=[],
            granted_permissions=parent.granted_permissions,
        ),
        context,
        platform_origin=profile.platform_origin,
    )
    row = AppWorkspaceRecord(
        id=workspace_id,
        app_id=grant.app_id,
        owner_user_id=context.user.id,
        parent_installation_id=parent.id,
        installation_id=installation.id,
        profile_id=profile.id,
        profile_digest=profile.identity(),
        creation_digest=creation,
        slot=slot,
    )
    db.add(row)
    db.flush()
    _candidate(db, row, data.definition, data.source_revision)
    service._audit(db, context, "workspace.prepare", grant.app_id)
    service._commit(db)
    return snapshot(db, row)


def sync(db, workspace_id, data, grant, context):
    row = require(db, workspace_id, grant, context, lock=True)
    manifest = data.definition.model_dump(mode="json")
    if row.state != "ready" or delegation.definition_policy(manifest) != grant.definition_policy:
        service.fail("forbidden")
    current = db.get(AppWorkspaceCandidate, row.candidate_id)
    if current and (current.source_revision, current.definition_digest) == (
        data.source_revision,
        data.definition.content_digest(),
    ):
        return snapshot(db, row)
    if data.expected_version != row.version:
        service.fail("conflict", 409)
    _candidate(db, row, data.definition, data.source_revision)
    row.version += 1
    service._commit(db)
    return snapshot(db, row)


def runtime_target(db, installation, settings=None):
    row = for_installation(db, installation.id)
    if row is None or row.slot is None or row.state == "cleaned":
        return None
    profile = profile_for(row, settings)
    slot = profile.origins[row.slot]
    if (installation.app_id, installation.environment, installation.origin) != (
        row.app_id,
        "development",
        slot.origin,
    ):
        service.fail("conflict", 409)
    # Builds read immutable objects from the operator's repository, not a mutable
    # worktree path supplied by an API caller. Git worktrees share these objects.
    return IndependentDeliveryTarget(
        app_id=row.app_id,
        installation_id=installation.id,
        source_root=profile.repository_root,
        work_root=profile.work_root / row.id,
        state_root=profile.state_root / row.id,
        toolchain_image=profile.toolchain_image,
        ingress_image=profile.ingress_image,
        platform_origin=profile.platform_origin,
        platform_api_origin=profile.platform_api_origin,
        app_origin=slot.origin if slot.origin.startswith("https://") else None,
        loopback_port=slot.port if slot.origin.startswith("https://") else None,
    )


def configured_targets(db, settings):
    return [
        target
        for installation in db.scalars(
            select(AppInstallationRecord).join(
                AppWorkspaceRecord, AppWorkspaceRecord.installation_id == AppInstallationRecord.id
            )
        )
        if (target := runtime_target(db, installation, settings)) is not None
    ]


def integrated_source_target(db, target, settings=None):
    """Persist the trusted source handoff after the temporary workspace is gone.

    Runtime origin, state and installed data remain the stable operator binding.
    Only an integration receipt matching the current canonical definition may
    select the platform repository as immutable build input.
    """
    if target.environment != "development":
        return target
    canonical = db.get(AppDefinitionRecord, target.app_id)
    if canonical is None:
        return target
    row = db.scalar(
        select(AppWorkspaceRecord)
        .where(
            AppWorkspaceRecord.parent_installation_id == str(target.installation_id),
            AppWorkspaceRecord.app_id == target.app_id,
            AppWorkspaceRecord.integration_revision == canonical.source_revision,
        )
        .order_by(AppWorkspaceRecord.updated_at.desc())
        .limit(1)
    )
    if row is None:
        return target
    settings = settings or get_settings()
    profile = next(
        (p for p in settings.independent_app_workspace_profiles if p.id == row.profile_id), None
    )
    handoff = (row.resources or {}).get("source_handoff", {})
    if profile is None or handoff.get("repository_root") != str(profile.repository_root):
        service.fail("local_delivery_only", 409)
    # Growing the temporary origin pool after cleanup does not invalidate the
    # permanent source handoff. Its approved repository identity still must match.
    if handoff.get("repository_identity") != list(repository_identity(profile.repository)):
        service.fail("conflict", 409)
    definition = AppDefinition.model_validate(canonical.manifest)
    if (
        repository_identity(definition.source.repository) != repository_identity(profile.repository)
        or definition.source.directory != f"personal-apps/{target.app_id}"
    ):
        service.fail("conflict", 409)
    return target.model_copy(
        update={"source_root": profile.repository_root, "toolchain_image": profile.toolchain_image}
    )


def transition(db, grant, context, workspace_id, data, *, action):
    from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeploymentRequest

    row = require(db, workspace_id, grant, context, lock=True)
    wanted = {"stop": "stopping", "resume": "ready", "cleanup": "cleanup_pending"}[action]
    if (
        row.state == wanted
        or (action == "stop" and row.state == "stopped")
        or (action == "cleanup" and row.state == "cleaned")
    ):
        return snapshot(db, row)
    if row.state in {"cleanup_pending", "cleaned"}:
        service.fail("conflict", 409)
    if row.version != data.expected_version:
        service.fail("conflict", 409)
    if action == "resume" and row.state != "stopped":
        service.fail("conflict", 409)
    if action == "cleanup" and not (row.resources or {}).get("integration_deployment_id"):
        service.fail("verification_required", 409)
    installation = db.scalar(
        select(AppInstallationRecord)
        .where(AppInstallationRecord.id == row.installation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    installation.enabled = action == "resume"
    installation.generation += 1
    installation.state = "configured" if action == "resume" else "disabled"
    # Only queued, unclaimed requests are cancelled. Running/unknown work keeps
    # its durable ownership and must be reconciled before maintenance proceeds.
    for model in (AppBuildJob, AppDeploymentRequest):
        db.execute(
            update(model)
            .where(
                model.installation_id == installation.id,
                model.state == "queued",
                model.active_slot.is_(None),
            )
            .values(state="failed", failure_code="workspace_stopped", updated_at=utcnow_naive())
            .execution_options(synchronize_session=False)
        )
    row.state, row.version = wanted, row.version + 1
    row.updated_at = utcnow_naive()
    service._audit(db, context, "workspace." + action, row.app_id)
    service._commit(db)
    return snapshot(db, row)


def integrate(db, grant, context, workspace_id, data):
    """Only a commit already on the trusted remote dev ref may become canonical."""
    import os
    import tempfile
    from miy_api.domains.independent_apps import builds

    row = require(db, workspace_id, grant, context, lock=True)
    delegation.validate(db, grant, "sync", grant.app_id, grant.installation_id)
    if (
        row.state != "ready"
        or delegation.definition_policy(data.definition.model_dump(mode="json"))
        != grant.definition_policy
    ):
        service.fail("forbidden")
    canonical = service.owned_definition(db, row.app_id, context)
    if row.integration_revision == data.source_revision and (
        canonical.source_revision,
        canonical.definition_digest,
    ) == (data.source_revision, data.definition.content_digest()):
        return snapshot(db, row)
    if row.version != data.expected_version:
        service.fail("conflict", 409)
    profile = profile_for(row)
    env = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
    }
    args = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(profile.repository_root),
    ]
    try:
        builds._required(
            [*args, "merge-base", "--is-ancestor", data.source_revision, "refs/remotes/origin/dev"],
            env=env,
        )
        subtree = data.definition.source.directory
        expected_tree = builds._required(
            [*args, "rev-parse", data.source_revision + ":" + subtree], env=env
        )
        latest_tree = builds._required(
            [*args, "rev-parse", "refs/remotes/origin/dev:" + subtree], env=env
        )
        if expected_tree != latest_tree:
            service.fail("conflict", 409)
        with tempfile.TemporaryDirectory(prefix="miy-integrated-source-") as path:
            from pathlib import Path

            builds._snapshot(
                profile.repository_root, data.source_revision, data.definition, Path(path)
            )
    except builds.BuildFailure:
        service.fail("verification_required", 409)
    service.stage_definition(
        db,
        RegisterDefinition(
            definition=data.definition,
            source_revision=data.source_revision,
            expected_digest=data.expected_digest,
            expected_source_revision=data.expected_source_revision,
        ),
        context,
    )
    row.integration_revision = data.source_revision
    row.resources = {
        k: v for k, v in (row.resources or {}).items() if k != "integration_deployment_id"
    }
    row.resources = {
        **row.resources,
        "source_handoff": {
            "repository_root": str(profile.repository_root),
            "repository_identity": list(repository_identity(profile.repository)),
        },
    }
    row.version += 1
    service._commit(db)
    return snapshot(db, row)


def confirm_integration(db, grant, context, workspace_id, deployment_id):
    from miy_api.domains.independent_apps.delivery_models import AppDeploymentRequest
    from miy_api.domains.independent_apps.models import AppReleaseRecord

    row = require(db, workspace_id, grant, context, lock=True)
    receipt = db.get(AppDeploymentRequest, str(deployment_id))
    release = db.get(AppReleaseRecord, receipt.release_id) if receipt else None
    parent = db.get(AppInstallationRecord, row.parent_installation_id)
    if (
        receipt is None
        or release is None
        or not row.integration_revision
        or receipt.installation_id != row.parent_installation_id
        or receipt.actor_user_id != context.user.id
        or receipt.state != "succeeded"
        or receipt.observed_image_id != release.artifact
        or release.source_revision != row.integration_revision
        or parent.release_id != release.id
        or parent.state != "ready"
    ):
        service.fail("verification_required", 409)
    row.resources = {**(row.resources or {}), "integration_deployment_id": receipt.id}
    service._commit(db)
    return snapshot(db, row)
