"""Optional queue selection; existing delivery consumers own claims and side effects."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable
from threading import Event

from sqlalchemy import and_, func, or_, select

from miy_api.core.independent_delivery_settings import validate_targets
from miy_api.core.settings import WORKSPACE_ROOT, Settings
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeploymentRequest
from miy_api.domains.independent_apps.models import AppInstallationRecord


def poll_once(settings: Settings, session_factory, consume: Callable[[Namespace], dict]) -> dict:
    targets = validate_targets(
        settings.independent_app_delivery_targets,
        platform_root=WORKSPACE_ROOT,
        platform_origins=settings.independent_app_platform_origins,
    )
    if not targets and not settings.independent_app_workspace_profiles:
        return {"state": "disabled"}
    # Each bounded tick gives independent maintenance and search work a turn,
    # even while a delivery retains its same-request unknown reservation.
    maintenance = {"state": "idle"}
    if settings.independent_app_workspace_profiles:
        from miy_api.domains.independent_apps.workspace_maintenance import poll_once as maintain

        maintenance = maintain(settings, session_factory)
    search = (
        poll_search(settings, session_factory)
        if settings.independent_app_search_enabled
        else {"state": "idle"}
    )
    background = maintenance if maintenance["state"] != "idle" else search
    from miy_api.domains.independent_apps.workspaces import (
        configured_targets,
        integrated_source_target,
    )

    with session_factory() as db:
        targets = [
            *[integrated_source_target(db, t, settings) for t in targets],
            *configured_targets(db, settings),
        ]
    if not targets:
        return background
    by_installation = {str(target.installation_id): target for target in targets}
    bindings = or_(
        *(
            and_(
                AppInstallationRecord.id == str(target.installation_id),
                AppInstallationRecord.app_id == target.app_id,
                AppInstallationRecord.environment == target.environment,
            )
            for target in targets
        )
    )
    candidates = []
    # The selection transaction never spans slow work. Another consumer may see
    # the same row; the existing authoritative claim/fence resolves that race.
    with session_factory() as db:
        interrupted = db.scalar(
            select(AppDeploymentRequest)
            .join(
                AppInstallationRecord,
                AppInstallationRecord.id == AppDeploymentRequest.installation_id,
            )
            .where(
                bindings,
                AppDeploymentRequest.executor_id == "local",
                AppDeploymentRequest.state.in_(["running", "unknown", "cleanup"]),
                func.json_typeof(AppDeploymentRequest.runtime_config) == "object",
            )
            .order_by(AppDeploymentRequest.updated_at, AppDeploymentRequest.id)
            .with_for_update(skip_locked=True, of=AppDeploymentRequest)
            .limit(1)
        )
        if interrupted is not None and interrupted.runtime_config is not None:
            # Row locks skip in-flight daemon work. The consumer's separate
            # transaction advisory guard also covers commit/reacquire windows.
            # Reconciliation observes prior work; it never prepares/activates.
            candidates.append(
                (
                    interrupted.updated_at,
                    interrupted.id,
                    interrupted.installation_id,
                    "reconcile",
                    interrupted.state,
                    interrupted.active_slot,
                )
            )
        for model, command in ((AppBuildJob, "build-request"), (AppDeploymentRequest, "execute")):
            if db.scalar(
                select(model.id)
                .where(model.executor_id == "local", model.active_slot == 1)
                .limit(1)
            ):
                continue
            query = (
                select(model)
                .join(AppInstallationRecord, AppInstallationRecord.id == model.installation_id)
                .where(
                    bindings,
                    model.executor_id == "local",
                    model.state == "queued",
                )
                .order_by(model.updated_at, model.id)
                .limit(1)
            )
            if model is AppBuildJob:
                query = query.where(
                    AppInstallationRecord.environment == "development",
                    AppBuildJob.delegation_id.is_not(None),
                    AppBuildJob.app_id == AppInstallationRecord.app_id,
                )
            row = db.scalar(query)
            if row is not None:
                candidates.append(
                    (
                        row.updated_at,
                        row.id,
                        row.installation_id,
                        command,
                        row.state,
                        row.active_slot,
                    )
                )
    if not candidates:
        return background
    attempted_at, request_id, installation_id, command, selected_state, selected_slot = min(
        candidates
    )
    target = by_installation[installation_id]
    target.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    args = {
        "command": command,
        "app_id": target.app_id,
        "installation_id": installation_id,
    }
    if command == "build-request":
        args.update(
            build_id=request_id,
            source=target.source_root,
            work_root=target.work_root,
            toolchain_image=target.toolchain_image,
        )
    else:
        args.update(
            request_id=request_id,
            state_root=target.state_root,
            ingress_image=target.ingress_image,
            platform_origin=target.platform_origin,
            platform_api_origin=target.platform_api_origin,
        )
    # All paths/images come from operator settings. API rows carry intent only.
    result = consume(Namespace(**args))
    if result.get("state") == "unknown" and result.get("failure_code") == "operator_check_required":
        model = AppBuildJob if command == "build-request" else AppDeploymentRequest
        with session_factory() as db:
            unchanged = db.scalar(
                select(model)
                .where(
                    model.id == request_id,
                    model.updated_at == attempted_at,
                    model.state == selected_state,
                    model.active_slot.is_(None)
                    if selected_slot is None
                    else model.active_slot == selected_slot,
                )
                .with_for_update(skip_locked=True)
            )
            if unchanged is not None:
                # Configuration failure is an attempt, not a state transition.
                # Never overwrite a live or independently updated consumer's work.
                unchanged.updated_at = utcnow_naive()
                db.commit()
    return result


def serve(
    poll: Callable[[], dict], *, stop: Event, emit: Callable[[dict], None], poll_seconds: float
) -> None:
    if not 1 <= poll_seconds <= 60:
        raise ValueError("Poll interval must be between 1 and 60 seconds")
    while not stop.is_set():
        result = poll()
        # Emit operation transitions, not a perpetual idle heartbeat.
        if result["state"] != "idle":
            emit(result)
        if result["state"] == "disabled":
            raise ValueError("Configure at least one explicit delivery target before serving")
        stop.wait(poll_seconds)


def poll_search(settings, session_factory):
    """Rotate one active installation per delivery tick; no extra daemon."""
    from miy_api.domains.independent_apps.search_models import AppSearchBindingRecord
    from miy_api.domains.independent_apps.search_consumer import run_once

    with session_factory() as db:
        identity = db.scalar(
            select(AppSearchBindingRecord.installation_id)
            .join(
                AppInstallationRecord,
                AppInstallationRecord.id == AppSearchBindingRecord.installation_id,
            )
            .where(
                AppSearchBindingRecord.state == "ready",
                AppInstallationRecord.enabled.is_(True),
                AppInstallationRecord.release_id.is_not(None),
            )
            .order_by(AppSearchBindingRecord.updated_at, AppSearchBindingRecord.installation_id)
            .limit(1)
        )
        if identity is None:
            return {"state": "idle"}
        for row in db.scalars(
            select(AppSearchBindingRecord).where(
                AppSearchBindingRecord.installation_id == identity,
                AppSearchBindingRecord.state == "ready",
            )
        ):
            row.updated_at = utcnow_naive()
        db.commit()
    try:
        result = run_once(session_factory, installation_id=identity, settings=settings)
        return (
            {"state": "idle"} if result == "idle" else {"state": result, "operation": "app_search"}
        )
    except Exception:  # consumer owns bounded durable uncertainty, never surface source text
        return {"state": "held", "operation": "app_search"}
