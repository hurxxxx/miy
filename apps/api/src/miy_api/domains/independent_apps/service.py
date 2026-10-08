"""Durable authority for app registration; manifests never grant runtime access."""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miy_api.core.app_contracts_generated import APP_CONTRACT_BY_ID
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.groups.models import Group
from miy_api.domains.groups.service import user_group_ids_query
from miy_api.domains.independent_apps.contracts import (
    AppDefinition,
    AppIdentityOut,
    AppSessionOut,
    DefinitionOut,
    ExchangeInput,
    InstallationInput,
    InstallationOut,
    InstallationSummary,
    LaunchInput,
    LaunchOut,
    RegisterDefinition,
    ReleaseCandidate,
    ReleaseOut,
)
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppLaunchCode,
    AppReleaseRecord,
    AppSession,
)
from miy_api.domains.independent_apps.verification import trusted_release


def fail(code: str, status: int = 403):
    raise localized_http_exception(status_code=status, code=f"independent_apps.{code}")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("conflict", 409)


def _audit(db: Session, context: AuthContext, action: str, entity_id: str) -> None:
    record_audit_log(
        db,
        actor_user_id=context.user.id,
        action=f"independent_app.{action}",
        entity_kind="independent_app",
        entity_id=None,
        summary="Independent app configuration changed",
        payload={"app_id": entity_id},
    )


def owned_definition(db: Session, app_id: str, context: AuthContext) -> AppDefinitionRecord:
    record = db.get(AppDefinitionRecord, app_id)
    if record is None:
        fail("not_found", 404)
    if record.owner_user_id != context.user.id and "platform_admin" not in context.system_roles:
        fail("not_found", 404)
    if record.manifest["ownership"] == "official" and "platform_admin" not in context.system_roles:
        fail("forbidden")
    return record


def definition_out(record: AppDefinitionRecord) -> DefinitionOut:
    return DefinitionOut(
        definition=AppDefinition.model_validate(record.manifest),
        definition_digest=record.definition_digest,
        source_revision=record.source_revision,
        owner_user_id=record.owner_user_id,
        updated_at=record.updated_at,
    )


def stage_definition(
    db: Session, data: RegisterDefinition, context: AuthContext, *, create_only: bool = False
) -> AppDefinitionRecord:
    """Validate and flush a definition and its audit; the caller owns the transaction."""
    definition = data.definition
    if definition.app_id in APP_CONTRACT_BY_ID:
        fail("conflict", 409)
    if definition.ownership == "official" and "platform_admin" not in context.system_roles:
        fail("forbidden")
    record = db.get(AppDefinitionRecord, definition.app_id)
    if create_only and record is not None:
        fail("conflict", 409)
    now = utcnow_naive()
    if record is None:
        if data.expected_digest is not None or data.expected_source_revision is not None:
            fail("conflict", 409)
        record = AppDefinitionRecord(
            app_id=definition.app_id,
            owner_user_id=context.user.id,
            manifest=definition.model_dump(mode="json"),
            definition_digest=definition.content_digest(),
            source_revision=data.source_revision,
            updated_at=now,
        )
        db.add(record)
        # Company-wide admission is a separate, existing platform authority. A new
        # personal app may preview for its owner; production activation remains gated.
        db.add(
            CompanyAppControl(
                app_id=definition.app_id, enabled=True, updated_by_user_id=context.user.id
            )
        )
    else:
        owned_definition(db, definition.app_id, context)
        if (data.expected_digest, data.expected_source_revision) != (
            record.definition_digest,
            record.source_revision,
        ):
            fail("conflict", 409)
        # Compare-and-swap prevents concurrent editors silently replacing the definition.
        changed = db.execute(
            update(AppDefinitionRecord)
            .where(
                AppDefinitionRecord.app_id == definition.app_id,
                AppDefinitionRecord.definition_digest == data.expected_digest,
                AppDefinitionRecord.source_revision == data.expected_source_revision,
            )
            .values(
                manifest=definition.model_dump(mode="json"),
                definition_digest=definition.content_digest(),
                source_revision=data.source_revision,
                updated_at=now,
            )
        )
        if changed.rowcount != 1:
            fail("conflict", 409)
    _audit(db, context, "definition.register", definition.app_id)
    db.flush()
    return record


def register_definition(
    db: Session, data: RegisterDefinition, context: AuthContext
) -> DefinitionOut:
    try:
        record = stage_definition(db, data, context)
        _commit(db)
    except IntegrityError:
        db.rollback()
        fail("conflict", 409)
    db.refresh(record)
    return definition_out(record)


