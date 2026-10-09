"""Real collaboration router cleanup with synthetic sessions, rooms and transport."""

import asyncio
from types import SimpleNamespace

import anyio
import pytest

from miy_api.domains.docs import router as docs
from miy_api.domains.whiteboard import router as whiteboard


def route_case(monkeypatch, logical_app_id, *, blocked_stage=None, failure_stage=None):
    module = docs if logical_app_id == "docs" else whiteboard
    trace = []
    entered = {
        name: anyio.Event()
        for name in ("serve", "monitor_started", "monitor", "release", "cleanup")
    }
    gates = {name: anyio.Event() for name in ("monitor", "release", "cleanup")}
    leave = anyio.Event()
    monitors = []
    failure = RuntimeError("synthetic cleanup failure")
    context = SimpleNamespace(
        room_key="synthetic-cleanup-room",
        whiteboard_id="synthetic-board",
        can_edit=True,
        source_type="native_doc",
        source_page_id="synthetic-page",
        content_blocks=[],
    )
    collab = SimpleNamespace(yjs_state=None)

    class Clients(list):
        def remove(self, client):
            super().remove(client)
            trace.append("detach")

    class Room:
        clients = Clients()

        async def serve(self, socket):
            self.clients.append(socket)
            entered["serve"].set()
            await leave.wait()

    runtime = SimpleNamespace(room=Room(), last_editor_user_id=None)

    class Hub:
        relay_available = True
        writer_identity = object()

        async def get_room(self, selected_context, state):
            assert selected_context is context and state is None
            return runtime

        async def acquire_connection_slot(self, selected_runtime, user_id):
            assert selected_runtime is runtime and user_id == "synthetic-actor"

        async def release_connection_slot(self, selected_runtime, user_id):
            assert selected_runtime is runtime and user_id == "synthetic-actor"
            entered["release"].set()
            if blocked_stage == "release":
                await gates["release"].wait()
            if failure_stage == "release":
                raise failure
            trace.append("release")

        async def cleanup_room(self, room_key, *, expected_runtime):
            assert room_key == context.room_key and expected_runtime is runtime
            entered["cleanup"].set()
            if blocked_stage == "cleanup":
                await gates["cleanup"].wait()
            if failure_stage == "cleanup":
                raise failure
            trace.append("cleanup")

    async def monitor(*args, **kwargs):
        monitors.append(asyncio.current_task())
        entered["monitor_started"].set()
        try:
            await anyio.sleep_forever()
        finally:
            entered["monitor"].set()
            with anyio.CancelScope(shield=True):
                if blocked_stage == "monitor":
                    await gates["monitor"].wait()
                trace.append("monitor_joined")

    async def accept():
        return None

    async def token(*args, **kwargs):
        return "synthetic-credential"

    async def prepared(*args, **kwargs):
        return None

    hub = Hub()
    socket = SimpleNamespace(
        accept=accept,
        app=SimpleNamespace(
            state=SimpleNamespace(
                docs_collab=hub,
                whiteboard_collab=hub,
            )
        ),
    )
    session = SimpleNamespace(commit=lambda: None, close=lambda: None)
    monkeypatch.setattr(module, "_resolve_collab_ws_token", token)
    monkeypatch.setattr(module, "resolve_prepared_official_ws_auth_context", prepared)
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(
        module,
        "resolve_auth_context_from_token",
        lambda *args: SimpleNamespace(user=SimpleNamespace(id="synthetic-actor")),
    )
    if logical_app_id == "docs":
        monkeypatch.setattr(docs, "resolve_collab_page_context", lambda *args: context)
        monkeypatch.setattr(docs, "require_active_writer", lambda *args: None)
        monkeypatch.setattr(docs, "bind_transaction", lambda *args: None)
        monkeypatch.setattr(docs, "ensure_collab_document_state", lambda *args, **kwargs: collab)
        monkeypatch.setattr(docs, "_monitor_collab_access", monitor)

        async def invoke():
            await docs.docs_collab_websocket(socket, "synthetic-page")
    else:
        monkeypatch.setattr(whiteboard, "_require_collab_app_access", lambda *args: None)
        monkeypatch.setattr(
            whiteboard, "_ensure_whiteboard_collab_context", lambda *args: (context, collab)
        )
        monkeypatch.setattr(whiteboard, "_monitor_whiteboard_collab_access", monitor)

        async def invoke():
            await whiteboard.whiteboard_collab_websocket(socket, "synthetic-board")

    return SimpleNamespace(
        invoke=invoke,
        trace=trace,
        entered=entered,
        gates=gates,
        leave=leave,
        monitors=monitors,
        runtime=runtime,
        failure=failure,
    )


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
@pytest.mark.parametrize("blocked_stage", ["monitor", "release", "cleanup"])
@pytest.mark.parametrize("cancellation", ["anyio_scope", "repeated_host"])
def test_route_cancellation_joins_owned_cleanup_at_every_wait(
    monkeypatch, logical_app_id, blocked_stage, cancellation
):
    async def scenario():
        with anyio.fail_after(3):
            case = route_case(monkeypatch, logical_app_id, blocked_stage=blocked_stage)
            scope_ready = anyio.Event()
            scopes = []

            async def caller():
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    scope_ready.set()
                    await case.invoke()

            task = asyncio.create_task(caller())
            try:
                await scope_ready.wait()
                await case.entered["serve"].wait()
                await case.entered["monitor_started"].wait()
                assert len(case.monitors) == 1
                if blocked_stage == "monitor":
                    if cancellation == "anyio_scope":
                        scopes[0].cancel()
                    else:
                        task.cancel()
                else:
                    case.leave.set()
                await case.entered[blocked_stage].wait()
                if cancellation == "anyio_scope":
                    scopes[0].cancel()
                    await anyio.lowlevel.checkpoint()
                    scopes[0].cancel()
                else:
                    task.cancel()
                    await anyio.lowlevel.checkpoint()
                    task.cancel()
            finally:
                case.leave.set()
                for gate in case.gates.values():
                    gate.set()
                result = await asyncio.gather(task, *case.monitors, return_exceptions=True)
            assert case.trace == ["detach", "monitor_joined", "release", "cleanup"]
            assert case.runtime.room.clients == []
            if cancellation == "repeated_host":
                assert isinstance(result[0], asyncio.CancelledError)
            else:
                assert result[0] is None
            assert all(monitor.done() for monitor in case.monitors)

    anyio.run(scenario)


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
@pytest.mark.parametrize("failure_stage", ["release", "cleanup"])
def test_owned_cleanup_failure_preserves_original_exception_without_group(
    monkeypatch, logical_app_id, failure_stage
):
    async def scenario():
        with anyio.fail_after(3):
            case = route_case(monkeypatch, logical_app_id, failure_stage=failure_stage)
            task = asyncio.create_task(case.invoke())
            try:
                await case.entered["serve"].wait()
                await case.entered["monitor_started"].wait()
                assert len(case.monitors) == 1
            finally:
                case.leave.set()
                result = await asyncio.gather(task, *case.monitors, return_exceptions=True)
            assert result[0] is case.failure
            assert case.trace[:2] == ["detach", "monitor_joined"]
            assert ("release" in case.trace) == (failure_stage == "cleanup")
            assert "cleanup" not in case.trace
            assert case.runtime.room.clients == []

    anyio.run(scenario)
