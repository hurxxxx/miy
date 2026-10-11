from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from anyio import CancelScope, CapacityLimiter, create_task_group, to_thread
import y_py as Y
from ypy_websocket.yroom import YRoom
from ypy_websocket.yutils import YMessageType

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
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
from miy_api.domains.whiteboard.scene_state import (
    WhiteboardPersistenceIdentity,
    WhiteboardPersistenceRefused,
    WhiteboardPersistenceResult,
    persist_runtime_yjs_state,
    persistence_identity,
)

logger = logging.getLogger(__name__)

COLLAB_RELAY_CHANNEL_PREFIX = "whiteboard-collab"
COLLAB_PERSISTENCE_MAX_WORKERS = 4


@dataclass(frozen=True)
class WhiteboardCollabContext:
    whiteboard_id: str
    room_key: str
    can_edit: bool
    scene: dict[str, Any]
    default_actor_user_id: str
    collab_document_id: str | None = None


@dataclass
class _WhiteboardRoomRuntime(CollabRoomRuntime):
    persistence_identity: WhiteboardPersistenceIdentity | None = None
    persistence_outcome: WhiteboardPersistenceResult | None = None
    retained_yjs_state: bytes | None = field(default=None, repr=False)
    last_acknowledged_yjs_state: bytes | None = field(default=None, repr=False)