def register_release(
    db: Session,
    app_id: str,
    data: ReleaseCandidate,
    context: AuthContext,
) -> ReleaseOut:
    definition = owned_definition(db, app_id, context)
    if (data.definition_digest, data.source_revision) != (
        definition.definition_digest,
        definition.source_revision,
    ):
        fail("conflict", 409)
    existing = db.scalar(
        select(AppReleaseRecord).where(
            AppReleaseRecord.app_id == app_id,
            AppReleaseRecord.artifact == data.artifact,
        )
    )
    if existing is not None:
        if (existing.definition_digest, existing.source_revision) != (
            data.definition_digest,
            data.source_revision,
        ):
            fail("conflict", 409)
        return release_out(existing)
    release = AppReleaseRecord(
        id=str(uuid4()),
        app_id=app_id,
        definition_snapshot=definition.manifest,
        **data.model_dump(),
    )
    db.add(release)
    _audit(db, context, "release.candidate", app_id)
    _commit(db)
    return release_out(release)


def release_out(record: AppReleaseRecord) -> ReleaseOut:
    return ReleaseOut.model_validate(record, from_attributes=True)


def installation_out(record: AppInstallationRecord) -> InstallationOut:
    return InstallationOut.model_validate(record, from_attributes=True)


def stage_installation(
    db: Session,
    app_id: str,
    data: InstallationInput,
    context: AuthContext,
    *,
    platform_origin: str,
    installation_id: str | None = None,
) -> AppInstallationRecord:
    """Validate and flush an installation and audit without committing other work."""
    definition = owned_definition(db, app_id, context)
    platform_origins = get_settings().independent_app_platform_origins
    if not platform_origins:
        fail("origin_configuration_required", 503)
    is_admin = "platform_admin" in context.system_roles
    if data.origin == platform_origin or data.origin in platform_origins:
        fail("invalid_origin", 422)
    if not is_admin and (
        data.environment != "development"
        or data.audience != "selected"
        or set(data.user_ids) != {context.user.id}
        or data.group_ids
    ):
        fail("forbidden")
    if not set(data.granted_permissions).issubset(definition.manifest["requested_permissions"]):
        fail("forbidden")
    if set(data.user_ids) != set(db.scalars(select(User.id).where(User.id.in_(data.user_ids)))):
        fail("invalid_audience", 422)
    if set(data.group_ids) != set(db.scalars(select(Group.id).where(Group.id.in_(data.group_ids)))):
        fail("invalid_audience", 422)
    # Production is admitted only after the trusted release executor has applied and checked
    # an artifact. Client-submitted manifests and success strings are never that evidence.
    if data.environment == "production" and data.enabled:
        fail("verification_required", 409)
    if installation_id:
        installation = db.scalar(
            select(AppInstallationRecord)
            .where(
                AppInstallationRecord.id == installation_id,
                AppInstallationRecord.app_id == app_id,
            )
            .with_for_update()
        )
        if installation is None:
            fail("not_found", 404)
        if installation.environment != data.environment or installation.origin != data.origin:
            fail("conflict", 409)
        installation.generation += 1  # Immediately invalidates old launch codes and sessions.
        for key, value in data.model_dump().items():
            setattr(installation, key, value)
    else:
        installation = AppInstallationRecord(id=str(uuid4()), app_id=app_id, **data.model_dump())
        db.add(installation)
    installation.state = "configured" if data.enabled else "disabled"
    _audit(db, context, "installation.configure", app_id)
    db.flush()
    return installation


def configure_installation(
    db: Session,
    app_id: str,
    data: InstallationInput,
    context: AuthContext,
    *,
    platform_origin: str,
    installation_id: str | None = None,
) -> InstallationOut:
    try:
        installation = stage_installation(
            db,
            app_id,
            data,
            context,
            platform_origin=platform_origin,
            installation_id=installation_id,
        )
        _commit(db)
    except IntegrityError:
        db.rollback()
        fail("conflict", 409)
    return installation_out(installation)


def admitted(
    db: Session,
    installation: AppInstallationRecord,
    user: User,
    *,
    verify_current_release: bool = True,
) -> bool:
    platform_origins = get_settings().independent_app_platform_origins
    company = db.get(CompanyAppControl, installation.app_id, populate_existing=True)
    if (
        not platform_origins
        or installation.origin in platform_origins
        or company is None
        or not company.enabled
        or user.status != "active"
        or user.login_blocked
        or user.must_change_password
        or not installation.enabled
        or installation.state == "disabled"
    ):
        return False
    if installation.environment == "production" and (
        installation.state != "ready" or not installation.release_id
    ):
        return False
    if (
        verify_current_release
        and installation.release_id
        and trusted_release(db, installation, installation.release_id) is None
    ):
        return False
    if installation.audience == "all" or user.id in installation.user_ids:
        return True
    if not installation.group_ids:
        return False
    return bool(set(db.scalars(user_group_ids_query(user.id))) & set(installation.group_ids))


