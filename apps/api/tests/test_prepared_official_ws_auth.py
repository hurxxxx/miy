"""Inactive prepared collaboration auth; synthetic bus and genuine restricted PG."""

import asyncio
from functools import partial
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request
from starlette.websockets import WebSocketDisconnect

from miy_api import api_registry, official_auth
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.docs import router as docs
from miy_api.domains.whiteboard import router as whiteboard
from miy_api.domains.auth.dependencies import require_auth_context
from miy_api.domains.official_apps.authority_reader import OfficialAuthorityReaderRefused
from miy_api.domains.official_apps import websocket_auth


def docs_socket_app(monkeypatch):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == "miy_api.domains.docs.router" and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app = FastAPI()
    # Denial precedes room/Source ownership; no live bus or runtime is constructed.
    app.state.docs_collab = SimpleNamespace()
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=lambda: pytest.fail("reader fixture bypassed"),
        official_auth_max_concurrent_reads=1,
    )
    return app


def test_prepared_docs_socket_rejects_platform_token_before_source(monkeypatch):
    seen, source = [], []
    app = docs_socket_app(monkeypatch)

    def deny(factory, token, *, logical_app_id):
        seen.append(logical_app_id)
        raise localized_http_exception(status_code=401, code="auth.required")

    def forbidden_source():
        source.append(1)
        raise localized_http_exception(status_code=401, code="auth.required")

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", deny)
    monkeypatch.setattr(docs, "get_session_factory", forbidden_source)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                "/api/v1/docs/collab/pages/native_doc__synthetic/ws"
            ) as socket:
                socket.send_json({"type": "auth", "token": "ordinary-platform-token"})
                socket.receive_bytes()
    assert caught.value.code == 4401
    assert source == []
    assert seen == ["docs"]


def socket_app(monkeypatch, *, logical_app_id, factory=lambda: None, prepared=True, hub=None):
    module = docs if logical_app_id == "docs" else whiteboard
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == module.__name__ and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app = FastAPI()
    setattr(
        app.state,
        "docs_collab" if logical_app_id == "docs" else "whiteboard_collab",
        hub or SimpleNamespace(),
    )
    options = (
        dict(official_auth_session_factory=factory, official_auth_max_concurrent_reads=1)
        if prepared
        else {}
    )
    api_registry.register_api_routers(app, get_settings(), composition="official", **options)
    if prepared:
        assert (
            app.state.prepared_official_auth_dependency
            is app.dependency_overrides[require_auth_context]
        )
    return app


def socket_path(logical_app_id, resource="synthetic"):
    return (
        f"/api/v1/docs/collab/pages/native_doc_page__{resource}/ws"
        if logical_app_id == "docs"
        else f"/api/v1/whiteboard/collab/items/{resource}/ws"
    )


def socket_connection(app):
    async def receive():
        pytest.fail("Authority callback unexpectedly consumed transport input")

    async def send(message):
        pytest.fail("Authority callback unexpectedly wrote transport output")

    return WebSocket(
        {"type": "websocket", "app": app, "state": {}, "headers": []},
        receive=receive,
        send=send,
    )


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
@pytest.mark.parametrize(
    "error,code",
    [
        (OfficialAuthorityReaderRefused("private SQL detail"), 1013),
        (SQLAlchemyError("private SQL detail"), 1013),
        (HTTPException(status_code=401, detail="current denial"), 4401),
        (HTTPException(status_code=403, detail="current denial"), 4403),
    ],
)
def test_prepared_handshake_denial_never_allocates_source_or_falls_back(
    monkeypatch, logical_app_id, error, code
):
    module = docs if logical_app_id == "docs" else whiteboard
    app = socket_app(monkeypatch, logical_app_id=logical_app_id)
    scopes = []

    def denied(*args, logical_app_id, **kwargs):
        scopes.append(logical_app_id)
        raise error

    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", denied)
    monkeypatch.setattr(module, "get_session_factory", lambda: pytest.fail("Source allocated"))
    monkeypatch.setattr(
        module, "resolve_auth_context_from_token", lambda *a, **k: pytest.fail("legacy fallback")
    )
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                socket_path(logical_app_id) + "?logical_app_id=pms", headers={"X-MIY-App-Id": "pms"}
            ) as socket:
                socket.send_json({"type": "auth", "token": "synthetic", "logical_app_id": "pms"})
                socket.receive_bytes()
    assert caught.value.code == code and scopes == [logical_app_id]
    if code == 1013:
        assert caught.value.reason == "official_authority_unavailable"
        assert "private" not in caught.value.reason


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_query_credential_is_refused_before_prepared_or_source(monkeypatch, logical_app_id):
    module = docs if logical_app_id == "docs" else whiteboard
    app = socket_app(
        monkeypatch, logical_app_id=logical_app_id, factory=lambda: pytest.fail("auth allocation")
    )
    monkeypatch.setattr(module, "get_session_factory", lambda: pytest.fail("Source allocation"))
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                socket_path(logical_app_id) + "?token=synthetic"
            ) as socket:
                socket.receive_bytes()
    assert caught.value.code == 4401


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_unprepared_assembly_keeps_existing_platform_session_reader(monkeypatch, logical_app_id):
    from sqlalchemy.orm import Session

    module = docs if logical_app_id == "docs" else whiteboard
    app = socket_app(monkeypatch, logical_app_id=logical_app_id, prepared=False)
    calls = []
    monkeypatch.setattr(module, "get_session_factory", lambda: Session)

    def denied(db, token):
        calls.append(token)
        raise localized_http_exception(status_code=401, code="auth.required")

    monkeypatch.setattr(module, "resolve_auth_context_from_token", denied)
    monkeypatch.setattr(
        official_auth,
        "resolve_prepared_official_auth_context",
        lambda *a, **k: pytest.fail("default assembly changed"),
    )
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(socket_path(logical_app_id)) as socket:
                socket.send_json({"type": "auth", "token": "ordinary"})
                socket.receive_bytes()
    assert caught.value.code == 4401 and calls == ["ordinary"]


