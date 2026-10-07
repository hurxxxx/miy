"""Narrow owner-only configuration, never runtime activation or provisioning."""

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.core.app_origins import exact_origin
from miy_api.core.settings import get_settings
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.auth.models import CompanyAppControl
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppBuildVerification,
    AppDeploymentRequest,
)
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps.owner_preview_contracts import (
    OwnerPreviewOut,
    OwnerPreviewPatch,
    UnavailableReason,
)

LOCK_TIMEOUT_MS = 5000


def _transaction(db: Session) -> None:
    with db.no_autoflush:
        if (
            db.connection().connection.driver_connection.autocommit is True
            or db.scalar(text("SELECT current_setting('transaction_isolation')"))
            != "read committed"
        ):
            service.fail("forbidden")
        db.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{LOCK_TIMEOUT_MS}ms"},
        )


def _owner(db: Session, owner_id: str, session_id: str) -> AuthContext:
    with db.no_autoflush:
        current = resolve_auth_context_from_session_id(db, session_id)
    if current.user.id != owner_id or current.impersonator_user_id is not None:
        service.fail("forbidden")
    return current


def _boundary(definition, installation, owner_id: str) -> None:
    if (
        definition is None
        or installation is None
        or definition.owner_user_id != owner_id
        or definition.manifest["ownership"] != "personal"
        or installation.app_id != definition.app_id
        or installation.environment != "development"
        or installation.audience != "selected"
        or installation.user_ids != [owner_id]
        or installation.group_ids != []
    ):
        service.fail("not_found", 404)


def _reason(
    db: Session,
    definition: AppDefinitionRecord,
    installation: AppInstallationRecord,
    company_enabled: bool,
    platform_origin: str,
) -> UnavailableReason | None:
    if (
        installation.release_id is not None
        or installation.runtime_ref is not None
        or installation.state not in {"configured", "disabled"}
    ):
        return "already_deployed"
    if db.scalar(
        select(AppDeploymentRequest.id)
        .where(
            AppDeploymentRequest.installation_id == installation.id,
            AppDeploymentRequest.state.not_in(("failed", "succeeded")),
        )
        .limit(1)
    ):
        return "delivery_in_progress"
    # A core operator's build may not carry an installation ID. This initial
    # configuration surface therefore fences the whole app, not just delegated jobs.
    if db.scalar(
        select(AppBuildJob.id)
        .where(
            AppBuildJob.app_id == definition.app_id,
            AppBuildJob.state.not_in(("failed", "succeeded")),
        )
        .limit(1)
    ):
        return "build_in_progress"
    if db.scalar(
        select(AppBuildVerification.id)
        .where(
            AppBuildVerification.app_id == definition.app_id,
            AppBuildVerification.revoked_at.is_(None),
        )
        .limit(1)
    ):
        return "already_verified"
    if not company_enabled:
        return "company_disabled"
    platform_origins = get_settings().independent_app_platform_origins
    if not platform_origins:
        return "origin_configuration_required"
    try:
        canonical = exact_origin(installation.origin)
    except ValueError:
        return "invalid_origin"
    if (
        canonical != installation.origin
        or canonical == platform_origin
        or canonical in platform_origins
    ):
        return "invalid_origin"
    return None


def _snapshot(db, definition, installation, platform_origin: str) -> OwnerPreviewOut:
    company = db.get(CompanyAppControl, definition.app_id, populate_existing=True)
    company_enabled = company is not None and company.enabled
    reason = _reason(db, definition, installation, company_enabled, platform_origin)
    return OwnerPreviewOut(
        app_id=definition.app_id,
        installation_id=installation.id,
        owner_user_id=definition.owner_user_id,
        display_name=definition.manifest["display"]["name"],
        origin=installation.origin,
        generation=installation.generation,
        definition_digest=definition.definition_digest,
        source_revision=definition.source_revision,
        runtime_profile=definition.manifest["runtime_profile"],
        requested_permissions=definition.manifest["requested_permissions"],
        granted_permissions=sorted(installation.granted_permissions),
        enabled=installation.enabled,
        company_enabled=company_enabled,
        can_configure=reason is None,
        unavailable_reason=reason,
    )