def installation_summary(
    db: Session, installation: AppInstallationRecord, definition: AppDefinitionRecord, user: User
) -> InstallationSummary:
    # Source registration can advance independently of an installed release.
    # The installed image owns its UI route, including after code rollback.
    entrypoint = None
    if installation.release_id:
        release = trusted_release(db, installation, installation.release_id)
        if release is not None:
            entrypoint = release.definition_snapshot["entrypoints"]["ui"]
    elif installation.environment == "development":
        # Existing owner-managed, unbuilt development previews remain supported.
        entrypoint = definition.manifest["entrypoints"]["ui"]
    return InstallationSummary(
        id=installation.id,
        app_id=installation.app_id,
        environment=installation.environment,
        origin=installation.origin,
        enabled=installation.enabled,
        release_id=installation.release_id,
        state=installation.state,
        generation=installation.generation,
        granted_permissions=installation.granted_permissions,
        launchable=entrypoint is not None and admitted(db, installation, user),
        ui_entrypoint=entrypoint,
    )


def set_company_enabled(db: Session, app_id: str, enabled: bool, context: AuthContext) -> bool:
    if "platform_admin" not in context.system_roles:
        fail("forbidden")
    if db.get(AppDefinitionRecord, app_id) is None:
        fail("not_found", 404)
    company = db.get(CompanyAppControl, app_id)
    if company is None:
        fail("not_found", 404)
    company.enabled = enabled
    company.updated_by_user_id = context.user.id
    _audit(db, context, "company.configure", app_id)
    _commit(db)
    return company.enabled


def _source_user(db: Session, source_session_id: str) -> tuple[User, AuthSession]:
    source = db.get(AuthSession, source_session_id, populate_existing=True)
    if (
        source is None
        or source.revoked_at is not None
        or source.expires_at <= utcnow_naive()
        or source.impersonator_user_id is not None
    ):
        fail("session_invalid", 401)
    user = db.get(User, source.user_id, populate_existing=True)
    if user is None or user.status != "active" or user.login_blocked or user.must_change_password:
        fail("session_invalid", 401)
    return user, source


def issue_launch(db: Session, data: LaunchInput, context: AuthContext) -> LaunchOut:
    if not get_settings().independent_app_platform_origins:
        fail("origin_configuration_required", 503)
    installation = db.get(AppInstallationRecord, data.installation_id)
    if installation is None or not admitted(db, installation, context.user):
        fail("not_found", 404)
    _, source = _source_user(db, context.session.id)
    code = secrets.token_urlsafe(32)
    expiry = min(utcnow_naive() + timedelta(seconds=60), source.expires_at)
    db.add(
        AppLaunchCode(
            code_hash=hash_token(code),
            installation_id=installation.id,
            source_session_id=source.id,
            generation=installation.generation,
            code_challenge=data.code_challenge,
            expires_at=expiry,
        )
    )
    _commit(db)
    return LaunchOut(code=code, expires_at=expiry, app_origin=installation.origin)


