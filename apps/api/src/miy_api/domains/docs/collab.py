from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from fastapi import HTTPException
import y_py as Y
from sqlalchemy import delete, event, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, joinedload, selectinload
from ypy_websocket.yroom import YRoom
from ypy_websocket.yutils import YMessageType

from miy_api.core.db import (
    get_session_factory,
    is_official_writer_guard_error,
    official_writer_unavailable,
)
from miy_api.core.i18n import LocalizedApiMessage, localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import User
from miy_api.domains.auth.security import new_id
from miy_api.domains.collaboration.yjs_runtime import (
    COLLAB_CLOSE_CODE_RELAY_UNAVAILABLE,
    CollabBus,
    CollabConnectionLimitExceeded,
    CollabRoomRuntime,
    RedisCollabBus,
    hash_bytes,
    native_persistence_lease,
    release_yroom_thread_bound_state,
)
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state, yjs_state_to_blocks
from miy_api.domains.docs.models import (
    DocsCollabDocument,
    NativeDoc,
    NativeDocPage,
    NativeDocUserShare,
)
from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
from miy_api.domains.docs.timestamps import touch_native_doc
from miy_api.domains.media.service import sync_embedded_media
from miy_api.domains.rag.contracts import RagSyncOperation
from miy_api.domains.official_apps.writer import (
    WriterIdentity,
    bind_transaction,
    require_active_writer,
)
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE

logger = logging.getLogger(__name__)

PAGE_SOURCE_NATIVE_DOC = "native_doc_page"

COLLAB_RELAY_CHANNEL_PREFIX = "docs-collab"
# Pinned composition identity. Never adopt a database generation at reconnect.
DOCS_WRITER_IDENTITY = WriterIdentity(SUITE_SCOPE, "legacy", 1)


def writer_close_choice(error: HTTPException) -> tuple[int, str] | None:
    if (
        error.status_code == 503
        and isinstance(error.detail, LocalizedApiMessage)
        and error.detail.code == "official_apps.writer_unavailable"
    ):
        return (1013, "official_writer_unavailable")
    return None