def test_http_and_ws_share_budget_and_cancelled_ws_waiter_allocates_no_session(monkeypatch):
    started, release = Event(), Event()
    calls = []
    context = SimpleNamespace(user=SimpleNamespace(id="member"))

    def resolve(factory, token, *, logical_app_id):
        calls.append(logical_app_id)
        started.set()
        assert release.wait(3)
        return context

    app = socket_app(monkeypatch, logical_app_id="docs")
    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", resolve)
    dependency = app.dependency_overrides[require_auth_context]
    request = Request(
        {"type": "http", "app": app, "state": {"official_logical_app_id": "docs"}, "headers": []}
    )
    websocket = socket_connection(app)
    scope, done = [], Event()

    async def queued():
        with anyio.CancelScope() as cancel:
            scope.append(cancel)
            await websocket_auth.resolve_prepared_official_ws_auth_context(
                websocket, token="synthetic", logical_app_id="whiteboard"
            )
        done.set()

    async def scenario():
        with anyio.fail_after(3):
            async with anyio.create_task_group() as tasks:
                try:
                    tasks.start_soon(
                        dependency,
                        request,
                        HTTPAuthorizationCredentials(scheme="Bearer", credentials="synthetic"),
                    )
                    while not started.is_set():
                        await anyio.sleep(0)
                    tasks.start_soon(queued)
                    while not scope:
                        await anyio.sleep(0)
                    scope[0].cancel()
                    while not done.is_set():
                        await anyio.sleep(0)
                    assert calls == ["docs"]
                finally:
                    release.set()
            assert (
                await websocket_auth.resolve_prepared_official_ws_auth_context(
                    websocket, token="synthetic", logical_app_id="whiteboard"
                )
                is context
            )

    anyio.run(scenario)
    assert calls == ["docs", "whiteboard"]


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_repeated_monitor_cancel_joins_reader_before_shared_permit_release(
    monkeypatch, logical_app_id
):
    module = docs if logical_app_id == "docs" else whiteboard
    started, release, finished = Event(), Event(), Event()
    calls, source = [], []
    context = SimpleNamespace(user=SimpleNamespace(id="member"))

    def resolve(factory, token, *, logical_app_id):
        calls.append(logical_app_id)
        if len(calls) == 1:
            started.set()
            try:
                assert release.wait(3)
            finally:
                finished.set()
        return context

    app = socket_app(monkeypatch, logical_app_id=logical_app_id)
    monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", resolve)
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(collab_acl_recheck_seconds=0.001)
    )
    websocket = socket_connection(app)

    def forbidden_source(**kwargs):
        source.append(1)
        pytest.fail("Cancelled authority lookup proceeded to Source")

    if logical_app_id == "docs":
        monkeypatch.setattr(docs, "_require_prepared_collab_source_access", forbidden_source)
        authorize = partial(
            docs._authorize_prepared_collab_access,
            websocket,
            page_ref="synthetic",
            token="synthetic",
            user_id="member",
            writer_identity=None,
        )
        monitor = partial(
            docs._monitor_collab_access,
            websocket,
            page_ref="synthetic",
            token="synthetic",
            hub=SimpleNamespace(),
            runtime=None,
            authorize=authorize,
        )
    else:
        monkeypatch.setattr(
            whiteboard, "_require_prepared_whiteboard_source_access", forbidden_source
        )
        authorize = partial(
            whiteboard._authorize_prepared_whiteboard_collab_access,
            websocket,
            item_id="synthetic",
            token="synthetic",
            user_id="member",
        )
        monitor = partial(
            whiteboard._monitor_whiteboard_collab_access,
            websocket,
            item_id="synthetic",
            token="synthetic",
            authorize=authorize,
        )

    async def scenario():
        with anyio.fail_after(3):
            task = asyncio.create_task(monitor())
            waiter = None
            try:
                while not started.is_set():
                    await anyio.sleep(0)
                task.cancel()
                await anyio.sleep(0.01)
                task.cancel()
                waiter = asyncio.create_task(
                    websocket_auth.resolve_prepared_official_ws_auth_context(
                        websocket, token="synthetic", logical_app_id=logical_app_id
                    )
                )
                await anyio.sleep(0.02)
                assert not task.done() and not waiter.done() and calls == [logical_app_id]
                assert not finished.is_set() and source == []
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
                if waiter is not None:
                    assert await waiter is context
            assert task.cancelled() and finished.is_set()

    anyio.run(scenario)
    assert calls == [logical_app_id, logical_app_id] and source == []


