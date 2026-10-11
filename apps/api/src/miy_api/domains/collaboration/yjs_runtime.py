from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import logging
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol, cast

from fastapi import HTTPException, WebSocket
from redis import asyncio as redis_asyncio
from redis.asyncio.client import PubSub
from starlette.websockets import WebSocketDisconnect, WebSocketState
from uvicorn.protocols.utils import ClientDisconnected
from ypy_websocket.yroom import YRoom
from ypy_websocket.yutils import YMessageType

logger = logging.getLogger(__name__)

COLLAB_CLOSE_CODE_RELAY_UNAVAILABLE = 1013
COLLAB_CLOSE_CODE_TOO_MANY_CONNECTIONS = 4429
COLLAB_CLOSE_REASON_TOO_MANY_CONNECTIONS = "too_many_connections"
REMOTE_UPDATE_HASH_CACHE_SIZE = 512


class CollabSubscription(Protocol):
    async def get_message(self, timeout: float = 0.0) -> dict[str, object] | None: ...


class CollabBus(Protocol):
    instance_id: str

    @property
    def available(self) -> bool: ...

    @property
    def failure_reason(self) -> str | None: ...

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def create_pubsub(self, room_key: str) -> CollabSubscription: ...

    async def publish(self, room_key: str, payload: dict[str, object]) -> None: ...

    async def close_pubsub(
        self,
        pubsub: CollabSubscription,
        room_key: str,
    ) -> None: ...

    def mark_failed(self, *, reason: str = "relay_unavailable") -> None: ...


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(eq=False)
class _NativePersistenceWaiter:
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[None]
    disposal: bool
    state: str = "waiting"


class NativePersistenceGC:
    """Process-wide exclusion between snapshot workers and explicit native GC.

    Only counters and queues use the thread lock. Every wait remains on its own
    event loop; readers run in parallel, while a waiting disposal closes new
    reader admission until the active workers and their cleanup have joined.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._readers = 0
        self._disposing = False
        self._waiting_readers: deque[_NativePersistenceWaiter] = deque()
        self._waiting_disposals: deque[_NativePersistenceWaiter] = deque()

    def _grant_locked(self) -> list[_NativePersistenceWaiter]:
        if self._disposing:
            return []
        if self._waiting_disposals:
            if self._readers:
                return []
            waiter = self._waiting_disposals.popleft()
            waiter.state = "held"
            self._disposing = True
            return [waiter]
        granted = list(self._waiting_readers)
        self._waiting_readers.clear()
        for waiter in granted:
            waiter.state = "held"
        self._readers += len(granted)
        return granted

    def _finish(self, waiter: _NativePersistenceWaiter) -> list[_NativePersistenceWaiter]:
        with self._lock:
            if waiter.state == "released":
                return []
            if waiter.state == "held":
                if waiter.disposal:
                    self._disposing = False
                else:
                    self._readers -= 1
            else:
                queue = self._waiting_disposals if waiter.disposal else self._waiting_readers
                queue.remove(waiter)
            waiter.state = "released"
            return self._grant_locked()

    def _notify(self, waiter: _NativePersistenceWaiter) -> None:
        # This callback always runs on the Future's own loop. A cancellation
        # between grant and delivery must also surrender the reserved lease.
        if waiter.future.done():
            self._wake(self._finish(waiter))
        else:
            waiter.future.set_result(None)

    def _wake(self, granted: list[_NativePersistenceWaiter]) -> None:
        pending = deque(granted)
        while pending:
            waiter = pending.popleft()
            try:
                waiter.loop.call_soon_threadsafe(self._notify, waiter)
            except RuntimeError:
                # A closed loop cannot consume its grant. Do not strand other
                # loops or keep a phantom reader/exclusive owner indefinitely.
                pending.extend(self._finish(waiter))

    async def _acquire(self, *, disposal: bool) -> _NativePersistenceWaiter:
        loop = asyncio.get_running_loop()
        waiter = _NativePersistenceWaiter(loop, loop.create_future(), disposal)
        with self._lock:
            queue = self._waiting_disposals if disposal else self._waiting_readers
            queue.append(waiter)
            granted = self._grant_locked()
        self._wake(granted)
        try:
            await waiter.future
        except BaseException:
            self._wake(self._finish(waiter))
            raise
        return waiter

    @asynccontextmanager
    async def persistence(self):
        waiter = await self._acquire(disposal=False)
        try:
            yield
        finally:
            self._wake(self._finish(waiter))

    @asynccontextmanager
    async def disposal(self):
        waiter = await self._acquire(disposal=True)
        try:
            yield
        finally:
            self._wake(self._finish(waiter))


_native_persistence_gc = NativePersistenceGC()


@asynccontextmanager
async def native_persistence_lease():
    async with _native_persistence_gc.persistence():
        yield


async def release_yroom_thread_bound_state(room: YRoom) -> None:
    """Drain snapshot workers, then drop y_py on the room's original loop thread."""

    async def dispose_owned():
        async with _native_persistence_gc.disposal():
            room.on_message = None
            for client in list(room.clients):
                detach = getattr(client, "detach_room_runtime", None)
                if detach is not None:
                    detach()
            room.clients = []
            room.awareness = None  # type: ignore[assignment]
            room.ydoc = None  # type: ignore[assignment]
            gc.collect()

    disposal = asyncio.create_task(dispose_owned())
    cancelled = False
    try:
        while True:
            try:
                await asyncio.shield(disposal)
                break
            except asyncio.CancelledError:
                # Docs lacks Whiteboard's private disposal shield. Its new GC
                # admission wait still must join native ownership on host cancel.
                cancelled = True
                if disposal.cancelled():
                    raise
    finally:
        if cancelled:
            raise asyncio.CancelledError