class WhiteboardCollabHub:
    def __init__(
        self,
        *,
        instance_id: str | None = None,
        bus: CollabBus | None = None,
    ) -> None:
        self._settings = get_settings()
        self._lock = asyncio.Lock()
        self._persistence_limiter = CapacityLimiter(COLLAB_PERSISTENCE_MAX_WORKERS)
        self._rooms: dict[str, CollabRoomRuntime] = {}
        self._disposals: set[asyncio.Task[None]] = set()
        # Local unresolved attempts survive native room disposal; observing an
        # existing Source row cannot establish their historical COMMIT outcome.
        self._uncertain_rooms: dict[WhiteboardPersistenceIdentity, _WhiteboardRoomRuntime] = {}
        self._retiring_rooms: dict[
            WhiteboardPersistenceIdentity, dict[int, _WhiteboardRoomRuntime]
        ] = {}
        self._session_factory = get_session_factory()
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
        context: WhiteboardCollabContext,
        yjs_state: bytes | None,
    ) -> CollabRoomRuntime:
        identity = (
            persistence_identity(
                context.whiteboard_id, context.collab_document_id, context.room_key
            )
            if context.collab_document_id is not None
            else None
        )
        async with self._lock:
            if identity is not None and identity in self._uncertain_rooms:
                raise WhiteboardPersistenceRefused("unresolved_incarnation")
            if identity is not None and identity in self._retiring_rooms:
                raise WhiteboardPersistenceRefused("retiring_incarnation")
            runtime = self._rooms.get(context.room_key)
            if (
                runtime is not None
                and not self._terminal(runtime)
                and (runtime.persistence_identity == identity)
            ):
                return runtime
            if runtime is not None:
                self._mark_retiring(runtime)
                self._rooms.pop(context.room_key)
                self._retire_runtime(
                    runtime, WhiteboardPersistenceResult("refused", "incarnation_replaced")
                )

            room = YRoom(ready=True, log=logger)
            room_task = asyncio.create_task(room.start())
            await room.started.wait()
            if yjs_state:
                Y.apply_update(room.ydoc, yjs_state)

            runtime = _WhiteboardRoomRuntime(
                room_key=context.room_key,
                default_actor_user_id=context.default_actor_user_id,
                room=room,
                room_task=room_task,
                metadata={"whiteboard_id": context.whiteboard_id},
                persistence_identity=identity,
            )
            if identity is not None:
                runtime.metadata["collab_document_id"] = identity.collab_document_id
            room.on_message = lambda message: self._handle_room_message(
                runtime,
                message,
            )
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
            if not self._current(runtime):
                raise RuntimeError("Collaboration room is no longer active.")
            if runtime.active_connection_count >= self._settings.collab_max_room_clients:
                raise CollabConnectionLimitExceeded()
            user_count = runtime.active_user_connections.get(user_id, 0)
            if user_count >= self._settings.collab_max_user_room_connections:
                raise CollabConnectionLimitExceeded()
            runtime.active_connection_count += 1
            runtime.active_user_connections[user_id] = user_count + 1
            logger.info(
                "Whiteboard collaboration connection accepted: room_key=%s user_id=%s "
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
                "Whiteboard collaboration connection released: room_key=%s user_id=%s "
                "room_connections=%s user_room_connections=%s",
                runtime.room_key,
                user_id,
                runtime.active_connection_count,
                runtime.active_user_connections.get(user_id, 0),
            )

    def _terminal(self, runtime):
        return bool(
            runtime.metadata.get("persistence_terminal") or runtime.metadata.get("disposing")
        )

    def _current(self, runtime):
        return (
            self._rooms.get(runtime.room_key) is runtime
            and not self._terminal(runtime)
            and runtime.persistence_identity not in self._uncertain_rooms
        )

    def _retire_runtime(self, runtime, outcome):
        runtime.persistence_outcome = outcome
        runtime.metadata["persistence_terminal"] = outcome.status
        self._mark_retiring(runtime)
        if outcome.status == "unknown" and runtime.persistence_identity is not None:
            self._uncertain_rooms.setdefault(runtime.persistence_identity, runtime)
        key = (
            runtime.persistence_identity.room_key
            if runtime.persistence_identity
            else runtime.room_key
        )
        if self._rooms.get(key) is runtime:
            self._rooms.pop(key)
        elif outcome.status == "unknown":
            resident = self._rooms.get(key)
            if (
                resident is not None
                and resident.persistence_identity == runtime.persistence_identity
            ):
                # Cover a same-incarnation replacement already present before
                # uncertainty was registered. Do not leave a silently skipped socket.
                self._retire_runtime(
                    resident, WhiteboardPersistenceResult("refused", "unresolved_incarnation")
                )
        self._start_disposal(runtime, persist=False, close_code=1013)

    def _mark_retiring(self, runtime):
        if runtime.persistence_identity is not None and runtime.room.ydoc is not None:
            self._retiring_rooms.setdefault(runtime.persistence_identity, {})[id(runtime)] = runtime

    def _forget_retiring(self, runtime):
        owners = self._retiring_rooms.get(runtime.persistence_identity)
        if owners is not None:
            owners.pop(id(runtime), None)
            if not owners:
                self._retiring_rooms.pop(runtime.persistence_identity)

    def _start_disposal(self, runtime, *, persist, close_code=None):
        if runtime.metadata.get("disposing"):
            return None
        self._mark_retiring(runtime)
        runtime.metadata["disposing"] = "true"
        task = asyncio.create_task(
            self._dispose_runtime(runtime, persist=persist, close_code=close_code)
        )
        self._disposals.add(task)
        task.add_done_callback(self._disposals.discard)
        return task

    async def cleanup_room(self, room_key: str, *, expected_runtime=None) -> None:
        async with self._lock:
            runtime = self._rooms.get(room_key)
            if (
                runtime is None
                or expected_runtime is not None
                and runtime is not expected_runtime
                or runtime.room.clients
                or runtime.active_connection_count
            ):
                return
            self._mark_retiring(runtime)
            self._rooms.pop(room_key, None)
        task = self._start_disposal(runtime, persist=True)
        if task is not None:

            async def wait_disposal_owned():
                with CancelScope(shield=True):
                    await task

            async with create_task_group() as group:
                group.start_soon(wait_disposal_owned)

    async def _dispose_runtime(self, runtime, *, persist, close_code):
        async def dispose_owned(close_code):
            # Joining this private owner also finishes native disposal when the
            # cleanup/shutdown parent is canceled while final admission waits.
            with CancelScope(shield=True):
                if runtime.flush_task is not None:
                    runtime.flush_task.cancel()
                    await self._run_cleanup_step(
                        runtime,
                        "flush task cancellation",
                        asyncio.gather(runtime.flush_task, return_exceptions=True),
                    )
                # The debounce pointer may have been replaced while an older shielded
                # worker still owns this lock. Even an acknowledged-byte skip must join it.
                async with runtime.flush_lock:
                    final_yjs_state = (
                        bytes(Y.encode_state_as_update(runtime.room.ydoc))
                        if persist
                        and not runtime.metadata.get("persistence_terminal")
                        and runtime.room.ydoc is not None
                        else None
                    )
                    needs_flush = (
                        final_yjs_state is not None
                        and final_yjs_state != runtime.last_acknowledged_yjs_state
                    )
                    if needs_flush:
                        runtime.retained_yjs_state = final_yjs_state
                if needs_flush:
                    # Admission wait is not the SQL deadline or non-SQL cleanup timeout.
                    # This owner keeps native state and detached bytes until work joins.
                    await self._flush_runtime(runtime, allow_disposing=True)
                if runtime.metadata.get("persistence_terminal"):
                    close_code = 1013
                if close_code is not None:
                    for client in list(runtime.room.clients):
                        await self._run_cleanup_step(
                            runtime,
                            "client close",
                            client.close(
                                code=close_code,
                                reason=(
                                    "whiteboard_persistence_unavailable"
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
                # Clear only after joined SQL and this native disposal complete. Unknown
                # attempts remain blocked by their separate retained incarnation tombstone.
                self._forget_retiring(runtime)

        async with create_task_group() as group:
            group.start_soon(dispose_owned, close_code)

    async def shutdown(self) -> None:
        async def shutdown_owned():
            # Caller cancellation must not cancel gather and return after only
            # the first completed disposal while another final owner still runs.
            with CancelScope(shield=True):
                async with self._lock:
                    runtimes = list(self._rooms.values())
                    for runtime in runtimes:
                        self._mark_retiring(runtime)
                    self._rooms.clear()

                for runtime in runtimes:
                    self._start_disposal(runtime, persist=True, close_code=1001)
                while self._disposals:
                    await asyncio.gather(*tuple(self._disposals))
                await self._bus.shutdown()

        async with create_task_group() as group:
            group.start_soon(shutdown_owned)

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
                "Timed out during whiteboard collaboration cleanup: room_key=%s step=%s",
                runtime.room_key,
                label,
            )
        except Exception as exc:
            logger.warning(
                "Failed during whiteboard collaboration cleanup: room_key=%s step=%s error=%s",
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
                "Failed to release whiteboard collaboration room state: room_key=%s error=%s",
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
        if not self._current(runtime):
            return
        if not isinstance(raw_payload, (bytes, bytearray)):
            return
        payload = json.loads(raw_payload.decode("utf-8"))
        if payload.get("instance_id") == self._instance_id:
            return
        if payload.get("room_key") != runtime.room_key:
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
                if not self._current(runtime):
                    return
                await client.send(data)

    def _handle_room_message(self, runtime, message: bytes) -> bool:
        if not self._current(runtime):
            return True  # Pinned YRoom skips native frame processing only for True.
        if not message or not self._bus.available:
            return False
        if message[0] == YMessageType.AWARENESS:
            asyncio.create_task(self._publish_awareness(runtime, message))
        return False

    def _handle_room_update(self, runtime, update: bytes) -> None:
        if not self._current(runtime):
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
        if not self._current(runtime) or not self._bus.available:
            return
        try:
            await self._bus.publish(
                runtime.room_key,
                {
                    "instance_id": self._instance_id,
                    "room_key": runtime.room_key,
                    "type": "yjs_update",
                    "hash": update_hash,
                    "actor_user_id": runtime.last_editor_user_id,
                    "data": base64.b64encode(update).decode("ascii"),
                },
            )
        except Exception as exc:
            await self._handle_relay_failure(exc)

    async def _publish_awareness(self, runtime, message: bytes) -> None:
        if not self._current(runtime) or not self._bus.available:
            return
        try:
            await self._bus.publish(
                runtime.room_key,
                {
                    "instance_id": self._instance_id,
                    "room_key": runtime.room_key,
                    "type": "awareness",
                    "data": base64.b64encode(message).decode("ascii"),
                },
            )
        except Exception as exc:
            await self._handle_relay_failure(exc)

    def _schedule_flush(self, runtime: CollabRoomRuntime) -> None:
        if not self._current(runtime):
            return
        if runtime.flush_task is not None:
            runtime.flush_task.cancel()
        runtime.flush_task = asyncio.create_task(self._flush_after_delay(runtime))

    async def _flush_after_delay(self, runtime: CollabRoomRuntime) -> None:
        try:
            await asyncio.sleep(self._settings.collab_snapshot_debounce_ms / 1000)
            await self._flush_runtime(runtime)
        except asyncio.CancelledError:
            return

    async def _flush_runtime(self, runtime: CollabRoomRuntime, *, allow_disposing=False) -> bool:
        async with runtime.flush_lock:
            if runtime.metadata.get("persistence_terminal") or (
                runtime.metadata.get("disposing") and not allow_disposing
            ):
                return False
            try:
                identity = persistence_identity(
                    runtime.metadata.get("whiteboard_id"),
                    runtime.metadata.get("collab_document_id"),
                    runtime.room_key,
                )
                if identity != runtime.persistence_identity or runtime.room.ydoc is None:
                    raise WhiteboardPersistenceRefused("invalid_capture")
                if identity in self._uncertain_rooms:
                    self._retire_runtime(
                        runtime, WhiteboardPersistenceResult("unknown", "unresolved_incarnation")
                    )
                    return False
            except WhiteboardPersistenceRefused as exc:
                self._retire_runtime(runtime, WhiteboardPersistenceResult("refused", exc.reason))
                return False
            # Parent admission stays cancellable before the private shielded child.
            # Its hub-wide permit includes worker cleanup and outcome transfer/join.
            async with self._persistence_limiter:
                # Process-wide admission precedes Session creation and its SQL clock.
                async with native_persistence_lease():
                    if (
                        runtime.metadata.get("persistence_terminal")
                        or (runtime.metadata.get("disposing") and not allow_disposing)
                        or (
                            not allow_disposing and self._rooms.get(runtime.room_key) is not runtime
                        )
                    ):
                        return False
                    try:
                        current_identity = persistence_identity(
                            runtime.metadata.get("whiteboard_id"),
                            runtime.metadata.get("collab_document_id"),
                            runtime.room_key,
                        )
                        if (
                            current_identity != identity
                            or identity != runtime.persistence_identity
                            or runtime.room.ydoc is None
                        ):
                            raise WhiteboardPersistenceRefused("invalid_capture")
                        if identity in self._uncertain_rooms:
                            self._retire_runtime(
                                runtime,
                                WhiteboardPersistenceResult("unknown", "unresolved_incarnation"),
                            )
                            return False
                    except WhiteboardPersistenceRefused as exc:
                        self._retire_runtime(
                            runtime, WhiteboardPersistenceResult("refused", exc.reason)
                        )
                        return False
                    # Native objects remain on this loop; only detached bytes cross to SQL.
                    yjs_state = bytes(Y.encode_state_as_update(runtime.room.ydoc))

                    async def persist_owned():
                        with CancelScope(shield=True):
                            try:
                                outcome = await to_thread.run_sync(
                                    partial(
                                        persist_runtime_yjs_state,
                                        self._session_factory,
                                        whiteboard_id=identity.whiteboard_id,
                                        yjs_state=yjs_state,
                                        expected_collab_id=identity.collab_document_id,
                                        expected_room_key=identity.room_key,
                                        timeout_seconds=self._settings.collab_cleanup_timeout_seconds,
                                    ),
                                    limiter=CapacityLimiter(1),
                                    abandon_on_cancel=False,
                                )
                                if not isinstance(outcome, WhiteboardPersistenceResult):
                                    outcome = WhiteboardPersistenceResult(
                                        "unknown", "worker_outcome_unknown"
                                    )
                            except WhiteboardPersistenceRefused as exc:
                                outcome = WhiteboardPersistenceResult("refused", exc.reason)
                            except BaseException:
                                outcome = WhiteboardPersistenceResult(
                                    "unknown", "worker_outcome_unknown"
                                )
                            # Transfer the result before the group forwards host cancellation.
                            runtime.persistence_outcome = outcome
                            if outcome.status == "acknowledged":
                                runtime.last_acknowledged_yjs_state = yjs_state
                                runtime.retained_yjs_state = None
                            else:
                                runtime.retained_yjs_state = yjs_state
                                self._retire_runtime(runtime, outcome)

                    async with create_task_group() as group:
                        group.start_soon(persist_owned)
                    return runtime.persistence_outcome.status == "acknowledged"

    async def _handle_relay_failure(self, exc: Exception) -> None:
        if not self._bus.available:
            return
        logger.warning("Whiteboard collaboration relay failed: %s", exc)
        self._bus.mark_failed()
        async with self._lock:
            runtimes = list(self._rooms.values())
        for runtime in runtimes:
            for client in list(runtime.room.clients):
                await client.close(
                    code=COLLAB_CLOSE_CODE_RELAY_UNAVAILABLE,
                    reason="Collaboration relay unavailable.",
                )