# Genuine migrated authority14/87 and Source ACL; room/bus are synthetic below.
from test_prepared_official_http_auth import http_world as http_world  # noqa: E402
from test_official_authority_reader import (  # noqa: E402
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)


class SyntheticRoom:
    """Exercise the real Yjs transport callbacks, without a codec, bus or persistence."""

    def __init__(self):
        self.clients = []
        self.effects = []
        self.after_receive = None

    async def serve(self, websocket):
        self.clients.append(websocket)
        await websocket.send(b"ready")
        try:
            while True:
                payload = await websocket.recv()
                self.effects.append(payload)
                if self.after_receive is not None:
                    self.after_receive()
                await websocket.send(b"echo:" + payload)
        except (WebSocketDisconnect, RuntimeError):
            return


class SyntheticHub:
    relay_available = True

    def __init__(self, writer_identity):
        self.writer_identity = writer_identity
        self.room = SyntheticRoom()
        self.runtime = SimpleNamespace(room=self.room, last_editor_user_id=None)
        self.acquired, self.released, self.cleaned, self.fenced = [], [], [], []

    async def get_room(self, context, state):
        return self.runtime

    async def acquire_connection_slot(self, runtime, user_id):
        self.acquired.append(user_id)

    async def release_connection_slot(self, runtime, user_id):
        self.released.append(user_id)

    async def cleanup_room(self, room_key, **kwargs):
        self.cleaned.append(room_key)

    def fence_runtime(self, runtime):
        self.fenced.append(runtime)


@pytest.fixture
def ws_world(http_world):
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.docs.collab import PAGE_SOURCE_NATIVE_DOC, make_room_key
    from miy_api.domains.docs.models import DocsCollabDocument, NativeDocPage
    from miy_api.domains.official_apps.writer import WriterIdentity
    from miy_api.domains.official_apps.writer_models import RuntimeOwnership
    from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE

    world = http_world
    with world.core() as db:
        page = NativeDocPage(
            id=new_id(),
            doc_id=world.ids["owned"],
            created_by_id=world.state["member_id"],
            title="Synthetic WS page",
            content_format="block",
            content_blocks=[],
        )
        db.add(page)
        db.flush()
        # Persisted synthetic Yjs state avoids invoking the unrelated real codec.
        db.add(
            DocsCollabDocument(
                id=new_id(),
                room_key=make_room_key(PAGE_SOURCE_NATIVE_DOC, page.id),
                source_type=PAGE_SOURCE_NATIVE_DOC,
                source_page_id=page.id,
                snapshot_content_blocks=[],
                yjs_state=b"\x00\x00",
            )
        )
        ownership = db.get(RuntimeOwnership, SUITE_SCOPE)
        assert ownership is not None and ownership.state == "active"
        world.writer = WriterIdentity(
            ownership.scope, ownership.active_owner, ownership.generation, ownership.artifact
        )
        db.commit()
        world.ids["ws_page"] = page.id
    return world


