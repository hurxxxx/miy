"""Inactive owned read-only authority lookup, separate from business Sessions."""

from collections.abc import Callable

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, load_only, raiseload

from miy_api.core.app_contracts_generated import OFFICIAL_APP_IDS
from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import (
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.auth.security import hash_token
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import (
    AppInstallationRecord,
    AppReleaseRecord,
    AppSession,
)
from miy_api.domains.independent_apps.service import fail
from miy_api.domains.official_apps.auth import resolve_official_auth_context
from miy_api.domains.official_apps.models import OfficialAppBinding
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import _role, _sequence_privileges

USER_COLUMNS = (
    "id",
    "status",
    "login_blocked",
    "must_change_password",
    "primary_organization_unit_id",
    "display_name",
    "full_name",
    "email",
    "locale",
    "time_zone",
)
SESSION_COLUMNS = ("id", "user_id", "expires_at", "revoked_at", "impersonator_user_id")
# Exact columns of the reused current metadata readers, not a guessed projection.
AUTHORITY_READ_COLUMNS = {
    "users": USER_COLUMNS,
    "auth_sessions": SESSION_COLUMNS,
    "user_system_roles": ("user_id", "role"),
    "company_app_controls": ("app_id", "enabled", "updated_by_user_id", "created_at", "updated_at"),
    "app_access_policies": ("app_id", "audience"),
    "app_user_grants": ("app_id", "user_id"),
    "app_group_grants": ("app_id", "group_id"),
    "groups": ("id", "source", "active"),
    "group_members": ("group_id", "user_id"),
    "independent_app_sessions": (
        "token_hash",
        "installation_id",
        "source_session_id",
        "generation",
        "permissions",
        "expires_at",
        "revoked_at",
    ),
    "independent_app_installations": (
        "id",
        "app_id",
        "environment",
        "origin",
        "enabled",
        "audience",
        "user_ids",
        "group_ids",
        "granted_permissions",
        "release_id",
        "state",
        "generation",
        "runtime_ref",
    ),
    "independent_app_releases": (
        "id",
        "app_id",
        "definition_digest",
        "definition_snapshot",
        "source_revision",
        "artifact",
        "created_at",
        "verification_id",
        "verified_at",
    ),
    "independent_app_build_verifications": (
        "id",
        "build_job_id",
        "app_id",
        "source_revision",
        "definition_digest",
        "source_archive_sha256",
        "artifact_digest",
        "builder_profile_digest",
        "target_environment",
        "checks",
        "created_at",
        "revoked_at",
    ),
    "official_app_bindings": (
        "id",
        "installation_id",
        "generation",
        "release_id",
        "verification_id",
        "artifact",
        "origin",
        "environment",
        "logical_app_ids",
        "approved_by_user_id",
        "approved_by_session_id",
        "approved_at",
        "revoked_at",
    ),
}
_MODELS = (
    User,
    AuthSession,
    UserSystemRole,
    CompanyAppControl,
    AppAccessPolicy,
    AppUserGrant,
    AppGroupGrant,
    Group,
    GroupMember,
    AppSession,
    AppInstallationRecord,
    AppReleaseRecord,
    AppBuildVerification,
    OfficialAppBinding,
)


class OfficialAuthorityReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("official_authority_reader_refused")


def _fresh(db: Session) -> None:
    if getattr(db.get_bind, "__func__", None) is not Session.get_bind:
        raise OfficialAuthorityReaderRefused("standard_session_binding_required")
    try:
        engine = db.get_bind()
        if not isinstance(engine, Engine):
            raise OfficialAuthorityReaderRefused("engine_binding_required")
        for model in _MODELS:
            if (
                db.get_bind(mapper=model) is not engine
                or db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise OfficialAuthorityReaderRefused("single_engine_required")
    except SQLAlchemyError:
        raise OfficialAuthorityReaderRefused("engine_binding_required") from None
    if (
        db.in_transaction()
        or db.in_nested_transaction()
        or db.new
        or db.dirty
        or db.deleted
        or db.identity_map
    ):
        raise OfficialAuthorityReaderRefused("fresh_session_required")


def load_official_source_user(db: Session, source_session_id: str) -> tuple[User, AuthSession]:
    source = db.scalar(
        select(AuthSession)
        .options(
            load_only(*(getattr(AuthSession, name) for name in SESSION_COLUMNS), raiseload=True),
            raiseload("*"),
        )
        .where(AuthSession.id == source_session_id)
        .execution_options(populate_existing=True)
    )
    if (
        source is None
        or source.revoked_at is not None
        or source.expires_at <= utcnow_naive()
        or source.impersonator_user_id is not None
    ):
        fail("session_invalid", 401)
    user = db.scalar(
        select(User)
        .options(
            load_only(*(getattr(User, name) for name in USER_COLUMNS), raiseload=True),
            raiseload("*"),
        )
        .where(User.id == source.user_id)
        .execution_options(populate_existing=True)
    )
    if user is None or user.status != "active" or user.login_blocked or user.must_change_password:
        fail("session_invalid", 401)
    return user, source


def _profile(db: Session) -> None:
    principal = db.execute(
        text("""
        SELECT current_user=session_user AS direct, session_user AS name
    """)
    ).one()
    if not principal.direct:
        raise OfficialAuthorityReaderRefused("reader_principal_required")
    # Reuse the owned principal checks: LOGIN/NOINHERIT, no membership in
    # either direction, persistent ownership or privileged parameter grants.
    try:
        _role(db, principal.name, login=True)
        _sequence_privileges(db, principal.name)
    except WriterControlError:
        raise OfficialAuthorityReaderRefused("reader_principal_required") from None
    if db.scalar(
        text("""
        SELECT pg_catalog.has_database_privilege(current_user,current_database(),'CREATE') OR
          EXISTS(SELECT 1 FROM pg_catalog.pg_namespace n
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
              AND pg_catalog.has_schema_privilege(current_user,n.oid,'CREATE,USAGE WITH GRANT OPTION')) OR
          EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
              AND (p.proowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user)
                OR (p.prosecdef AND pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE'))
                OR pg_catalog.has_function_privilege(current_user,p.oid,'EXECUTE WITH GRANT OPTION'))) OR
          EXISTS(SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema' AND c.relkind='S'
              AND pg_catalog.has_sequence_privilege(current_user,c.oid,'SELECT,USAGE,UPDATE'))
        """)
    ):
        raise OfficialAuthorityReaderRefused("reader_privileges_required")
    rows = db.execute(
        text("""
        SELECT n.nspname, c.relname, a.attname,
          CASE WHEN a.attnum IS NULL THEN pg_catalog.has_table_privilege(current_user,c.oid,'SELECT')
            ELSE pg_catalog.has_column_privilege(current_user,c.oid,a.attnum,'SELECT') END AS reads,
          pg_catalog.has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR
          pg_catalog.has_column_privilege(current_user,c.oid,a.attnum,'INSERT,UPDATE,REFERENCES') AS writes,
          pg_catalog.has_table_privilege(current_user,c.oid,'SELECT WITH GRANT OPTION') OR
          pg_catalog.has_column_privilege(current_user,c.oid,a.attnum,'SELECT WITH GRANT OPTION') AS grants,
          c.relowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user) AS owns
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
          LEFT JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        WHERE n.nspname !~ '^pg_' AND n.nspname<>'information_schema'
          AND c.relkind IN ('r','p','v','m','f')
    """)
    )
    actual: dict[str, set[str]] = {}
    for row in rows:
        if row.writes or row.owns or row.grants or (row.reads and row.nspname != "public"):
            raise OfficialAuthorityReaderRefused("reader_privileges_required")
        if row.reads:
            actual.setdefault(row.relname, set()).add(row.attname)
    if actual != {name: set(columns) for name, columns in AUTHORITY_READ_COLUMNS.items()}:
        raise OfficialAuthorityReaderRefused("reader_privileges_required")


def _cleanup(db: Session) -> None:
    # No cleanup failure may mask the original denial or cancellation. This
    # factory-owned Session is never reused; failed cleanup invalidates its bind.
    for action in (db.rollback, db.close):
        try:
            action()
        except BaseException:
            try:
                db.invalidate()
            except BaseException:
                pass


def resolve_prepared_official_auth_context(
    create_session: Callable[[], Session], token: str, *, logical_app_id: str
) -> AuthContext:
    """Return detached safe authority; no default HTTP/service activation.

    The factory creates an owned fresh auth-only Session. It is never the
    business Source Session. No operational role or grant is prepared here.
    """
    if logical_app_id not in OFFICIAL_APP_IDS:
        raise localized_http_exception(status_code=403, code="auth.required")
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= 1024
        or any(ord(c) < 32 or ord(c) == 127 for c in token)
    ):
        raise localized_http_exception(status_code=401, code="auth.session_invalid_or_expired")
    db = create_session()
    _fresh(db)  # Rejected pre-existing caller work remains outside ownership.
    try:
        if db.get_bind().dialect.name != "postgresql":
            raise OfficialAuthorityReaderRefused("postgresql_required")
        if db.connection().connection.driver_connection.autocommit is True:
            raise OfficialAuthorityReaderRefused("read_committed_required")
        if db.scalar(text("SHOW transaction_isolation")) != "read committed":
            raise OfficialAuthorityReaderRefused("read_committed_required")
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '15s'"))
        _profile(db)
        context = resolve_official_auth_context(
            db, token, logical_app_id=logical_app_id, source_user_loader=load_official_source_user
        )
        delegated_expiry = db.scalar(
            select(AppSession.expires_at).where(
                AppSession.token_hash == hash_token(token), AppSession.revoked_at.is_(None)
            )
        )
        # Every returned scalar stays loaded after rollback/close; forbidden
        # credential columns and relationships remain raiseload/detached.
        db.expunge_all()
    except SQLAlchemyError:
        raise OfficialAuthorityReaderRefused("authority_read_failed") from None
    finally:
        _cleanup(db)
    now = utcnow_naive()
    if delegated_expiry is None or delegated_expiry <= now or context.session.expires_at <= now:
        raise localized_http_exception(status_code=401, code="auth.session_invalid_or_expired")
    return context