@dataclass
class CollabRoomRuntime:
    room_key: str
    default_actor_user_id: str
    room: YRoom
    room_task: asyncio.Task[None]
    metadata: dict[str, str] = field(default_factory=dict)
    relay_task: asyncio.Task[None] | None = None
    relay_pubsub: CollabSubscription | None = None
    flush_task: asyncio.Task[None] | None = None
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_editor_user_id: str | None = None
    recent_remote_update_hashes: OrderedDict[str, None] = field(default_factory=OrderedDict)
    active_connection_count: int = 0
    active_user_connections: dict[str, int] = field(default_factory=dict)

    def remember_remote_update_hash(
        self,
        update_hash: str,
        *,
        max_size: int = REMOTE_UPDATE_HASH_CACHE_SIZE,
    ) -> None:
        self.recent_remote_update_hashes[update_hash] = None
        self.recent_remote_update_hashes.move_to_end(update_hash)
        if len(self.recent_remote_update_hashes) > max_size:
            self.recent_remote_update_hashes.popitem(last=False)

    def consume_remote_update_hash(self, update_hash: str) -> bool:
        if update_hash not in self.recent_remote_update_hashes:
            return False
        self.recent_remote_update_hashes.pop(update_hash, None)
        return True


class CollabConnectionLimitExceeded(Exception):
    def __init__(self, *, reason: str = COLLAB_CLOSE_REASON_TOO_MANY_CONNECTIONS) -> None:
        super().__init__(reason)
        self.reason = reason
        self.close_code = COLLAB_CLOSE_CODE_TOO_MANY_CONNECTIONS


