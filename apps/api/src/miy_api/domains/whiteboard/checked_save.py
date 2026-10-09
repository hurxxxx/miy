"""Inactive caller-owned Core seal, Source stage and authoritative outcome resolve.

Core alone supplies the complete original contributor cohort. Source supplies only
an immutable attempt reference; SQL keeps all ACL, aggregate expiry, captured CAS
and receipt writes on this actual caller transaction. None of these calls commits,
cleans up a Session, selects a factory, or acknowledges a save. Caller must await
the same staged transaction's COMMIT success for ACK; an unknown COMMIT requires fresh original-attempt
Core resolution and its successful COMMIT before using the historical outcome.
"""

from dataclasses import dataclass, fields
import json
import re
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.official_apps.authority_reader import _MODELS as _AUTH_MODELS
from miy_api.domains.official_apps.whiteboard_actor_acl_writer import _RESOURCE_MODELS
from miy_api.domains.official_apps.whiteboard_actor_writer import (
    CapturedWhiteboardWriteExecution,
    _bounded,
)
from miy_api.domains.official_apps.whiteboard_checked_models import (
    WhiteboardCheckedAttempt,
    WhiteboardCheckedContributor,
)
from miy_api.domains.official_apps.whiteboard_checked_writer_roles import (
    WhiteboardCheckedProfile,
    _profile,
    whiteboard_checked_contract,
)
from miy_api.domains.official_apps.whiteboard_source_writer_roles import _restricted_role
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import RuntimePrincipal
from miy_api.domains.whiteboard.models import WhiteboardCollabDocument

MAX_CONTRIBUTORS = 128
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_REVISION = 9223372036854775807
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MODELS = (
    *_AUTH_MODELS,
    *_RESOURCE_MODELS,
    RuntimePrincipal,
    WhiteboardCollabDocument,
    WhiteboardCheckedAttempt,
    WhiteboardCheckedContributor,
)