def _is_writer_unavailable(error: Exception) -> bool:
    return is_official_writer_guard_error(error) or (
        isinstance(error, HTTPException) and writer_close_choice(error) is not None
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_DEFAULT_BLOCK_PROPS = {
    "backgroundColor": "default",
    "textAlignment": "left",
    "textColor": "default",
}


def _normalize_block_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_block_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key == "id":
            continue
        if key == "props" and isinstance(item, dict):
            props = {
                prop_key: _normalize_block_value(prop_value)
                for prop_key, prop_value in item.items()
                if _DEFAULT_BLOCK_PROPS.get(prop_key) != prop_value
            }
            if props:
                normalized[key] = props
            continue
        if key in {"children", "content"} and item == []:
            continue
        if key == "styles" and item == {}:
            continue
        normalized[key] = _normalize_block_value(item)
    return normalized


def _normalize_block_content(blocks: list[dict] | None) -> list[Any]:
    return [_normalize_block_value(block) for block in blocks or []]


def block_content_equal(left: list[dict] | None, right: list[dict] | None) -> bool:
    return _normalize_block_content(left) == _normalize_block_content(right)


def _is_stale_yjs_state(*, current_state: bytes | None, incoming_state: bytes | None) -> bool:
    if not current_state or not incoming_state:
        return False
    try:
        current_doc = Y.YDoc()
        incoming_doc = Y.YDoc()
        Y.apply_update(current_doc, current_state)
        Y.apply_update(incoming_doc, incoming_state)
        missing_from_incoming = bytes(
            Y.encode_state_as_update(
                current_doc,
                Y.encode_state_vector(incoming_doc),
            )
        )
        return missing_from_incoming != b"\x00\x00"
    except Exception:
        logger.exception("Failed to compare docs collaboration Yjs states.")
        return False


def make_page_ref(source_type: str, source_page_id: str) -> str:
    return f"{source_type}__{source_page_id}"


def split_page_ref(page_ref: str) -> tuple[str | None, str]:
    if "__" not in page_ref:
        return None, page_ref
    return tuple(page_ref.split("__", 1))  # type: ignore[return-value]


def make_room_key(source_type: str, source_page_id: str) -> str:
    return f"{source_type}:{source_page_id}"


@dataclass(frozen=True)
class CollabPageContext:
    page_ref: str
    source_type: str
    source_page_id: str
    room_key: str
    can_edit: bool
    content_blocks: list[dict] | None
    default_actor_user_id: str


def _load_native_page_for_collab(db: Session, page_id: str) -> NativeDocPage | None:
    return db.scalar(
        select(NativeDocPage)
        .options(
            selectinload(NativeDocPage.created_by),
            joinedload(NativeDocPage.doc).selectinload(NativeDoc.targets),
            joinedload(NativeDocPage.doc)
            .selectinload(NativeDoc.user_shares)
            .selectinload(NativeDocUserShare.user),
        )
        .where(NativeDocPage.id == page_id)
    )


def _resolve_native_page_context(db: Session, user: User, page_id: str) -> CollabPageContext:
    from miy_api.domains.docs.access_context import native_page_context_from_page_or_404

    context = native_page_context_from_page_or_404(
        db, page_id=page_id, user=user, share_token=None, require="view"
    )
    page = context.page
    if page.content_format != "block":
        raise localized_http_exception(status_code=404, code="docs.page_not_found")
    return CollabPageContext(
        page_ref=make_page_ref(PAGE_SOURCE_NATIVE_DOC, page.id),
        source_type=PAGE_SOURCE_NATIVE_DOC,
        source_page_id=page.id,
        room_key=make_room_key(PAGE_SOURCE_NATIVE_DOC, page.id),
        can_edit=context.access.can_edit,
        content_blocks=page.content_blocks,
        default_actor_user_id=page.created_by_id,
    )


def resolve_collab_page_context(
    db: Session,
    user: User,
    page_ref: str,
) -> CollabPageContext:
    source_type, source_page_id = split_page_ref(page_ref)
    if source_type == PAGE_SOURCE_NATIVE_DOC:
        return _resolve_native_page_context(db, user, source_page_id)
    raise localized_http_exception(status_code=404, code="docs.page_not_found")


def get_collab_document(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
) -> DocsCollabDocument | None:
    return db.scalar(
        select(DocsCollabDocument).where(
            DocsCollabDocument.source_type == source_type,
            DocsCollabDocument.source_page_id == source_page_id,
        )
    )


def ensure_collab_document(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
    room_key: str,
    snapshot_content_blocks: list[dict] | None,
) -> DocsCollabDocument:
    """Get-or-create the collab document row for a page.

    Two concurrent calls (e.g. two meeting-notes sessions opened at the same
    instant) both missed the cache and raced to ``INSERT``, producing
    ``UniqueViolation`` on ``uq_docs_collab_documents_room_key``. Use a
    Postgres upsert (``INSERT ... ON CONFLICT DO NOTHING``) so the racing
    insert is absorbed silently; whichever transaction wins owns the row
    and the other re-queries it after the conflict.
    """
    existing = get_collab_document(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
    )
    if existing is not None:
        if existing.room_key != room_key:
            existing.room_key = room_key
        if existing.snapshot_content_blocks is None and snapshot_content_blocks is not None:
            existing.snapshot_content_blocks = snapshot_content_blocks
        db.add(existing)
        db.flush()
        return existing

    stmt = (
        pg_insert(DocsCollabDocument)
        .values(
            id=new_id(),
            room_key=room_key,
            source_type=source_type,
            source_page_id=source_page_id,
            snapshot_content_blocks=snapshot_content_blocks,
        )
        .on_conflict_do_nothing(
            index_elements=[DocsCollabDocument.room_key],
        )
    )
    db.execute(stmt)
    db.flush()

    # Re-fetch the canonical row. With DO NOTHING we cannot rely on RETURNING,
    # so we always read back the state the winning transaction left us.
    collab = get_collab_document(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
    )
    if collab is None:
        # Extremely unlikely but not impossible if a concurrent delete raced
        # between our upsert and re-read. Fall back to a hard insert and let
        # any error propagate.
        raise RuntimeError(
            "Collab document disappeared immediately after upsert. "
            f"source_type={source_type} source_page_id={source_page_id}"
        )
    if collab.snapshot_content_blocks is None and snapshot_content_blocks is not None:
        collab.snapshot_content_blocks = snapshot_content_blocks
        db.add(collab)
        db.flush()
    return collab


def ensure_collab_document_state(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
    room_key: str,
    snapshot_content_blocks: list[dict] | None,
) -> DocsCollabDocument:
    collab = ensure_collab_document(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
        room_key=room_key,
        snapshot_content_blocks=snapshot_content_blocks,
    )
    if collab.yjs_state is None and snapshot_content_blocks is not None:
        collab.yjs_state = blocks_to_yjs_state(snapshot_content_blocks)
        collab.snapshot_content_blocks = snapshot_content_blocks
        collab.last_snapshot_at = collab.last_snapshot_at or _utcnow()
        db.add(collab)
        db.flush()
    return collab


def update_collab_snapshot_record(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
    room_key: str,
    snapshot_content_blocks: list[dict] | None,
    yjs_state: bytes | None,
) -> DocsCollabDocument:
    collab = ensure_collab_document(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
        room_key=room_key,
        snapshot_content_blocks=snapshot_content_blocks,
    )
    collab.snapshot_content_blocks = snapshot_content_blocks
    collab.yjs_state = yjs_state
    collab.last_snapshot_at = _utcnow()
    db.add(collab)
    db.flush()
    return collab


def sync_collab_record_from_rest_patch(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
    snapshot_content_blocks: list[dict] | None,
) -> None:
    update_collab_snapshot_record(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
        room_key=make_room_key(source_type, source_page_id),
        snapshot_content_blocks=snapshot_content_blocks,
        yjs_state=blocks_to_yjs_state(snapshot_content_blocks),
    )


def delete_collab_document(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
) -> None:
    db.execute(
        delete(DocsCollabDocument).where(
            DocsCollabDocument.source_type == source_type,
            DocsCollabDocument.source_page_id == source_page_id,
        )
    )


def persist_collab_snapshot_to_page(
    db: Session,
    *,
    current_user: User,
    source_type: str,
    source_page_id: str,
    content_blocks: list[dict] | None,
) -> bool:
    if source_type == PAGE_SOURCE_NATIVE_DOC:
        page = _load_native_page_for_collab(db, source_page_id)
        if (
            page is None
            or page.doc is None
            or page.trashed_at is not None
            or page.doc.trashed_at is not None
        ):
            raise localized_http_exception(status_code=404, code="docs.page_not_found")
        if block_content_equal(page.content_blocks, content_blocks):
            return False
        page.content_blocks = content_blocks
        sync_embedded_media(db, content_blocks, "docs_native_page", page.id, current_user)
        db.add(page)
        touch_native_doc(page.doc)
        db.add(page.doc)
        db.flush()
        enqueue_native_doc_rag_sync(
            db,
            doc=page.doc,
            operation=RagSyncOperation.UPSERT,
        )
        return True

    raise localized_http_exception(status_code=404, code="docs.page_not_found")


def materialize_collab_room_state(
    db: Session,
    *,
    source_type: str,
    source_page_id: str,
    room_key: str,
    yjs_state: bytes,
    actor_user_id: str,
    fallback_actor_user_id: str,
) -> DocsCollabDocument:
    content_blocks = yjs_state_to_blocks(yjs_state)
    actor = db.scalar(select(User).where(User.id == actor_user_id))
    if actor is None:
        actor = db.scalar(select(User).where(User.id == fallback_actor_user_id))
    if actor is None:
        raise localized_http_exception(status_code=404, code="docs.collaboration_actor_not_found")

    existing = get_collab_document(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
    )
    if existing is not None and _is_stale_yjs_state(
        current_state=existing.yjs_state,
        incoming_state=yjs_state,
    ):
        logger.info(
            "Skipping stale docs collaboration runtime flush: room_key=%s source_type=%s source_page_id=%s",
            room_key,
            source_type,
            source_page_id,
        )
        return existing

    persist_collab_snapshot_to_page(
        db,
        current_user=actor,
        source_type=source_type,
        source_page_id=source_page_id,
        content_blocks=content_blocks,
    )
    return update_collab_snapshot_record(
        db,
        source_type=source_type,
        source_page_id=source_page_id,
        room_key=room_key,
        snapshot_content_blocks=content_blocks,
        yjs_state=yjs_state,
    )


class DocsPersistenceDeadline(TimeoutError):
    """The current background snapshot exhausted its SQL transaction budget."""


@contextmanager
def _docs_persistence_sql_deadline(db: Session, seconds: float):
    """Budget this Connection only; never change engine/pool or session defaults.

    Python cancellation cannot stop a SQL thread. PostgreSQL must cancel a
    blocked statement itself. Remaining time is applied before every statement
    so a sequence of locks cannot reset the snapshot's entire budget each time.
    Pool acquisition/connection establishment still use the existing DB policy.
    """
    deadline = monotonic() + seconds
    connection = db.connection()

    def before_statement(_conn, cursor, _statement, _parameters, _context, _executemany):
        remaining_ms = int((deadline - monotonic()) * 1000)
        if remaining_ms <= 0:
            raise DocsPersistenceDeadline("docs_snapshot_sql_deadline")
        # Raw cursor avoids recursively dispatching SQLAlchemy's event. Values
        # are bound parameters, and true makes both settings transaction-local.
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true), "
            "set_config('lock_timeout', %s, true)",
            (str(remaining_ms), str(remaining_ms)),
        )

    event.listen(connection, "before_cursor_execute", before_statement)
    try:
        yield
    finally:
        event.remove(connection, "before_cursor_execute", before_statement)