def _database_error(db: Session, error: DBAPIError) -> None:
    db.rollback()
    if getattr(error.orig, "sqlstate", None) == "55P03":
        service.fail("preview_busy", 503)


def read(
    db: Session,
    app_id: str,
    installation_id: str,
    context: AuthContext,
    *,
    platform_origin: str,
) -> OwnerPreviewOut:
    owner_id, session_id = context.user.id, context.session.id
    try:
        _transaction(db)
        if context.impersonator_user_id is not None:
            service.fail("forbidden")
        _owner(db, owner_id, session_id)
        row = db.execute(
            select(AppDefinitionRecord, AppInstallationRecord)
            .join(AppInstallationRecord, AppInstallationRecord.app_id == AppDefinitionRecord.app_id)
            .where(
                AppDefinitionRecord.app_id == app_id,
                AppInstallationRecord.id == installation_id,
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            service.fail("not_found", 404)
        definition, installation = row
        _boundary(definition, installation, owner_id)
        result = _snapshot(db, definition, installation, platform_origin)
        _owner(db, owner_id, session_id)
        return result
    except DBAPIError as error:
        _database_error(db, error)
        raise
    finally:
        db.rollback()


def configure(
    db: Session,
    app_id: str,
    installation_id: str,
    data: OwnerPreviewPatch,
    context: AuthContext,
    *,
    platform_origin: str,
) -> OwnerPreviewOut:
    owner_id, session_id = context.user.id, context.session.id
    try:
        _transaction(db)
        if context.impersonator_user_id is not None:
            service.fail("forbidden")
        _owner(db, owner_id, session_id)
        # Fixed definition -> installation order also holds FK insertions until
        # commit. Do not acquire deployment/job row locks in the reverse order
        # of an executor; late queued work still has its installation generation fence.
        definition = db.scalar(
            select(AppDefinitionRecord)
            .where(AppDefinitionRecord.app_id == app_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if definition is None or definition.owner_user_id != owner_id:
            service.fail("not_found", 404)
        installation = db.scalar(
            select(AppInstallationRecord)
            .where(
                AppInstallationRecord.id == installation_id,
                AppInstallationRecord.app_id == app_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        _owner(db, owner_id, session_id)
        _boundary(definition, installation, owner_id)
        if (
            installation.generation,
            definition.definition_digest,
            definition.source_revision,
        ) != (
            data.expected_generation,
            data.expected_definition_digest,
            data.expected_source_revision,
        ):
            service.fail("conflict", 409)
        before = _snapshot(db, definition, installation, platform_origin)
        if not before.can_configure:
            service.fail("conflict", 409)
        if not set(data.granted_permissions).issubset(before.requested_permissions):
            service.fail("forbidden")
        if (installation.enabled, before.granted_permissions) == (
            data.enabled,
            data.granted_permissions,
        ):
            _owner(db, owner_id, session_id)
            db.rollback()
            return before
        installation.enabled = data.enabled
        installation.granted_permissions = data.granted_permissions
        installation.state = "configured" if data.enabled else "disabled"
        installation.generation += 1
        record_audit_log(
            db,
            actor_user_id=owner_id,
            action="independent_app.owner_preview.configure",
            entity_kind="independent_app",
            entity_id=None,
            summary="Owner private development preview access changed",
            payload={
                "app_id": app_id,
                "installation_id": installation_id,
                "definition_digest": definition.definition_digest,
                "source_revision": definition.source_revision,
                "before": {
                    "generation": before.generation,
                    "enabled": before.enabled,
                    "granted_permissions": before.granted_permissions,
                },
                "after": {
                    "generation": installation.generation,
                    "enabled": installation.enabled,
                    "granted_permissions": installation.granted_permissions,
                },
            },
        )
        db.flush()
        _owner(db, owner_id, session_id)
        _boundary(definition, installation, owner_id)
        result = _snapshot(db, definition, installation, platform_origin)
        if not result.can_configure:
            service.fail("conflict", 409)
        db.commit()
        return result
    except DBAPIError as error:
        _database_error(db, error)
        raise
    except BaseException:
        db.rollback()
        raise