def native_socket_app(monkeypatch, world, logical_app_id, *, factory=None, after_lookup=None):
    module = docs if logical_app_id == "docs" else whiteboard
    hub = SyntheticHub(world.writer)
    app = socket_app(
        monkeypatch,
        logical_app_id=logical_app_id,
        factory=world.factory if factory is None else factory,
        hub=hub,
    )

    def source():
        world.source_calls.append("Source")
        return world.core

    monkeypatch.setattr(module, "get_session_factory", source)
    monkeypatch.setattr(
        module,
        "resolve_auth_context_from_token",
        lambda *a, **k: pytest.fail("prepared WS used platform token resolver"),
    )
    if after_lookup is not None:
        original = official_auth.resolve_prepared_official_auth_context

        def coordinated(*args, **kwargs):
            context = original(*args, **kwargs)
            after_lookup()
            return context

        monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", coordinated)
    return app, hub


def native_path(world, logical_app_id):
    return socket_path(
        logical_app_id, world.ids["ws_page" if logical_app_id == "docs" else "board"]
    )


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_genuine_prepared_socket_reads_auth_role_and_rechecks_before_recv_and_send(
    ws_world, monkeypatch, logical_app_id
):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, logical_app_id)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"synthetic update")
            assert socket.receive_bytes() == b"echo:synthetic update"
    assert hub.room.effects == [b"synthetic update"]
    assert len(world.source_calls) == 4  # init, first send, recv, response send
    assert world.auth_commands and set(world.auth_commands) <= {"SELECT", "SHOW", "SET"}
    assert hub.acquired == hub.released == [world.state["member_id"]] and hub.cleaned


def revoke(world, kind, logical_app_id):
    from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
    from miy_api.domains.auth.security import hash_token
    from miy_api.domains.independent_apps.models import AppSession
    from miy_api.domains.official_apps.models import OfficialAppBinding

    with world.core() as db:
        if kind == "source":
            db.get(AuthSession, world.state["source_id"]).revoked_at = utcnow_naive()
        elif kind == "delegated":
            db.get(AppSession, hash_token(world.token)).revoked_at = utcnow_naive()
        elif kind == "binding":
            db.get(OfficialAppBinding, world.ids["binding"]).revoked_at = utcnow_naive()
        elif kind == "app":
            db.get(CompanyAppControl, logical_app_id).enabled = False
        else:
            db.get(User, world.state["member_id"]).status = "inactive"
        db.commit()


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
@pytest.mark.parametrize("kind", ["source", "delegated", "binding", "app", "user"])
def test_genuine_current_revocation_blocks_next_receive_before_room_effect(
    ws_world, monkeypatch, logical_app_id, kind
):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, logical_app_id)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            world.source_calls.clear()
            revoke(world, kind, logical_app_id)
            socket.send_bytes(b"forbidden update")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert caught.value.code == 1008
    assert hub.room.effects == [] and world.source_calls == []
    assert hub.acquired == hub.released and not hub.fenced


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_genuine_revocation_between_recv_and_send_blocks_outgoing_content(
    ws_world, monkeypatch, logical_app_id
):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    hub.room.after_receive = lambda: revoke(world, "source", logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, logical_app_id)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"authorized incoming update")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert caught.value.code == 1008
    assert hub.room.effects == [b"authorized incoming update"]
    assert hub.acquired == hub.released


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_genuine_broad_auth_profile_refuses_before_source(ws_world, monkeypatch, logical_app_id):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id, factory=world.core)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(native_path(world, logical_app_id)) as socket:
                socket.send_json({"type": "auth", "token": world.token})
                socket.receive_bytes()
    assert caught.value.code == 1013 and caught.value.reason == "official_authority_unavailable"
    assert not world.source_calls and not hub.acquired and not hub.room.effects


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_genuine_platform_login_is_not_a_delegated_ws_credential(
    ws_world, monkeypatch, logical_app_id
):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(native_path(world, logical_app_id)) as socket:
                socket.send_json({"type": "auth", "token": world.state["login_token"]})
                socket.receive_bytes()
    assert caught.value.code == 4401 and not world.source_calls and not hub.acquired


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_transient_reader_failure_after_connect_holds_private_without_room_fence(
    ws_world, monkeypatch, logical_app_id
):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, logical_app_id)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            world.source_calls.clear()

            def fail(*args, **kwargs):
                raise OfficialAuthorityReaderRefused("private internal detail")

            monkeypatch.setattr(official_auth, "resolve_prepared_official_auth_context", fail)
            socket.send_bytes(b"held update")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert (
                caught.value.code == 1013
                and caught.value.reason == "official_authority_unavailable"
            )
    assert not world.source_calls and not hub.room.effects and not hub.fenced
    assert hub.acquired == hub.released


