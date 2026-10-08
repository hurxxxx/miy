"""Core approval and a read-only identity bridge, not a new login protocol.

No HTTP endpoint or app manifest can create these bindings. The composition
layer supplies the logical app from its owned route; app input never selects it.
Resource ACLs remain the responsibility of the existing business handlers.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miy_api.core.app_contracts_generated import OFFICIAL_APP_IDS
from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.access import record_audit_log, resolve_system_roles
from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.dependencies import AuthContext, resolve_auth_context_from_session_id
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import hash_token, new_id
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppSession
from miy_api.domains.independent_apps.service import SourceUserLoader, app_identity
from miy_api.domains.independent_apps.verification import trusted_release
from miy_api.domains.official_apps.models import OfficialAppBinding


def _denied() -> None:
    raise localized_http_exception(
        status_code=403, code="auth.system_role_required", roles="official binding"
    )


def _require_authority_transaction(db: Session) -> None:
    # populate_existing refreshes ORM state, not a REPEATABLE READ snapshot.
    # AUTOCOMMIT also releases row locks before the approval/audit transaction.
    if (
        db.connection().connection.driver_connection.autocommit is True
        or db.scalar(text("SELECT current_setting('transaction_isolation')")) != "read committed"
    ):
        _denied()


def _core_admin(db: Session, context: AuthContext) -> AuthContext:
    current = resolve_auth_context_from_session_id(db, context.session.id)
    if (
        current.user.id != context.user.id
        or current.impersonator_user_id is not None
        or "platform_admin" not in current.system_roles
    ):
        _denied()
    return current


def approve_binding(
    db: Session,
    context: AuthContext,
    *,
    installation_id: str,
    expected_generation: int,
    expected_release_id: str,
    expected_artifact: str,
    logical_app_ids: frozenset[str],
) -> OfficialAppBinding:
    """Core-only approval of a reviewed artifact; caller commits approval+audit.

    Approval itself does not activate the official service or change routing.
    One immutable binding per generation forces a new reviewed deployment after
    revocation or a scope change. Application owners cannot self-approve.
    """
    _require_authority_transaction(db)
    _core_admin(db, context)
    installation = db.scalar(
        select(AppInstallationRecord)
        .where(AppInstallationRecord.id == installation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Installation changes can keep this transaction waiting. Authority read
    # before that wait must not authorize an approval after session/role revoke.
    admin = _core_admin(db, context)
    release = trusted_release(db, installation, expected_release_id) if installation else None
    if (
        installation is None
        or not installation.enabled
        or installation.state != "ready"
        or not installation.runtime_ref
        or (installation.generation, installation.release_id)
        != (expected_generation, expected_release_id)
        or release is None
        or release.artifact != expected_artifact
        or release.definition_snapshot.get("ownership") != "official"
        or not logical_app_ids
        or not logical_app_ids <= OFFICIAL_APP_IDS
    ):
        _denied()
    binding = OfficialAppBinding(
        id=new_id(),
        installation_id=installation.id,
        generation=installation.generation,
        release_id=release.id,
        verification_id=release.verification_id,
        artifact=release.artifact,
        origin=installation.origin,
        environment=installation.environment,
        logical_app_ids=sorted(logical_app_ids),
        approved_by_user_id=admin.user.id,
        approved_by_session_id=admin.session.id,
    )
    db.add(binding)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        _denied()
    record_audit_log(
        db,
        actor_user_id=admin.user.id,
        action="official_app.binding.approve",
        entity_kind="official_app_binding",
        entity_id=binding.id,
        summary="Official app identity delegation approved",
        payload={
            "installation_id": installation.id,
            "generation": installation.generation,
            "release_id": release.id,
            "artifact": release.artifact,
            "logical_app_ids": binding.logical_app_ids,
        },
    )
    return binding


def revoke_binding(db: Session, context: AuthContext, binding_id: str) -> None:
    _require_authority_transaction(db)
    _core_admin(db, context)
    binding = db.scalar(
        select(OfficialAppBinding)
        .where(OfficialAppBinding.id == binding_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    admin = _core_admin(db, context)
    if binding is None:
        _denied()
    if binding.revoked_at is not None:
        return
    binding.revoked_at = utcnow_naive()
    record_audit_log(
        db,
        actor_user_id=admin.user.id,
        action="official_app.binding.revoke",
        entity_kind="official_app_binding",
        entity_id=binding.id,
        summary="Official app identity delegation revoked",
    )


def resolve_official_auth_context(
    db: Session,
    token: str,
    *,
    logical_app_id: str,
    source_user_loader: SourceUserLoader | None = None,
) -> AuthContext:
    """Validate an app session then derive the unchanged source ACL principal.

    The logical app argument is trusted composition metadata, never request data.
    No last_seen, commit, audit insert, or other write occurs during this bridge.
    """
    with db.no_autoflush:
        _require_authority_transaction(db)
        app_session = db.get(AppSession, hash_token(token), populate_existing=True)
        if app_session is None:
            raise localized_http_exception(status_code=401, code="auth.session_invalid_or_expired")
        installation = db.get(
            AppInstallationRecord, app_session.installation_id, populate_existing=True
        )
        binding = db.scalar(
            select(OfficialAppBinding)
            .where(
                OfficialAppBinding.installation_id == app_session.installation_id,
                OfficialAppBinding.generation == app_session.generation,
                OfficialAppBinding.revoked_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        if (
            installation is None
            or binding is None
            or logical_app_id not in OFFICIAL_APP_IDS
            or logical_app_id not in binding.logical_app_ids
        ):
            _denied()
        identity = app_identity(
            db,
            token=token,
            installation_id=installation.id,
            audience=binding.origin,
            source_user_loader=source_user_loader,
        )
        release = trusted_release(db, installation, binding.release_id)
        if (
            installation.state != "ready"
            or not installation.runtime_ref
            or (installation.generation, installation.release_id, installation.environment)
            != (binding.generation, binding.release_id, binding.environment)
            or release is None
            or (release.artifact, release.verification_id)
            != (binding.artifact, binding.verification_id)
            or release.definition_snapshot.get("ownership") != "official"
            or not can_use_app(db, user_id=identity.user_id, app_id=logical_app_id)
        ):
            _denied()
        if source_user_loader is None:
            context = resolve_auth_context_from_session_id(db, app_session.source_session_id)
        else:
            user, source_session = source_user_loader(db, app_session.source_session_id)
            context = AuthContext(
                user=user,
                session=source_session,
                system_roles=frozenset(resolve_system_roles(db, user)),
            )
            # The narrow reader may observe a role change after earlier app
            # admission. Evaluate app policy again with the current actual role.
            if not can_use_app(db, user_id=user.id, app_id=logical_app_id):
                _denied()
            if context.system_roles != frozenset(resolve_system_roles(db, user)):
                _denied()
        if context.user.id != identity.user_id or context.impersonator_user_id is not None:
            _denied()
        return context
