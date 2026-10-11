"""Inactive prepared collaboration auth; synthetic bus and genuine restricted PG."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_official_authority_reader import authority as authority
from test_official_authority_reader import bound_official as bound_official
from test_official_authority_reader import client as client
from test_official_authority_reader import isolated_data_cluster as isolated_data_cluster
from test_official_authority_reader import role_template as role_template
from test_prepared_official_http_auth import http_world as http_world

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import require_auth_context
from miy_api.domains.docs import router as docs
from miy_api.domains.whiteboard import router as whiteboard


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


# Genuine current authority reader and Source ACL; room/bus are synthetic below.


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
    from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
    from miy_api.domains.official_apps.writer_models import RuntimeOwnership

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


@pytest.mark.parametrize("logical_app_id", ["docs"])
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


@pytest.mark.parametrize("logical_app_id", ["whiteboard"])
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
