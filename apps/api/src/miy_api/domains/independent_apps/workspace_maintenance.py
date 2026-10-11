"""Finite Core maintenance for explicitly stopped/merged temporary workspaces."""

from sqlalchemy import select, text, update

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.data_store import configured_store
from miy_api.domains.independent_apps.delivery import RuntimeSpec
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppDeploymentRequest,
    AppRuntimeSlot,
)
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.production import binding_digest
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from miy_api.domains.independent_apps.workspaces import runtime_target


def runtime_for(target, settings):
    return DockerRuntime(
        state_root=target.state_root,
        ingress_image=target.ingress_image,
        platform_origin=target.platform_origin,
        platform_api_origin=target.platform_api_origin,
        app_origin=target.app_origin,
        loopback_port=target.loopback_port,
        operator_binding_digest=binding_digest(target),
        environment="development",
    )


def poll_once(settings, factory, *, make_runtime=runtime_for):
    # The advisory transaction is separate from receipt transactions, so the
    # ownership fence survives durable progress commits and is released on loss.
    with factory() as fence:
        candidates = list(
            fence.scalars(
                select(AppWorkspaceRecord)
                .where(AppWorkspaceRecord.state.in_(["stopping", "cleanup_pending"]))
                .order_by(AppWorkspaceRecord.updated_at, AppWorkspaceRecord.id)
                .limit(16)
            )
        )
        held = None
        for candidate in candidates:
            workspace_id = candidate.id
            attempt = (candidate.state, candidate.version, candidate.updated_at)
            if not fence.scalar(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": "miy-workspace-maintenance:" + workspace_id},
            ):
                continue
            try:
                result = _maintain(settings, factory, workspace_id, make_runtime)
            except Exception:  # bounded diagnostics; retain ownership and retry observation
                result = {
                    "state": "unknown",
                    "workspace_id": workspace_id,
                    "failure_code": "workspace_cleanup_held",
                }
            if result["state"] in {"stopped", "cleaned"}:
                return result
            if result["state"] != "idle":
                _record_attempt(factory, workspace_id, attempt)
                held = held or result
        return held or {"state": "idle"}


def _record_attempt(factory, workspace_id, attempt):
    """Rotate held work without overwriting a concurrent transition or receipt."""
    state, version, updated_at = attempt
    with factory() as db:
        row = db.scalar(
            select(AppWorkspaceRecord)
            .where(
                AppWorkspaceRecord.id == workspace_id,
                AppWorkspaceRecord.state == state,
                AppWorkspaceRecord.version == version,
                AppWorkspaceRecord.updated_at == updated_at,
            )
            .with_for_update(skip_locked=True)
        )
        if row is not None:
            row.updated_at = utcnow_naive()
            db.commit()