def _is_persistence_timeout(error: Exception) -> bool:
    if isinstance(error, DocsPersistenceDeadline):
        return True
    if isinstance(error, DBAPIError):
        original = error.orig
        return (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) in {
            "57014",  # PostgreSQL cancelled the statement (including its timeout).
            "55P03",  # The transaction-local lock timeout expired.
        }
    return False


def _persist_docs_runtime_state_sync(
    session_factory: Any,
    *,
    source_type: str,
    source_page_id: str,
    room_key: str,
    fallback_actor_user_id: str,
    yjs_state: bytes,
    actor_user_id: str,
    writer_identity: WriterIdentity = DOCS_WRITER_IDENTITY,
    timeout_seconds: float | None = None,
) -> None:
    db = session_factory()
    try:
        seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else get_settings().collab_cleanup_timeout_seconds
        )
        with _docs_persistence_sql_deadline(db, seconds):
            require_active_writer(db, writer_identity)
            bind_transaction(db, writer_identity)
            materialize_collab_room_state(
                db,
                source_type=source_type,
                source_page_id=source_page_id,
                room_key=room_key,
                yjs_state=yjs_state,
                actor_user_id=actor_user_id,
                fallback_actor_user_id=fallback_actor_user_id,
            )
            # commit() is a DBAPI operation rather than a cursor event. Refresh
            # the remaining PostgreSQL budget immediately before COMMIT too.
            db.execute(select(1))
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class DocsCollabHub:
    def __init__(
        self,
        *,
        instance_id: str | None = None,
        bus: CollabBus | None = None,
    ) -> None:
        self._settings = get_settings()
        self._lock = asyncio.Lock()
        self._rooms: dict[str, CollabRoomRuntime] = {}
        self._session_factory = get_session_factory()
        self.writer_identity = DOCS_WRITER_IDENTITY
        self._disposals: set[asyncio.Task[None]] = set()
        self._instance_id = instance_id or self._settings.instance_id or new_id()
        self._bus = bus
        if self._bus is None:
            self._bus = RedisCollabBus(
                self._settings.collab_redis_url,
                instance_id=self._instance_id,
                channel_prefix=COLLAB_RELAY_CHANNEL_PREFIX,
                operation_timeout_seconds=self._settings.collab_cleanup_timeout_seconds,
            )

    @property
    def relay_available(self) -> bool:
        return self._bus.available

    @property
    def relay_read_only_reason(self) -> str | None:
        return self._bus.failure_reason

    async def startup(self) -> None:
        await self._bus.startup()

    async def get_room(
        self,
        context: CollabPageContext,
        yjs_state: bytes | None,
    ) -> CollabRoomRuntime:
        async with self._lock:
            runtime = self._rooms.get(context.room_key)
            if runtime is not None:
                return runtime

            room = YRoom(ready=True, log=logger)
            room_task = asyncio.create_task(room.start())
            await room.started.wait()
            if yjs_state:
                Y.apply_update(room.ydoc, yjs_state)

            runtime = CollabRoomRuntime(
                room_key=context.room_key,
                default_actor_user_id=context.default_actor_user_id,
                room=room,
                room_task=room_task,
                metadata={
                    "source_type": context.source_type,
                    "source_page_id": context.source_page_id,
                },
            )
            room.on_message = lambda message: self._handle_room_message(runtime, message)
            room.ydoc.observe_after_transaction(
                lambda event: self._handle_room_update(
                    runtime,
                    event.get_update(),
                )
            )
            if self._bus.available:
                runtime.relay_pubsub = await self._bus.create_pubsub(context.room_key)
                runtime.relay_task = asyncio.create_task(self._run_room_relay_listener(runtime))
            self._rooms[context.room_key] = runtime
            return runtime

    async def acquire_connection_slot(
        self,
        runtime: CollabRoomRuntime,
        user_id: str,
    ) -> None:
        async with self._lock:
            if runtime.metadata.get("writer_fenced"):
                raise official_writer_unavailable()
            if self._rooms.get(runtime.room_key) is not runtime:
                raise RuntimeError("Collaboration room is no longer active.")
            if runtime.active_connection_count >= self._settings.collab_max_room_clients:
                raise CollabConnectionLimitExceeded()
            user_count = runtime.active_user_connections.get(user_id, 0)
            if user_count >= self._settings.collab_max_user_room_connections:
                raise CollabConnectionLimitExceeded()
            runtime.active_connection_count += 1
            runtime.active_user_connections[user_id] = user_count + 1
            logger.info(
                "Docs collaboration connection accepted: room_key=%s user_id=%s "
                "room_connections=%s user_room_connections=%s",
                runtime.room_key,
                user_id,
                runtime.active_connection_count,
                runtime.active_user_connections[user_id],
            )

    async def release_connection_slot(
        self,
        runtime: CollabRoomRuntime,
        user_id: str,
    ) -> None:
        async with self._lock:
            user_count = runtime.active_user_connections.get(user_id, 0)
            if user_count <= 1:
                runtime.active_user_connections.pop(user_id, None)
            else:
                runtime.active_user_connections[user_id] = user_count - 1
            runtime.active_connection_count = max(0, runtime.active_connection_count - 1)
            logger.info(
                "Docs collaboration connection released: room_key=%s user_id=%s "
                "room_connections=%s user_room_connections=%s",
                runtime.room_key,
                user_id,
                runtime.active_connection_count,
                runtime.active_user_connections.get(user_id, 0),
            )

    def fence_runtime(self, runtime: CollabRoomRuntime) -> None:
        """Invalidate immediately; dispose on a separate task, outside client send locks."""
        runtime.metadata["writer_fenced"] = "true"
        if self._rooms.get(runtime.room_key) is runtime:
            self._rooms.pop(runtime.room_key)
        self._start_disposal(runtime, persist=False, close_code=1013)

    def _start_disposal(
        self, runtime: CollabRoomRuntime, *, persist: bool, close_code: int | None = None
    ) -> asyncio.Task[None] | None:
        if runtime.metadata.get("disposing"):
            return None
        runtime.metadata["disposing"] = "true"
        task = asyncio.create_task(
            self._dispose_runtime(runtime, persist=persist, close_code=close_code)
        )
        self._disposals.add(task)
        task.add_done_callback(self._disposals.discard)
        return task

    async def cleanup_room(
        self, room_key: str, *, expected_runtime: CollabRoomRuntime | None = None
    ) -> None:
        async with self._lock:
            runtime = self._rooms.get(room_key)
            if (
                runtime is None
                or (expected_runtime is not None and runtime is not expected_runtime)
                or runtime.room.clients
                or runtime.active_connection_count
            ):
                return
            self._rooms.pop(room_key)
        task = self._start_disposal(runtime, persist=True)
        if task is not None:
            await asyncio.shield(task)

    async def _dispose_runtime(
        self, runtime: CollabRoomRuntime, *, persist: bool, close_code: int | None
    ) -> None:
        if runtime.flush_task is not None:
            runtime.flush_task.cancel()
            await self._run_cleanup_step(
                runtime,
                "flush task cancellation",
                asyncio.gather(runtime.flush_task, return_exceptions=True),
            )
        if persist and not runtime.metadata.get("writer_fenced"):
            await self._run_cleanup_step(runtime, "flush", self._flush_runtime(runtime))
        if runtime.metadata.get("writer_fenced"):
            close_code = 1013
        if close_code is not None:
            for client in list(runtime.room.clients):
                await self._run_cleanup_step(
                    runtime,
                    "client close",
                    client.close(
                        code=close_code,
                        reason=(
                            "official_writer_unavailable"
                            if close_code == 1013
                            else "Server shutdown."
                        ),
                    ),
                )
        if runtime.relay_task is not None:
            runtime.relay_task.cancel()
            await self._run_cleanup_step(
                runtime,
                "relay task cancellation",
                asyncio.gather(runtime.relay_task, return_exceptions=True),
            )
        if runtime.relay_pubsub is not None:
            await self._run_cleanup_step(
                runtime,
                "relay pubsub close",
                self._bus.close_pubsub(runtime.relay_pubsub, runtime.room_key),
            )
        self._stop_room(runtime)
        await self._run_cleanup_step(
            runtime,
            "room task stop",
            asyncio.gather(runtime.room_task, return_exceptions=True),
        )
        await self._release_room_state(runtime)

    async def shutdown(self) -> None:
        async with self._lock:
            runtimes = list(self._rooms.values())
            self._rooms.clear()
        for runtime in runtimes:
            self._start_disposal(runtime, persist=True, close_code=1001)
        # Includes rooms already retired by a frame, relay or background flush.
        while self._disposals:
            await asyncio.gather(*tuple(self._disposals))
        await self._bus.shutdown()

    def require_writer(self) -> None:
        with self._session_factory() as db:
            require_active_writer(db, self.writer_identity)

    async def _run_cleanup_step(
        self,
        runtime: CollabRoomRuntime,
        label: str,
        awaitable,
    ) -> None:
        try:
            await asyncio.wait_for(
                awaitable,
                timeout=self._settings.collab_cleanup_timeout_seconds,
            )
        except TimeoutError:
            logger.warning(
                "Timed out during docs collaboration cleanup: room_key=%s step=%s",
                runtime.room_key,
                label,
            )
        except Exception as exc:
            logger.warning(
                "Failed during docs collaboration cleanup: room_key=%s step=%s error=%s",
                runtime.room_key,
                label,
                exc,
            )

    def _stop_room(self, runtime: CollabRoomRuntime) -> None:
        try:
            runtime.room.stop()
        except RuntimeError:
            return

    async def _release_room_state(self, runtime: CollabRoomRuntime) -> None:
        try:
            await release_yroom_thread_bound_state(runtime.room)
        except Exception as exc:
            logger.warning(
                "Failed to release docs collaboration room state: room_key=%s error=%s",
                runtime.room_key,
                exc,
            )

    async def _run_room_relay_listener(self, runtime: CollabRoomRuntime) -> None:
        assert runtime.relay_pubsub is not None
        try:
            while True:
                message = await runtime.relay_pubsub.get_message(timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
                await self._apply_remote_relay_message(runtime, message["data"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_relay_failure(exc)

    async def _apply_remote_relay_message(
        self,
        runtime: CollabRoomRuntime,
        raw_payload: object,
    ) -> None:
        if runtime.metadata.get("disposing"):
            return
        if not isinstance(raw_payload, (bytes, bytearray)):
            return
        payload = json.loads(raw_payload.decode("utf-8"))
        if payload.get("instance_id") == self._instance_id:
            return
        if payload.get("room_key") != runtime.room_key:
            return
        # A peer cannot bless an old update by relaying it under a new owner.
        if "writer" not in payload:
            # The original relay had no identity tag. Its sole compatibility
            # window is the initial, unattested legacy generation. Never infer
            # a current generation for an old producer or accept explicit null.
            if self.writer_identity != DOCS_WRITER_IDENTITY:
                return
        else:
            wire_identity = payload["writer"]
            if (
                not isinstance(wire_identity, dict)
                or type(wire_identity.get("generation")) is not int
                or wire_identity != asdict(self.writer_identity)
            ):
                return
        try:
            await asyncio.to_thread(self.require_writer)
        except HTTPException as exc:
            if writer_close_choice(exc) is None:
                raise
            self.fence_runtime(runtime)
            return
        if runtime.metadata.get("disposing"):
            return

        encoded_data = payload.get("data")
        if not isinstance(encoded_data, str):
            return
        data = base64.b64decode(encoded_data.encode("ascii"))

        if payload.get("type") == "yjs_update":
            update_hash = payload.get("hash")
            if not isinstance(update_hash, str):
                update_hash = hash_bytes(data)
            runtime.remember_remote_update_hash(update_hash)
            actor_user_id = payload.get("actor_user_id")
            if isinstance(actor_user_id, str) and actor_user_id:
                runtime.last_editor_user_id = actor_user_id
            Y.apply_update(runtime.room.ydoc, data)
            return

        if payload.get("type") == "awareness":
            for client in list(runtime.room.clients):
                await client.send(data)

    def _handle_room_message(self, runtime: CollabRoomRuntime, message: bytes) -> bool:
        if self._rooms.get(runtime.room_key) is not runtime:
            return True
        if not message or not self._bus.available:
            return False
        if message[0] == YMessageType.AWARENESS:
            asyncio.create_task(self._publish_awareness(runtime, message))
        return False

    def _handle_room_update(self, runtime: CollabRoomRuntime, update: bytes) -> None:
        if self._rooms.get(runtime.room_key) is not runtime:
            return
        if update == b"\x00\x00":
            return  # Native read transactions can emit this exact empty delta.
        update_hash = hash_bytes(update)
        should_publish = not runtime.consume_remote_update_hash(update_hash)
        self._schedule_flush(runtime)
        if should_publish and self._bus.available:
            asyncio.create_task(self._publish_update(runtime, update, update_hash))

    async def _publish_update(
        self,
        runtime: CollabRoomRuntime,
        update: bytes,
        update_hash: str,
    ) -> None:
        if runtime.metadata.get("disposing"):
            return
        try:
            await self._bus.publish(
                runtime.room_key,
                {
                    "instance_id": self._instance_id,
                    "room_key": runtime.room_key,
                    "type": "yjs_update",
                    "writer": asdict(self.writer_identity),
                    "hash": update_hash,
                    "actor_user_id": runtime.last_editor_user_id,
                    "data": base64.b64encode(update).decode("ascii"),
                },
            )
        except Exception as exc:
            await self._handle_relay_failure(exc)

    async def _publish_awareness(self, runtime: CollabRoomRuntime, message: bytes) -> None:
        if runtime.metadata.get("disposing"):
            return
        room_key = runtime.room_key
        try:
            await self._bus.publish(
                room_key,
                {
                    "instance_id": self._instance_id,
                    "room_key": room_key,
                    "type": "awareness",
                    "writer": asdict(self.writer_identity),
                    "data": base64.b64encode(message).decode("ascii"),
                },
            )
        except Exception as exc:
            await self._handle_relay_failure(exc)

    def _schedule_flush(self, runtime: CollabRoomRuntime) -> None:
        if runtime.flush_task is not None:
            runtime.flush_task.cancel()
        runtime.flush_task = asyncio.create_task(self._flush_after_delay(runtime))

    async def _flush_after_delay(self, runtime: CollabRoomRuntime) -> None:
        try:
            await asyncio.sleep(self._settings.collab_snapshot_debounce_ms / 1000)
            await self._flush_runtime(runtime)
        except asyncio.CancelledError:
            return

    async def _flush_runtime(self, runtime: CollabRoomRuntime) -> bool:
        async with runtime.flush_lock:
            if runtime.metadata.get("writer_fenced"):
                return False
            # Capture this snapshot and its original actor before shared admission waits.
            yjs_state = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            actor_user_id = runtime.last_editor_user_id or runtime.default_actor_user_id
            # Shared admission remains cancellable before the existing joined worker.
            async with native_persistence_lease():
                if runtime.metadata.get("writer_fenced"):
                    return False
                persistence = asyncio.create_task(
                    asyncio.to_thread(
                        _persist_docs_runtime_state_sync,
                        self._session_factory,
                        source_type=runtime.metadata["source_type"],
                        source_page_id=runtime.metadata["source_page_id"],
                        room_key=runtime.room_key,
                        fallback_actor_user_id=runtime.default_actor_user_id,
                        yjs_state=yjs_state,
                        actor_user_id=actor_user_id,
                        writer_identity=self.writer_identity,
                        timeout_seconds=self._settings.collab_cleanup_timeout_seconds,
                    )
                )
                cancelled = False
                try:
                    while True:
                        try:
                            await asyncio.shield(persistence)
                            break
                        except asyncio.CancelledError:
                            # Cancelling a debounce/cleanup task cannot stop SQL in
                            # a thread. Repeated cancellation must not release the
                            # flush lock before its transaction has finished.
                            cancelled = True
                            if persistence.cancelled():
                                raise
                except Exception as exc:
                    if _is_writer_unavailable(exc):
                        self.fence_runtime(runtime)
                    elif _is_persistence_timeout(exc):
                        logger.warning(
                            "Docs collaboration persistence timed out: room_key=%s",
                            runtime.room_key,
                        )
                    else:
                        logger.exception(
                            "Failed to persist docs collaboration room %s", runtime.room_key
                        )
                    return False
                finally:
                    if cancelled:
                        raise asyncio.CancelledError
                return True

    async def _handle_relay_failure(self, exc: Exception) -> None:
        if not self._bus.available:
            return
        logger.warning("Docs collaboration relay failed: %s", exc)
        self._bus.mark_failed()
        async with self._lock:
            runtimes = list(self._rooms.values())
        for runtime in runtimes:
            for client in list(runtime.room.clients):
                await client.close(
                    code=COLLAB_CLOSE_CODE_RELAY_UNAVAILABLE,
                    reason="Collaboration relay unavailable.",
                )
