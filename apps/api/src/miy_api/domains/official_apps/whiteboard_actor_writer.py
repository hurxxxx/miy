"""Inactive owner-only actor locks, with separate auth capture and caller SQL.

A detached execution selects current credential rows; it never grants authority.
This primitive has no Yjs, business DML, factory selection or transaction commit.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
import re

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps.models import (
    AppInstallationRecord,
    AppReleaseRecord,
    AppSession,
)
from miy_api.domains.official_apps.auth import resolve_official_auth_context
from miy_api.domains.official_apps.authority_reader import (
    OfficialAuthorityReaderRefused,
    _cleanup,
    _MODELS,
    _fresh,
    _profile as _auth_profile,
    load_official_source_user,
)
from miy_api.domains.official_apps.models import OfficialAppBinding
from miy_api.domains.official_apps.whiteboard_actor_writer_roles import (
    WhiteboardActorOwnerProfile,
    _profile,
    whiteboard_actor_owner_contract,
)
from miy_api.domains.official_apps.whiteboard_source_writer_roles import _restricted_role
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import RuntimePrincipal
from miy_api.domains.whiteboard.models import Whiteboard


class WhiteboardActorWriterRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_actor_writer_refused")


def _bounded(value: str, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    )


@dataclass(frozen=True, repr=False)
class CapturedWhiteboardWriteExecution:
    delegated_token_digest: str = field(repr=False)
    actor_user_id: str
    source_session_id: str
    installation_id: str
    installation_generation: int
    binding_id: str
    release_id: str
    verification_id: str
    execution_artifact: str
    origin: str
    environment: str
    database_name: str
    database_oid: int
    server_address: str | None
    server_port: int | None

    def __post_init__(self):
        if (
            not _bounded(self.database_name, 63)
            or type(self.database_oid) is not int
            or not 1 <= self.database_oid <= 4294967295
            or (self.server_address is not None and not _bounded(self.server_address, 100))
            or (
                self.server_port is not None
                and (type(self.server_port) is not int or not 1 <= self.server_port <= 65535)
            )
        ):
            raise WhiteboardActorWriterRefused("original_database_required")
        if not isinstance(self.delegated_token_digest, str) or not re.fullmatch(
            r"[a-f0-9]{64}", self.delegated_token_digest
        ):
            raise WhiteboardActorWriterRefused("original_execution_required")
        for value, limit in (
            (self.actor_user_id, 36),
            (self.source_session_id, 36),
            (self.installation_id, 36),
            (self.binding_id, 36),
            (self.release_id, 36),
            (self.verification_id, 100),
            (self.execution_artifact, 500),
            (self.origin, 300),
            (self.environment, 16),
        ):
            if not _bounded(value, limit):
                raise WhiteboardActorWriterRefused("original_execution_required")
        if (
            type(self.installation_generation) is not int
            or not 1 <= self.installation_generation <= 2147483647
        ):
            raise WhiteboardActorWriterRefused("original_execution_required")


def capture_whiteboard_write_execution(
    auth_factory: Callable[[], Session],
    *,
    token: str,
    original_user_id: str,
    original_source_session_id: str,
) -> CapturedWhiteboardWriteExecution:
    """Capture through the unchanged auth14/87 role, never a Source Session.

    Core current predicates are reused; the extra projection uses existing read
    columns. No credential/descriptor serialization or logging API is supplied.
    Accepted fresh Sessions are cleaned; rejected caller work is never adopted.
    """
    if (
        not callable(auth_factory)
        or not _bounded(token, 1024)
        or not _bounded(original_user_id, 36)
        or not _bounded(original_source_session_id, 36)
    ):
        raise WhiteboardActorWriterRefused("original_execution_required")
    try:
        db = auth_factory()
        if not isinstance(db, Session):
            raise WhiteboardActorWriterRefused("fresh_auth_session_required")
        _fresh(db)
    except (SQLAlchemyError, OfficialAuthorityReaderRefused):
        raise WhiteboardActorWriterRefused("fresh_auth_session_required") from None
    try:
        with db.no_autoflush:
            if (
                db.get_bind().dialect.name != "postgresql"
                or db.connection().connection.driver_connection.autocommit is True
                or db.scalar(text("SHOW transaction_isolation")) != "read committed"
            ):
                raise WhiteboardActorWriterRefused("read_committed_required")
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            _auth_profile(db)
            context = resolve_official_auth_context(
                db, token, logical_app_id="whiteboard", source_user_loader=load_official_source_user
            )
            if (context.user.id, context.session.id) != (
                original_user_id,
                original_source_session_id,
            ):
                raise WhiteboardActorWriterRefused("original_actor_required")
            digest = hash_token(token)
            row = db.execute(
                select(
                    AppSession.source_session_id,
                    AppInstallationRecord.id,
                    AppInstallationRecord.generation,
                    OfficialAppBinding.id,
                    AppReleaseRecord.id,
                    AppReleaseRecord.verification_id,
                    AppReleaseRecord.artifact,
                    AppInstallationRecord.origin,
                    AppInstallationRecord.environment,
                    AppSession.expires_at,
                )
                .join(AppInstallationRecord, AppInstallationRecord.id == AppSession.installation_id)
                .join(
                    OfficialAppBinding,
                    (OfficialAppBinding.installation_id == AppSession.installation_id)
                    & (OfficialAppBinding.generation == AppSession.generation),
                )
                .join(AppReleaseRecord, AppReleaseRecord.id == OfficialAppBinding.release_id)
                .where(
                    AppSession.token_hash == digest,
                    AppSession.revoked_at.is_(None),
                    OfficialAppBinding.revoked_at.is_(None),
                )
            ).one_or_none()
            if row is None or row[0] != original_source_session_id:
                raise WhiteboardActorWriterRefused("original_execution_required")
            locator = db.execute(
                text(
                    "SELECT current_database()::text,(SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()),inet_server_addr()::text,inet_server_port()"
                )
            ).one()
            execution = CapturedWhiteboardWriteExecution(
                digest, original_user_id, *row[:9], *locator
            )
            current = resolve_official_auth_context(
                db, token, logical_app_id="whiteboard", source_user_loader=load_official_source_user
            )
            if (current.user.id, current.session.id) != (
                original_user_id,
                original_source_session_id,
            ):
                raise WhiteboardActorWriterRefused("original_actor_required")
            source_expiry, delegated_expiry = current.session.expires_at, row[9]
    except (SQLAlchemyError, OfficialAuthorityReaderRefused):
        raise WhiteboardActorWriterRefused("authority_capture_unavailable") from None
    finally:
        _cleanup(db)
    if source_expiry <= utcnow_naive() or delegated_expiry <= utcnow_naive():
        raise WhiteboardActorWriterRefused("execution_expired")
    return execution


def lock_whiteboard_owner_actor_write(
    source_db: Session,
    *,
    writer: WhiteboardActorOwnerProfile,
    execution: CapturedWhiteboardWriteExecution,
    whiteboard_id: str,
) -> None:
    """Hold current positive service/actor/app/owner witnesses through caller end.

    Same database metadata and SQL capability are required. Caller owns its
    decreasing SQL deadline, COMMIT/rollback and cleanup. Expiry is checked after
    waits at decision time; wall-clock expiry at physical COMMIT is not promised.
    Deadlock/timeout invalidates this decision; rollback is mandatory, with no
    reusable decision, automatic retry, savepoint proof or alternate witness.
    """
    if (
        type(writer) is not WhiteboardActorOwnerProfile
        or type(execution) is not CapturedWhiteboardWriteExecution
        or not _bounded(whiteboard_id, 36)
    ):
        raise WhiteboardActorWriterRefused("original_execution_required")
    if not isinstance(source_db, Session) or source_db.new or source_db.dirty or source_db.deleted:
        raise WhiteboardActorWriterRefused("clean_caller_transaction_required")
    if getattr(source_db.get_bind, "__func__", None) is not Session.get_bind:
        raise WhiteboardActorWriterRefused("standard_caller_binding_required")
    try:
        engine = source_db.get_bind()
        if not isinstance(engine, Engine):
            raise WhiteboardActorWriterRefused("engine_caller_binding_required")
        for model in (*_MODELS, Whiteboard, RuntimePrincipal):
            if (
                source_db.get_bind(mapper=model) is not engine
                or source_db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise WhiteboardActorWriterRefused("single_caller_engine_required")
    except SQLAlchemyError:
        raise WhiteboardActorWriterRefused("engine_caller_binding_required") from None
    platform_origins = get_settings().independent_app_platform_origins
    if not platform_origins or execution.origin in platform_origins:
        raise WhiteboardActorWriterRefused("current_platform_origin_required")
    try:
        with source_db.no_autoflush:
            connection = source_db.connection()
            if (
                connection.dialect.name != "postgresql"
                or connection.connection.driver_connection.autocommit is True
                or source_db.scalar(text("SHOW transaction_isolation")) != "read committed"
            ):
                raise WhiteboardActorWriterRefused("read_committed_required")
            source_db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
            current = source_db.execute(
                text("SELECT current_user=session_user,session_user::text")
            ).one()
            if (
                not current[0]
                or current[1] != writer.role_name
                or _restricted_role(source_db, writer.role_name, login=True) != writer.role_oid
            ):
                raise WhiteboardActorWriterRefused("original_direct_login_required")
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
                raise WhiteboardActorWriterRefused("original_database_required")
            whiteboard_actor_owner_contract(
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
                raise WhiteboardActorWriterRefused("complete_profile_required")
            source_db.execute(
                text(
                    "SELECT public.miy_whiteboard_lock_owner_actor(:generation,:artifact,:digest,:user,:session,:installation,:installation_generation,:binding,:release,:verification,:execution_artifact,:origin,:environment,:board)"
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
        raise WhiteboardActorWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        raise WhiteboardActorWriterRefused("current_actor_admission_unavailable") from None