class WhiteboardCheckedWriterRefused(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("whiteboard_checked_writer_refused")


def _uuid(value):
    if type(value) is not UUID or value.int == 0:
        raise WhiteboardCheckedWriterRefused("stable_attempt_identity_required")


@dataclass(frozen=True, repr=False)
class WhiteboardCheckedAttemptRef:
    attempt_id: UUID
    request_digest: str
    database_name: str
    database_oid: int
    server_address: str | None
    server_port: int | None

    def __post_init__(self):
        _uuid(self.attempt_id)
        if (
            not isinstance(self.request_digest, str)
            or _DIGEST.fullmatch(self.request_digest) is None
        ):
            raise WhiteboardCheckedWriterRefused("sealed_attempt_required")
        if (
            not _bounded(self.database_name, 63)
            or type(self.database_oid) is not int
            or not 1 <= self.database_oid <= 4294967295
        ):
            raise WhiteboardCheckedWriterRefused("original_database_required")
        if self.server_address is not None and not _bounded(self.server_address, 100):
            raise WhiteboardCheckedWriterRefused("original_database_required")
        if self.server_port is not None and (
            type(self.server_port) is not int or not 1 <= self.server_port <= 65535
        ):
            raise WhiteboardCheckedWriterRefused("original_database_required")


@dataclass(frozen=True, repr=False)
class WhiteboardCheckedStage:
    """Durable receipt staged in the caller transaction; it is not a saved ACK."""

    attempt: WhiteboardCheckedAttemptRef
    content_incarnation_id: UUID
    content_revision: int

    def __post_init__(self):
        if type(self.attempt) is not WhiteboardCheckedAttemptRef:
            raise WhiteboardCheckedWriterRefused("sealed_attempt_required")
        _uuid(self.content_incarnation_id)
        if type(self.content_revision) is not int or not 0 <= self.content_revision <= MAX_REVISION:
            raise WhiteboardCheckedWriterRefused("receipt_invalid")


@dataclass(frozen=True, repr=False)
class WhiteboardCheckedResolution:
    """Historical outcome, usable only after caller's resolution COMMIT returns."""

    attempt: WhiteboardCheckedAttemptRef
    state: str
    receipt: WhiteboardCheckedStage | None

    def __post_init__(self):
        if type(self.attempt) is not WhiteboardCheckedAttemptRef or self.state not in (
            "committed",
            "cancelled_not_committed",
        ):
            raise WhiteboardCheckedWriterRefused("receipt_invalid")
        if (self.state == "committed") != (type(self.receipt) is WhiteboardCheckedStage):
            raise WhiteboardCheckedWriterRefused("receipt_invalid")
        if self.receipt is not None and self.receipt.attempt != self.attempt:
            raise WhiteboardCheckedWriterRefused("receipt_invalid")


def _preflight(db, writer, kind):
    if type(writer) is not WhiteboardCheckedProfile or writer.kind != kind:
        raise WhiteboardCheckedWriterRefused("original_principal_required")
    if not isinstance(db, Session) or db.new or db.dirty or db.deleted:
        raise WhiteboardCheckedWriterRefused("clean_caller_transaction_required")
    if db.in_nested_transaction():
        raise WhiteboardCheckedWriterRefused("caller_outer_transaction_required")
    if getattr(db.get_bind, "__func__", None) is not Session.get_bind:
        raise WhiteboardCheckedWriterRefused("standard_caller_binding_required")
    try:
        engine = db.get_bind()
        if not isinstance(engine, Engine):
            raise WhiteboardCheckedWriterRefused("engine_caller_binding_required")
        for model in _MODELS:
            if (
                db.get_bind(mapper=model) is not engine
                or db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise WhiteboardCheckedWriterRefused("single_caller_engine_required")
    except SQLAlchemyError:
        raise WhiteboardCheckedWriterRefused("engine_caller_binding_required") from None


def _admit(db, writer):
    connection = db.connection()
    if (
        connection.dialect.name != "postgresql"
        or connection.connection.driver_connection.autocommit is True
        or db.scalar(text("SHOW transaction_isolation")) != "read committed"
    ):
        raise WhiteboardCheckedWriterRefused("read_committed_required")
    db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
    direct, name = db.execute(text("SELECT current_user=session_user,session_user::text")).one()
    if (
        not direct
        or name != writer.role_name
        or _restricted_role(db, name, login=True) != writer.role_oid
    ):
        raise WhiteboardCheckedWriterRefused("original_direct_login_required")
    whiteboard_checked_contract(
        db,
        **{
            field: getattr(writer, field)
            for field in (
                "source_owner_oid",
                "core_owner_oid",
                "acl_owner_oid",
                "service_capability_owner_oid",
                "producer_owner_oid",
                "source_guard_owner_oid",
                "trigger_owner_oid",
            )
        },
    )
    if not all(_profile(db, name, kind=writer.kind)) or not db.scalar(
        text("SELECT pg_catalog.has_schema_privilege(:name,'public','USAGE')"), {"name": name}
    ):
        raise WhiteboardCheckedWriterRefused("complete_profile_required")
    return tuple(
        db.execute(
            text(
                "SELECT current_database()::text,(SELECT oid::bigint FROM pg_catalog.pg_database WHERE datname=current_database()),inet_server_addr()::text,inet_server_port()"
            )
        ).one()
    )


def _locator(attempt):
    return attempt.database_name, attempt.database_oid, attempt.server_address, attempt.server_port


def _result(value, attempt, states):
    if type(value) is not dict or set(value) != {
        "attempt_id",
        "request_digest",
        "state",
        "content_incarnation_id",
        "content_revision",
    }:
        raise WhiteboardCheckedWriterRefused("receipt_invalid")
    if (
        value["attempt_id"] != str(attempt.attempt_id)
        or value["request_digest"] != attempt.request_digest
        or value["state"] not in states
    ):
        raise WhiteboardCheckedWriterRefused("receipt_invalid")
    if value["state"] == "committed":
        try:
            incarnation = UUID(value["content_incarnation_id"])
        except (TypeError, ValueError, AttributeError):
            raise WhiteboardCheckedWriterRefused("receipt_invalid") from None
        return WhiteboardCheckedStage(attempt, incarnation, value["content_revision"])
    if value["content_incarnation_id"] is not None or value["content_revision"] is not None:
        raise WhiteboardCheckedWriterRefused("receipt_invalid")
    return None


def seal_whiteboard_checked_attempt(
    db,
    *,
    writer,
    attempt_id,
    source_role_oid,
    source_role_name,
    whiteboard_id,
    collab_id,
    room_key,
    content_incarnation_id,
    base_revision,
    yjs_state,
    snapshot_scene,
    cohort_cutoff,
    contributors,
):
    """Trusted Core seals complete original cohort and payload; caller owns COMMIT.

    A frozen Python descriptor is not proof of complete provenance. Only the
    server-owned Core principal may supply this immutable attempt; C1 does not
    select a native apply boundary or prove its complete-cohort intake. Source
    cannot supply replacement credentials, payload, cohort or a last editor.
    Dispatch requires observed successful seal COMMIT; seal-COMMIT uncertainty
    must be observed through exact fresh Core replay before Source dispatch.
    """
    _preflight(db, writer, "core")
    _uuid(attempt_id)
    _uuid(content_incarnation_id)
    if (
        type(source_role_oid) is not int
        or not 1 <= source_role_oid <= 4294967295
        or not _bounded(source_role_name, 63)
        or not re.fullmatch("[a-z][a-z0-9_]{0,62}", source_role_name)
    ):
        raise WhiteboardCheckedWriterRefused("original_principal_required")
    if (
        not all(
            _bounded(value, bound)
            for value, bound in ((whiteboard_id, 36), (collab_id, 36), (room_key, 128))
        )
        or type(base_revision) is not int
        or not 0 <= base_revision <= MAX_REVISION
        or type(cohort_cutoff) is not int
        or not 1 <= cohort_cutoff <= MAX_REVISION
    ):
        raise WhiteboardCheckedWriterRefused("captured_cas_required")
    if (
        type(contributors) is not tuple
        or not 1 <= len(contributors) <= MAX_CONTRIBUTORS
        or any(type(c) is not CapturedWhiteboardWriteExecution for c in contributors)
    ):
        raise WhiteboardCheckedWriterRefused("complete_original_cohort_required")
    if (
        yjs_state is not None
        and type(yjs_state) is not bytes
        or snapshot_scene is not None
        and type(snapshot_scene) is not dict
    ):
        raise WhiteboardCheckedWriterRefused("bounded_payload_required")
    try:
        snapshot = (
            None
            if snapshot_scene is None
            else json.dumps(
                snapshot_scene, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
        )
        cohort = json.dumps(
            [
                {
                    field.name: getattr(c, field.name)
                    for field in fields(CapturedWhiteboardWriteExecution)
                }
                for c in contributors
            ],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        payload_bytes = (len(yjs_state) if yjs_state is not None else 0) + (
            len(snapshot.encode("utf-8")) if snapshot is not None else 0
        )
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise WhiteboardCheckedWriterRefused("bounded_payload_required") from None
    if payload_bytes > MAX_PAYLOAD_BYTES:
        raise WhiteboardCheckedWriterRefused("bounded_payload_required")
    platform_origins = get_settings().independent_app_platform_origins
    if not platform_origins or any(c.origin in platform_origins for c in contributors):
        raise WhiteboardCheckedWriterRefused("current_platform_origin_required")
    try:
        with db.no_autoflush:
            locator = _admit(db, writer)
            if any(
                (c.database_name, c.database_oid, c.server_address, c.server_port) != locator
                for c in contributors
            ):
                raise WhiteboardCheckedWriterRefused("original_database_required")
            value = db.scalar(
                text(
                    "SELECT public.miy_whiteboard_seal_checked(CAST(:attempt AS uuid),:source_oid,:source_name,:generation,:artifact,:board,:collab,:room,CAST(:incarnation AS uuid),:revision,:yjs,CAST(:snapshot AS jsonb),:cutoff,CAST(:contributors AS jsonb))"
                ),
                {
                    "attempt": str(attempt_id),
                    "source_oid": source_role_oid,
                    "source_name": source_role_name,
                    "generation": writer.identity.generation,
                    "artifact": writer.identity.artifact,
                    "board": whiteboard_id,
                    "collab": collab_id,
                    "room": room_key,
                    "incarnation": str(content_incarnation_id),
                    "revision": base_revision,
                    "yjs": yjs_state,
                    "snapshot": snapshot,
                    "cutoff": cohort_cutoff,
                    "contributors": cohort,
                },
            )
            if type(value) is not dict:
                raise WhiteboardCheckedWriterRefused("receipt_invalid")
            attempt = WhiteboardCheckedAttemptRef(attempt_id, value.get("request_digest"), *locator)
            _result(value, attempt, {"sealed"})
            return attempt
    except WriterControlError:
        raise WhiteboardCheckedWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        raise WhiteboardCheckedWriterRefused("current_seal_unavailable") from None


def stage_whiteboard_checked_save(db, *, writer, attempt):
    """Stage CAS+receipt in this transaction. Caller COMMIT return alone allows ACK.

    The caller must retain this exact outer transaction until its COMMIT returns;
    any rollback invalidates the stage. The caller owns its decreasing SQL deadline, mandatory rollback on failure,
    deadlock/timeout cancellation, and cleanup. There is no automatic retry,
    alternate cohort, rebase, COMMIT, rollback or standalone authority decision.
    """
    _preflight(db, writer, "source")
    if type(attempt) is not WhiteboardCheckedAttemptRef:
        raise WhiteboardCheckedWriterRefused("sealed_attempt_required")
    try:
        with db.no_autoflush:
            if _admit(db, writer) != _locator(attempt):
                raise WhiteboardCheckedWriterRefused("original_database_required")
            value = db.scalar(
                text("SELECT public.miy_whiteboard_save_checked(CAST(:attempt AS uuid),:digest)"),
                {"attempt": str(attempt.attempt_id), "digest": attempt.request_digest},
            )
            return _result(value, attempt, {"committed"})
    except WriterControlError:
        raise WhiteboardCheckedWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        raise WhiteboardCheckedWriterRefused("current_save_unavailable") from None


def resolve_whiteboard_checked_attempt(db, *, writer, attempt):
    """Lock original attempt and read committed receipt or cancel pending intent.

    Resolution waits behind any actual save COMMIT/rollback. Cancellation is
    authoritative only after this caller's COMMIT returns. It prevents a queued
    late Source saver; unlocked absence, same bytes, timeout or replica reads are
    not outcome proof. This is original-attempt recovery, never automatic replay.
    """
    _preflight(db, writer, "core")
    if type(attempt) is not WhiteboardCheckedAttemptRef:
        raise WhiteboardCheckedWriterRefused("sealed_attempt_required")
    try:
        with db.no_autoflush:
            if _admit(db, writer) != _locator(attempt):
                raise WhiteboardCheckedWriterRefused("original_database_required")
            value = db.scalar(
                text(
                    "SELECT public.miy_whiteboard_resolve_checked(CAST(:attempt AS uuid),:digest)"
                ),
                {"attempt": str(attempt.attempt_id), "digest": attempt.request_digest},
            )
            receipt = _result(value, attempt, {"committed", "cancelled_not_committed"})
            return WhiteboardCheckedResolution(attempt, value["state"], receipt)
    except WriterControlError:
        raise WhiteboardCheckedWriterRefused("prepared_contract_unavailable") from None
    except SQLAlchemyError:
        raise WhiteboardCheckedWriterRefused("current_resolve_unavailable") from None