class RedisCollabBus:
    def __init__(
        self,
        redis_url: str,
        *,
        instance_id: str,
        channel_prefix: str = "docs-collab",
        operation_timeout_seconds: float = 5.0,
    ) -> None:
        self._redis_url = redis_url
        self._channel_prefix = channel_prefix
        self._operation_timeout_seconds = operation_timeout_seconds
        self.instance_id = instance_id
        self._redis: redis_asyncio.Redis | None = None
        self._available = False
        self._failure_reason: str | None = None
        self._connect_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    async def startup(self) -> None:
        self._stopping = False
        await self._connect()
        if not self._available:
            self._schedule_reconnect()

    async def shutdown(self) -> None:
        self._stopping = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            await asyncio.gather(self._reconnect_task, return_exceptions=True)
            self._reconnect_task = None
        await self._close()

    async def create_pubsub(self, room_key: str) -> CollabSubscription:
        if not self._available or self._redis is None:
            raise RuntimeError("Collaboration relay is unavailable.")
        channel = self.channel_name(room_key)
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await asyncio.wait_for(
            pubsub.subscribe(channel),
            timeout=self._operation_timeout_seconds,
        )
        return pubsub

    async def publish(self, room_key: str, payload: dict[str, object]) -> None:
        if not self._available or self._redis is None:
            raise RuntimeError("Collaboration relay is unavailable.")
        await asyncio.wait_for(
            self._redis.publish(
                self.channel_name(room_key),
                json.dumps(payload).encode("utf-8"),
            ),
            timeout=self._operation_timeout_seconds,
        )

    async def close_pubsub(
        self,
        pubsub: CollabSubscription,
        room_key: str,
    ) -> None:
        redis_pubsub = cast(PubSub, pubsub)
        channel = self.channel_name(room_key)
        with suppress(Exception):
            await asyncio.wait_for(
                redis_pubsub.unsubscribe(channel),
                timeout=self._operation_timeout_seconds,
            )
        with suppress(Exception):
            await asyncio.wait_for(
                redis_pubsub.aclose(),
                timeout=self._operation_timeout_seconds,
            )

    def mark_failed(self, *, reason: str = "relay_unavailable") -> None:
        self._available = False
        self._failure_reason = reason
        self._schedule_reconnect()

    def channel_name(self, room_key: str) -> str:
        return f"{self._channel_prefix}:{room_key}"

    async def _connect(self) -> None:
        async with self._connect_lock:
            await self._close()
            if self._stopping:
                return
            redis = redis_asyncio.from_url(self._redis_url)
            try:
                await asyncio.wait_for(
                    redis.ping(),
                    timeout=self._operation_timeout_seconds,
                )
            except Exception as exc:
                logger.warning("Collaboration relay is unavailable: %s", exc)
                self._available = False
                self._failure_reason = "relay_unavailable"
                with suppress(Exception):
                    await asyncio.wait_for(
                        redis.aclose(),
                        timeout=self._operation_timeout_seconds,
                    )
                return
            self._redis = redis
            self._available = True
            self._failure_reason = None

    async def _close(self) -> None:
        self._available = False
        if self._redis is not None:
            with suppress(Exception):
                await asyncio.wait_for(
                    self._redis.aclose(),
                    timeout=self._operation_timeout_seconds,
                )
            self._redis = None

    def _schedule_reconnect(self) -> None:
        if self._stopping:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._run_reconnect_loop())

    async def _run_reconnect_loop(self) -> None:
        delay_seconds = 0.5
        try:
            while not self._stopping:
                await asyncio.sleep(delay_seconds)
                await self._connect()
                if self._available:
                    return
                delay_seconds = min(delay_seconds * 2, 5)
        except asyncio.CancelledError:
            raise


class _InProcessCollabSubscription:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def get_message(self, timeout: float = 0.0) -> dict[str, object] | None:
        try:
            if timeout > 0:
                payload = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            else:
                payload = self.queue.get_nowait()
        except (TimeoutError, asyncio.QueueEmpty):
            return None
        return {"data": payload}


class InProcessCollabBus:
    """Process-local collaboration relay for Docker-free application tests."""

    def __init__(self, *, instance_id: str) -> None:
        self.instance_id = instance_id
        self._available = False
        self._failure_reason: str | None = None
        self._subscriptions: dict[str, set[_InProcessCollabSubscription]] = {}

    @property
    def available(self) -> bool:
        return self._available

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    async def startup(self) -> None:
        self._available = True
        self._failure_reason = None

    async def shutdown(self) -> None:
        self._available = False
        self._subscriptions.clear()

    async def create_pubsub(self, room_key: str) -> CollabSubscription:
        if not self._available:
            raise RuntimeError("Collaboration relay is unavailable.")
        subscription = _InProcessCollabSubscription()
        self._subscriptions.setdefault(room_key, set()).add(subscription)
        return subscription

    async def publish(self, room_key: str, payload: dict[str, object]) -> None:
        if not self._available:
            raise RuntimeError("Collaboration relay is unavailable.")
        encoded_payload = json.dumps(payload).encode("utf-8")
        for subscription in tuple(self._subscriptions.get(room_key, ())):
            subscription.queue.put_nowait(encoded_payload)

    async def close_pubsub(
        self,
        pubsub: CollabSubscription,
        room_key: str,
    ) -> None:
        subscriptions = self._subscriptions.get(room_key)
        if subscriptions is None:
            return
        subscriptions.discard(cast(_InProcessCollabSubscription, pubsub))
        if not subscriptions:
            self._subscriptions.pop(room_key, None)

    def mark_failed(self, *, reason: str = "relay_unavailable") -> None:
        self._available = False
        self._failure_reason = reason


