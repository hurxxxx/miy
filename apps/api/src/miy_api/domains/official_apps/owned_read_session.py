"""Owned read Session guards; no factories, pools, roles or runtime activation."""

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.domains.official_apps.writer_roles import _role


class OwnedReadSessionRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("owned_read_session_refused")


# Existing safe policy query subset; not a role or privilege ceiling.
CORE_POLICY_READ_COLUMNS = {
    "users": (
        "id",
        "status",
        "login_blocked",
        "must_change_password",
        "primary_organization_unit_id",
    ),
    "user_system_roles": ("user_id", "role"),
    "company_app_controls": ("app_id", "enabled"),
    "app_access_policies": ("app_id", "audience"),
    "app_user_grants": ("app_id", "user_id"),
    "app_group_grants": ("app_id", "group_id"),
    "groups": ("id", "source", "active"),
    "group_members": ("group_id", "user_id"),
}


def require_fresh_owned_read_session(db: Session, *, models: tuple) -> None:
    if getattr(db.get_bind, "__func__", None) is not Session.get_bind:
        raise OwnedReadSessionRefused("standard_session_binding_required")
    try:
        engine = db.get_bind()
        if not isinstance(engine, Engine):
            raise OwnedReadSessionRefused("engine_binding_required")
        for model in models:
            if (
                db.get_bind(mapper=model) is not engine
                or db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise OwnedReadSessionRefused("single_engine_required")
    except SQLAlchemyError:
        raise OwnedReadSessionRefused("engine_binding_required") from None
    if (
        db.in_transaction()
        or db.in_nested_transaction()
        or db.new
        or db.dirty
        or db.deleted
        or db.identity_map
    ):
        raise OwnedReadSessionRefused("fresh_session_required")


def cleanup_owned_read_session(db: Session) -> None:
    for action in (db.rollback, db.close):
        try:
            action()
        except BaseException:
            try:
                db.invalidate()
            except BaseException:
                pass


def require_owned_read_transaction(db: Session) -> None:
    """Admit the existing owned read transaction; this is not a grant profile."""
    if db.get_bind().dialect.name != "postgresql":
        raise OwnedReadSessionRefused("postgresql_required")
    if db.connection().connection.driver_connection.autocommit is True:
        raise OwnedReadSessionRefused("read_committed_required")
    if db.scalar(text("SHOW transaction_isolation")) != "read committed":
        raise OwnedReadSessionRefused("read_committed_required")
    db.execute(text("SET TRANSACTION READ ONLY"))
    db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SET LOCAL statement_timeout = '15s'"))
    current, session = db.execute(text("SELECT CURRENT_USER, SESSION_USER")).one()
    if current != session:
        raise OwnedReadSessionRefused("direct_login_required")
    # Catalog-only reuse, preserving the accepted ACL reader's limitation.
    _role(db, session, login=True)