def exchange_launch(db: Session, data: ExchangeInput, *, origin: str | None) -> AppSessionOut:
    # The opaque portal bearer is never present in this public exchange request.
    code = db.get(AppLaunchCode, hash_token(data.code))
    now = utcnow_naive()
    installation = db.get(AppInstallationRecord, data.installation_id)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(data.code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    if (
        code is None
        or installation is None
        or code.installation_id != installation.id
        or code.expires_at <= now
        or code.consumed_at is not None
        or code.generation != installation.generation
        or origin != installation.origin
        or not secrets.compare_digest(code.code_challenge, challenge)
    ):
        fail("session_invalid", 401)
    user, source = _source_user(db, code.source_session_id)
    if not admitted(db, installation, user):
        fail("session_invalid", 401)
    consumed = db.execute(
        update(AppLaunchCode)
        .where(
            AppLaunchCode.code_hash == code.code_hash,
            AppLaunchCode.consumed_at.is_(None),
            AppLaunchCode.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if consumed.rowcount != 1:
        fail("session_invalid", 401)
    token = secrets.token_urlsafe(32)
    expiry = min(now + timedelta(minutes=5), source.expires_at)
    app_session = AppSession(
        token_hash=hash_token(token),
        installation_id=installation.id,
        source_session_id=source.id,
        generation=installation.generation,
        permissions=list(installation.granted_permissions),
        expires_at=expiry,
    )
    db.add(app_session)
    _commit(db)
    return AppSessionOut(
        token=token,
        expires_at=expiry,
        installation_id=installation.id,
        app_id=installation.app_id,
        environment=installation.environment,
        audience=installation.origin,
        permissions=app_session.permissions,
    )


@dataclass(frozen=True)
class VerifiedAppSession:
    session: AppSession
    installation: AppInstallationRecord
    user: User
    source_session: AuthSession
    permissions: list[str]


SourceUserLoader = Callable[[Session, str], tuple[User, AuthSession]]


def verified_app_session(
    db: Session,
    *,
    token_hash: str,
    installation_id: str,
    audience: str,
    source_user_loader: SourceUserLoader | None = None,
) -> VerifiedAppSession:
    """Internal lookup: hash a bearer or verify a purpose-bound proof first.

    The hash is a lookup selector, never an accepted external bearer. Each call
    refreshes current session/installation/source authority, including after I/O.
    """
    session = db.get(AppSession, token_hash, populate_existing=True)
    installation = db.get(AppInstallationRecord, installation_id, populate_existing=True)
    if (
        session is None
        or installation is None
        or session.installation_id != installation_id
        or installation.origin != audience
        or session.generation != installation.generation
        or session.revoked_at is not None
        or session.expires_at <= utcnow_naive()
    ):
        fail("session_invalid", 401)
    # Only trusted server composition selects this reader; no request field or
    # manifest can supply it. A failed reader never falls back to a broader one.
    loader = _source_user if source_user_loader is None else source_user_loader
    user, source = loader(db, session.source_session_id)
    if not admitted(db, installation, user):
        fail("session_invalid", 401)
    permissions = sorted(set(session.permissions) & set(installation.granted_permissions))
    return VerifiedAppSession(session, installation, user, source, permissions)


def app_identity(
    db: Session,
    *,
    token: str,
    installation_id: str,
    audience: str,
    source_user_loader: SourceUserLoader | None = None,
) -> AppIdentityOut:
    current = verified_app_session(
        db,
        token_hash=hash_token(token),
        installation_id=installation_id,
        audience=audience,
        source_user_loader=source_user_loader,
    )
    session, installation, user, permissions = (
        current.session,
        current.installation,
        current.user,
        current.permissions,
    )
    if "identity:read" not in permissions:
        fail("forbidden")
    return AppIdentityOut(
        user_id=user.id,
        display_name=user.display_name or user.full_name,
        app_id=installation.app_id,
        installation_id=installation_id,
        environment=installation.environment,
        audience=audience,
        permissions=permissions,
        expires_at=session.expires_at,
    )


def management_projection(db: Session) -> list[dict]:
    """Company-level metadata only; caller enforces the app-catalog:read service scope."""
    definitions = db.scalars(select(AppDefinitionRecord).order_by(AppDefinitionRecord.app_id)).all()
    installations = db.scalars(
        select(AppInstallationRecord).where(
            AppInstallationRecord.environment == "production",
        )
    ).all()
    by_app = {installation.app_id: installation for installation in installations}
    releases = {
        row.id: row
        for row in db.scalars(
            select(AppReleaseRecord).where(
                AppReleaseRecord.id.in_(
                    [item.release_id for item in installations if item.release_id]
                ),
            )
        )
    }
    result = []
    company_enabled = dict(
        db.execute(select(CompanyAppControl.app_id, CompanyAppControl.enabled)).all()
    )
    for definition in definitions:
        installation = by_app.get(definition.app_id)
        release = releases.get(installation.release_id) if installation else None
        result.append(
            {
                "app_id": definition.app_id,
                "title": definition.manifest["display"]["name"],
                "enabled": bool(
                    company_enabled.get(definition.app_id, False)
                    and installation
                    and installation.enabled
                    and installation.state == "ready"
                ),
                "release_unit": f"independent-app:{definition.app_id}",
                "installed_revision": release.source_revision if release else None,
                "registered_source_revision": definition.source_revision,
                "runtime_ai": False,
                "title_translations": definition.manifest["display"]["translations"],
                "icon_key": definition.manifest["display"]["icon"],
                "source_repository": definition.manifest["source"]["repository"],
                "source_directory": definition.manifest["source"]["directory"],
                "definition_digest": definition.definition_digest,
            }
        )
    return result