class UnavailableCollabBus:
    """Explicitly unavailable collaboration relay for degraded-mode tests."""

    def __init__(
        self,
        *,
        instance_id: str,
        reason: str = "relay_unavailable",
    ) -> None:
        self.instance_id = instance_id
        self._failure_reason = reason

    @property
    def available(self) -> bool:
        return False

    @property
    def failure_reason(self) -> str:
        return self._failure_reason

    async def startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def create_pubsub(self, room_key: str) -> CollabSubscription:
        del room_key
        raise RuntimeError("Collaboration relay is unavailable.")

    async def publish(self, room_key: str, payload: dict[str, object]) -> None:
        del room_key, payload
        raise RuntimeError("Collaboration relay is unavailable.")

    async def close_pubsub(
        self,
        pubsub: CollabSubscription,
        room_key: str,
    ) -> None:
        del pubsub, room_key

    def mark_failed(self, *, reason: str = "relay_unavailable") -> None:
        self._failure_reason = reason


class FastAPIYjsWebsocket:
    def __init__(
        self,
        websocket: WebSocket,
        path: str,
        room_runtime: CollabRoomRuntime,
        user_id: str,
        *,
        authorize: Callable[[], Awaitable[bool | None]],
        authorization_error_close: Callable[[HTTPException], tuple[int, str] | None] | None = None,
    ):
        self._websocket = websocket
        self._path = path
        self._room_runtime: CollabRoomRuntime | None = room_runtime
        self._user_id = user_id
        self._authorize = authorize
        self._authorization_error_close = authorization_error_close
        self._send_lock = asyncio.Lock()
        self._closed = False

    @property
    def path(self) -> str:
        return self._path

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self.recv()
        except Exception:  # pragma: no cover - ypy-websocket expects StopAsyncIteration
            self.detach_room_runtime()
            raise StopAsyncIteration() from None

    async def recv(self) -> bytes:
        if self._closed:
            raise WebSocketDisconnect(code=1008)
        message = await self._websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise RuntimeError("WebSocket disconnected.")
        payload = message.get("bytes")
        if payload is None:
            raise RuntimeError("Unexpected non-binary WebSocket frame.")
        denial = await self._authorize_frame()
        if denial is not None:
            await self.close(code=denial[0], reason=denial[1])
            raise WebSocketDisconnect(code=denial[0])
        if payload and payload[0] == YMessageType.SYNC and self._room_runtime is not None:
            self._room_runtime.last_editor_user_id = self._user_id
        return payload

    def detach_room_runtime(self) -> None:
        if self._room_runtime is not None:
            with suppress(Exception):
                self._room_runtime.room.clients.remove(self)
        self._room_runtime = None

    async def send(self, message: bytes) -> None:
        if self._closed:
            return
        async with self._send_lock:
            if self._closed:
                return
            if not self._is_connected():
                self._mark_closed()
                return
            denial = await self._authorize_frame()
            if denial is None:
                try:
                    await self._websocket.send_bytes(message)
                except (
                    ClientDisconnected,
                    WebSocketDisconnect,
                    RuntimeError,
                    AssertionError,
                ) as exc:
                    if self._is_closed_send_error(exc):
                        self._mark_closed()
                        return
                    raise
        if denial is not None:
            # close() owns the same send lock. Do not reenter it or fail the
            # YRoom broadcast task group for other, still-authorized clients.
            await self.close(code=denial[0], reason=denial[1])

    async def _authorize_frame(self) -> tuple[int, str] | None:
        # The optional callback chooses a close frame only; it must not close or
        # await anything (send calls authorization while holding its send lock).
        try:
            return (1008, "access_revoked") if await self._authorize() is False else None
        except HTTPException as exc:
            if self._authorization_error_close is not None:
                choice = self._authorization_error_close(exc)
                if choice is not None:
                    return choice
            return (1008, "access_revoked")

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        if self._closed:
            return
        async with self._send_lock:
            if self._closed:
                return
            if not self._is_connected():
                self._mark_closed()
                return
            try:
                await self._websocket.close(code=code, reason=reason)
            except (ClientDisconnected, WebSocketDisconnect, RuntimeError, AssertionError) as exc:
                if self._is_closed_send_error(exc):
                    self._mark_closed()
                    return
                raise
            self._mark_closed()

    def _mark_closed(self) -> None:
        self._closed = True
        self.detach_room_runtime()

    def _is_connected(self) -> bool:
        return (
            self._websocket.client_state == WebSocketState.CONNECTED
            and self._websocket.application_state == WebSocketState.CONNECTED
        )

    @staticmethod
    def _is_closed_send_error(exc: Exception) -> bool:
        if isinstance(exc, (AssertionError, ClientDisconnected, WebSocketDisconnect)):
            return True
        message = str(exc)
        return (
            "after sending 'websocket.close'" in message
            or 'Cannot call "send" once a close message has been sent.' in message
            or "no close frame received or sent" in message
        )
