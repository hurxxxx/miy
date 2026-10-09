"""Inactive service admission in a caller-owned Whiteboard Source transaction.

This does not authorize a user, save bytes, select a factory, or own transaction
cleanup. The original server identity and prepared role descriptor are mandatory.
"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.domains.official_apps.whiteboard_source_writer_roles import (
    WhiteboardSourceWriterProfile,
    _profile,
    _restricted_role,
    whiteboard_source_writer_contract,
)
from miy_api.domains.official_apps.writer import WriterControlError


class WhiteboardSourceWriterRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_source_writer_refused")


def admit_whiteboard_source_writer(db: Session, writer: WhiteboardSourceWriterProfile) -> None:
    """Hold service ownership/principal SHARE locks through caller COMMIT/rollback.

    Catalog validation is admission-time validation, not an atomic lock against
    superuser DDL or a current actor/resource ACL fence. No GUC supplies identity.
    The caller retains its decreasing SQL budget and complete cleanup ownership.
    """
    if type(writer) is not WhiteboardSourceWriterProfile:
        raise WhiteboardSourceWriterRefused("prepared_profile_required")
    if not isinstance(db, Session) or db.new or db.dirty or db.deleted:
        raise WhiteboardSourceWriterRefused("clean_caller_transaction_required")
    try:
        with db.no_autoflush:
            connection = db.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.connection.driver_connection.autocommit is True
                or db.scalar(text("SHOW transaction_isolation")) != "read committed"
            ):
                raise WhiteboardSourceWriterRefused("read_committed_required")
            db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
            current = db.execute(text("SELECT current_user=session_user,session_user::text")).one()
            if not current[0] or current[1] != writer.role_name:
                raise WhiteboardSourceWriterRefused("original_direct_login_required")
            if _restricted_role(db, writer.role_name, login=True) != writer.role_oid:
                raise WhiteboardSourceWriterRefused("original_direct_login_required")
            whiteboard_source_writer_contract(
                db,
                capability_owner_oid=writer.capability_owner_oid,
                producer_owner_oid=writer.producer_owner_oid,
                source_guard_owner_oid=writer.source_guard_owner_oid,
            )
            if not all(_profile(db, writer.role_name)):
                raise WhiteboardSourceWriterRefused("complete_profile_required")
            if not db.scalar(
                text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                {"name": writer.role_name},
            ):
                raise WhiteboardSourceWriterRefused("complete_profile_required")
            db.execute(
                text("SELECT public.miy_whiteboard_lock_source_writer(:generation,:artifact)"),
                {"generation": writer.identity.generation, "artifact": writer.identity.artifact},
            )
    except WriterControlError:
        raise WhiteboardSourceWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        # Caller owns rollback/close even after a server-side denial or timeout.
        raise WhiteboardSourceWriterRefused("service_admission_unavailable") from None
