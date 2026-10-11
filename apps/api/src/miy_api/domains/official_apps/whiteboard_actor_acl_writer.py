"""Inactive current full-edit ACL locks in the actual caller transaction.

The original public capture/descriptor are reused unchanged. This fixed adapter
adds only the resource model binding closure and the distinct ACL capability;
it performs no business DML, factory selection, COMMIT or Session cleanup.
"""

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.official_apps.authority_reader import _MODELS as _AUTH_MODELS
from miy_api.domains.official_apps.whiteboard_actor_writer import (
    CapturedWhiteboardWriteExecution,
    _bounded,
    capture_whiteboard_write_execution,
)
from miy_api.domains.official_apps.whiteboard_actor_acl_writer_roles import (
    WhiteboardActorACLProfile,
    _profile,
    whiteboard_actor_acl_contract,
)
from miy_api.domains.official_apps.whiteboard_source_writer_roles import _restricted_role
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import RuntimePrincipal
from miy_api.domains.pms.models import TaskList
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember
from miy_api.domains.whiteboard.models import (
    Whiteboard,
    WhiteboardGroupShare,
    WhiteboardTarget,
    WhiteboardUserShare,
)

__all__ = (
    "CapturedWhiteboardWriteExecution",
    "capture_whiteboard_write_execution",
    "WhiteboardActorACLWriterRefused",
    "lock_whiteboard_actor_edit_write",
)

_RESOURCE_MODELS = (
    Whiteboard,
    WhiteboardUserShare,
    WhiteboardGroupShare,
    WhiteboardTarget,
    Team,
    TeamMember,
    SpaceGroupBinding,
    TaskList,
    Meeting,
    MeetingAttendee,
)


class WhiteboardActorACLWriterRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_actor_acl_writer_refused")


def lock_whiteboard_actor_edit_write(
    source_db: Session,
    *,
    writer: WhiteboardActorACLProfile,
    execution: CapturedWhiteboardWriteExecution,
    whiteboard_id: str,
) -> None:
    """Hold current positive service/actor/app/edit witnesses through caller end.

    Same database metadata and SQL capability are required. Caller owns its
    decreasing SQL deadline, COMMIT/rollback and cleanup. Expiry is checked after
    waits at decision time; wall-clock expiry at physical COMMIT is not promised.
    Deadlock/timeout invalidates this decision; rollback is mandatory, with no
    reusable decision, automatic retry, savepoint proof or alternate witness.
    """
    if (
        type(writer) is not WhiteboardActorACLProfile
        or type(execution) is not CapturedWhiteboardWriteExecution
        or not _bounded(whiteboard_id, 36)
    ):
        raise WhiteboardActorACLWriterRefused("original_execution_required")
    if not isinstance(source_db, Session) or source_db.new or source_db.dirty or source_db.deleted:
        raise WhiteboardActorACLWriterRefused("clean_caller_transaction_required")
    if getattr(source_db.get_bind, "__func__", None) is not Session.get_bind:
        raise WhiteboardActorACLWriterRefused("standard_caller_binding_required")
    try:
        engine = source_db.get_bind()
        if not isinstance(engine, Engine):
            raise WhiteboardActorACLWriterRefused("engine_caller_binding_required")
        for model in (*_AUTH_MODELS, *_RESOURCE_MODELS, RuntimePrincipal):
            if (
                source_db.get_bind(mapper=model) is not engine
                or source_db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise WhiteboardActorACLWriterRefused("single_caller_engine_required")
    except SQLAlchemyError:
        raise WhiteboardActorACLWriterRefused("engine_caller_binding_required") from None
    platform_origins = get_settings().independent_app_platform_origins
    if not platform_origins or execution.origin in platform_origins:
        raise WhiteboardActorACLWriterRefused("current_platform_origin_required")
    try:
        with source_db.no_autoflush:
            connection = source_db.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.connection.driver_connection.autocommit is True
                or source_db.scalar(text("SHOW transaction_isolation")) != "read committed"
            ):
                raise WhiteboardActorACLWriterRefused("read_committed_required")
            source_db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
            current = source_db.execute(
                text("SELECT current_user=session_user,session_user::text")
            ).one()
            if (
                not current[0]
                or current[1] != writer.role_name
                or _restricted_role(source_db, writer.role_name, login=True) != writer.role_oid
            ):
                raise WhiteboardActorACLWriterRefused("original_direct_login_required")
            locator = source_db.execute(
                text(
                    "SELECT current_database()::text,(SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()),inet_server_addr()::text,inet_server_port()"
                )
            ).one()
            if tuple(locator) != (
                execution.database_name,
                execution.database_oid,
                execution.server_address,
                execution.server_port,
            ):
                raise WhiteboardActorACLWriterRefused("original_database_required")
            whiteboard_actor_acl_contract(
                source_db,
                capability_owner_oid=writer.capability_owner_oid,
                service_capability_owner_oid=writer.service_capability_owner_oid,
                producer_owner_oid=writer.producer_owner_oid,
                source_guard_owner_oid=writer.source_guard_owner_oid,
            )
            if not all(_profile(source_db, writer.role_name)) or not source_db.scalar(
                text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"),
                {"name": writer.role_name},
            ):
                raise WhiteboardActorACLWriterRefused("complete_profile_required")
            source_db.execute(
                text(
                    "SELECT public.miy_whiteboard_lock_edit_actor(:generation,:artifact,:digest,:user,:session,:installation,:installation_generation,:binding,:release,:verification,:execution_artifact,:origin,:environment,:board)"
                ),
                {
                    "generation": writer.identity.generation,
                    "artifact": writer.identity.artifact,
                    "digest": execution.delegated_token_digest,
                    "user": execution.actor_user_id,
                    "session": execution.source_session_id,
                    "installation": execution.installation_id,
                    "installation_generation": execution.installation_generation,
                    "binding": execution.binding_id,
                    "release": execution.release_id,
                    "verification": execution.verification_id,
                    "execution_artifact": execution.execution_artifact,
                    "origin": execution.origin,
                    "environment": execution.environment,
                    "board": whiteboard_id,
                },
            )
    except WriterControlError:
        raise WhiteboardActorACLWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        raise WhiteboardActorACLWriterRefused("current_actor_admission_unavailable") from None