def test_genuine_read_share_cannot_open_edit_room(ws_world, monkeypatch):
    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, "docs")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(socket_path("docs", world.ids["page"])) as socket:
                socket.send_json({"type": "auth", "token": world.token})
                socket.receive_bytes()
    assert caught.value.code == 4403 and not hub.acquired and not hub.room.effects


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
@pytest.mark.parametrize("direction", ["recv", "send"])
def test_genuine_source_edit_share_revoke_blocks_open_socket_before_content(
    ws_world, monkeypatch, logical_app_id, direction
):
    from miy_api.domains.auth.security import new_id
    from miy_api.domains.docs.models import NativeDocUserShare
    from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardUserShare

    world = ws_world
    with world.core() as db:
        if logical_app_id == "docs":
            share_model, share_id = NativeDocUserShare, world.ids["share"]
            db.get(share_model, share_id).access_level = "edit"
            resource = world.ids["page"]
        else:
            owner_id = world.state["admin"]["user"]["id"]
            board = Whiteboard(id=new_id(), owner_id=owner_id, title="Shared synthetic board")
            db.add(board)
            db.flush()
            share = WhiteboardUserShare(
                id=new_id(),
                whiteboard_id=board.id,
                user_id=world.state["member_id"],
                created_by_id=owner_id,
                access_level="edit",
            )
            db.add(share)
            share_model, share_id, resource = WhiteboardUserShare, share.id, board.id
        db.commit()

    def revoke_share():
        with world.core() as db:
            db.get(share_model, share_id).access_level = "read"
            db.commit()

    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(socket_path(logical_app_id, resource)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            world.source_calls.clear()
            if direction == "recv":
                revoke_share()
            else:
                hub.room.after_receive = revoke_share
            socket.send_bytes(b"synthetic update")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert caught.value.code == 1008
    assert hub.room.effects == ([] if direction == "recv" else [b"synthetic update"])
    assert len(world.source_calls) == (1 if direction == "recv" else 2)
    assert hub.acquired == hub.released and not hub.fenced


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_current_source_app_revocation_after_prepared_lookup_denies_initialization(
    ws_world, monkeypatch, logical_app_id
):
    world = ws_world
    app, hub = native_socket_app(
        monkeypatch,
        world,
        logical_app_id,
        after_lookup=lambda: revoke(world, "app", logical_app_id),
    )
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(native_path(world, logical_app_id)) as socket:
                socket.send_json({"type": "auth", "token": world.token})
                socket.receive_bytes()
    assert caught.value.code == 4403 and world.source_calls and not hub.acquired


@pytest.mark.parametrize("logical_app_id", ["docs", "whiteboard"])
def test_idle_monitor_rechecks_real_revocation_without_frame(ws_world, monkeypatch, logical_app_id):
    world = ws_world
    module = docs if logical_app_id == "docs" else whiteboard
    monkeypatch.setattr(
        module, "get_settings", lambda: SimpleNamespace(collab_acl_recheck_seconds=0.02)
    )
    app, hub = native_socket_app(monkeypatch, world, logical_app_id)
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, logical_app_id)) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            revoke(world, "delegated", logical_app_id)
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert caught.value.code == 4401
    assert not hub.room.effects and hub.acquired == hub.released


def test_docs_current_writer_fence_survives_prepared_frame_auth(ws_world, monkeypatch):
    from uuid import uuid4
    from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
    from miy_api.domains.official_apps.writer import transition

    world = ws_world
    app, hub = native_socket_app(monkeypatch, world, "docs")
    with TestClient(app) as client:
        with client.websocket_connect(native_path(world, "docs")) as socket:
            socket.send_json({"type": "auth", "token": world.token})
            assert socket.receive_bytes() == b"ready"
            with world.core() as db:
                context = resolve_auth_context_from_token(
                    db, world.state["admin"]["token"], update_last_seen=False
                )
                transition(
                    db,
                    context,
                    request_id=uuid4(),
                    expected=world.writer,
                    expected_state="active",
                    owner="legacy",
                    state="draining",
                    artifact=None,
                    reason="Synthetic writer drain",
                )
                db.commit()
            socket.send_bytes(b"forbidden during drain")
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_bytes()
            assert (
                caught.value.code == 1013 and caught.value.reason == "official_writer_unavailable"
            )
    assert not hub.room.effects and hub.fenced == [hub.runtime]