def _maintain(settings, factory, workspace_id, make_runtime):
    with factory() as db:
        row = db.get(AppWorkspaceRecord, workspace_id)
        if row is None or row.state not in {"stopping", "cleanup_pending"}:
            return {"state": "idle"}
        stop_identity = (row.version, row.installation_id)
        installation = db.get(AppInstallationRecord, row.installation_id)
        if (
            installation is None
            or installation.enabled
            or installation.environment != "development"
        ):
            raise ValueError("Workspace admission must be closed")
        for model in (AppBuildJob, AppDeploymentRequest):
            if db.scalar(
                select(model.id)
                .where(
                    model.installation_id == installation.id,
                    model.state.in_(["queued", "running", "unknown", "cleanup"]),
                )
                .limit(1)
            ):
                return {
                    "state": "waiting",
                    "workspace_id": row.id,
                    "failure_code": "workspace_delivery_reconciliation_required",
                }
        target = runtime_target(db, installation, settings)
        if target is None:
            raise ValueError("Workspace operator binding is unavailable")
        cleanup_identity = (installation.origin, installation.generation, row.slot)
        requests = list(
            db.scalars(
                select(AppDeploymentRequest)
                .where(
                    AppDeploymentRequest.installation_id == installation.id,
                    AppDeploymentRequest.runtime_config.is_not(None),
                )
                .order_by(AppDeploymentRequest.created_at, AppDeploymentRequest.id)
            )
        )
        specs = [RuntimeSpec(**r.runtime_config) for r in requests if r.runtime_config is not None]
        runtime = make_runtime(target, settings)
        runtime.stop_workspace(specs, installation_id=installation.id)
        slot = db.get(AppRuntimeSlot, installation.id)
        if slot is not None:
            db.delete(slot)
        db.refresh(row)
        if row.state == "stopping":
            # An owner may approve cleanup after this observation. Complete
            # only the stop we observed; never overwrite that newer intent.
            completed = db.execute(
                update(AppWorkspaceRecord)
                .where(
                    AppWorkspaceRecord.id == workspace_id,
                    AppWorkspaceRecord.state == "stopping",
                    AppWorkspaceRecord.version == stop_identity[0],
                    AppWorkspaceRecord.installation_id == stop_identity[1],
                )
                .values(state="stopped", updated_at=utcnow_naive())
                .execution_options(synchronize_session=False)
            )
            if completed.rowcount != 1:
                db.rollback()
                return {"state": "idle"}
            db.commit()
            return {"state": "stopped", "workspace_id": workspace_id}
        if row.state != "cleanup_pending" or not (row.resources or {}).get(
            "integration_deployment_id"
        ):
            raise ValueError("Merged development runtime receipt is required")
        from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
        from miy_api.domains.independent_apps.search_consumer import cleanup_binding

        bindings = list(
            db.scalars(
                select(AppSearchBindingRecord).where(
                    AppSearchBindingRecord.installation_id == installation.id,
                    AppSearchBindingRecord.state != "removed",
                )
            )
        )
        for binding in bindings:
            if binding.workspace_id != row.id:
                raise ValueError("Search resources have another owner")
            if binding.state == "ready":
                binding.state = "stopped"
            elif binding.state == "cleanup_pending" and binding.cleanup_phase in {
                "verified",
                "keyword_removed",
                "vector_removed",
            }:
                pass
            elif binding.state != "stopped":
                raise ValueError("Uncertain search resources require reconciliation")
        db.commit()
        for binding in bindings:
            cleanup_binding(
                factory,
                installation_id=installation.id,
                generation=binding.generation,
                settings=settings,
            )

        def persist_receipt(receipt):
            row.resources = {**(row.resources or {}), "data_cleanup": receipt}
            db.commit()

        # Verify positive absence too; no broad prefix/age-based deletion.
        if bindings or any(s.runtime_profile == "web-api-postgres-v1" for s in specs):
            configured_store(settings).remove_temporary(
                installation_id=installation.id,
                app_id=row.app_id,
                environment="development",
                receipt=(row.resources or {}).get("data_cleanup"),
                persist_receipt=persist_receipt,
            )
        runtime.clean_workspace_files(specs, installation_id=installation.id)
        if target.work_root.exists():
            if target.work_root.is_symlink():
                raise ValueError("Build scratch identity changed")
            target.work_root.rmdir()  # Unknown/nonempty scratch is retained, never recursively erased.
        # Receipt commits release ordinary row locks. Fence the final release
        # against an owner changing admission while external cleanup ran.
        row = db.scalar(
            select(AppWorkspaceRecord)
            .where(AppWorkspaceRecord.id == workspace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        installation = db.scalar(
            select(AppInstallationRecord)
            .where(AppInstallationRecord.id == row.installation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row.state != "cleanup_pending"
            or installation.enabled
            or installation.state != "disabled"
            or (installation.origin, installation.generation, row.slot) != cleanup_identity
        ):
            raise ValueError("Workspace cleanup identity changed")
        # The origin is a live security-principal claim. Release it only after
        # exact runtime/data cleanup, atomically with the operator slot. Keep
        # the original installation and all FK-bound delivery/session history.
        installation.archived_origin = installation.origin
        installation.origin = None
        installation.state = "archived"
        installation.generation += 1
        row.resources = {
            **(row.resources or {}),
            "installation_archive": {
                "installation_id": installation.id,
                "origin": installation.archived_origin,
                "generation": installation.generation,
                "profile_id": row.profile_id,
                "slot": row.slot,
            },
        }
        row.state, row.slot = "cleaned", None
        row.updated_at = utcnow_naive()
        db.commit()
        return {"state": "cleaned", "workspace_id": row.id}
