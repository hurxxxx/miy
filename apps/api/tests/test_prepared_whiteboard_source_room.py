"""Prepared existing Whiteboard room reads; no Source writes or hub cutover."""

from datetime import datetime, timedelta
import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from starlette.websockets import WebSocketDisconnect

from miy_api import api_registry
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import CompanyAppControl, User, utcnow_naive
from miy_api.domains.whiteboard import collab_source_room as room
from miy_api.domains.whiteboard import router as whiteboard
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
from test_prepared_whiteboard_source_access import (
    Marker as Marker,
    MarkerBase as MarkerBase,
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    context as context,
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
    shared as shared,
    source_world as source_world,  # noqa: F401
)
from test_prepared_official_ws_auth import (
    SyntheticHub as SyntheticHub,
    socket_connection as socket_connection,
)


def row_for(*, yjs=None):
    scene, snapshot = json.dumps({"elements": [], "appState": {}, "files": {}}), "{}"
    return dict(
        board_id="unit",
        owner_id="owner",
        board_updated_at=datetime(2026, 10, 8),
        trashed_at=None,
        collab_id="collab",
        collab_board_id="unit",
        room_key="whiteboard:unit",
        collab_updated_at=datetime(2026, 10, 8),
        scene_text=scene,
        snapshot_text=snapshot,
        yjs_state=yjs,
        body_bytes=len(scene.encode()) + len(snapshot.encode()) + len(yjs or b""),
    )


def assembly():
    app = FastAPI()
    context = SimpleNamespace(user=User(id="member"), session=SimpleNamespace(id="source-session"))

    async def dependency(*args):
        return context

    async def acl(**kwargs):
        return None

    async def load(**kwargs):
        return room._room_state(row_for(), item_id="unit")

    app.state.prepared_official_auth_dependency = dependency
    app.state.prepared_whiteboard_source_access = acl
    app.state.prepared_whiteboard_room_loader = load
    app.state.prepared_whiteboard_room_configured = True
    return app, context, dependency, acl, load


def socket_app(c, monkeypatch):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == whiteboard.__name__ and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app, hub = FastAPI(), SyntheticHub(None)
    app.state.whiteboard_collab = hub
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=c.world.factory,
        official_auth_max_concurrent_reads=1,
        official_whiteboard_source_session_factory=c.factory,
        official_whiteboard_source_max_concurrent_reads=1,
        official_whiteboard_room_session_factory=c.factory,
        official_whiteboard_room_max_concurrent_reads=1,
    )
    monkeypatch.setattr(
        whiteboard, "get_session_factory", lambda: pytest.fail("global initial factory")
    )
    return app, hub


# Actual PostgreSQL is run only in Root's owned, migrated isolated fixtures.
@pytest.fixture
def room_world(source_world):
    c = source_world
    c.world.core_sql(
        sql.SQL("GRANT SELECT (scene, updated_at) ON public.whiteboards TO {}").format(c.role)
    )
    c.world.core_sql(
        sql.SQL(
            "GRANT SELECT (id, whiteboard_id, room_key, yjs_state, snapshot_scene, updated_at) ON public.whiteboard_collab_documents TO {}"
        ).format(c.role)
    )
    with c.world.core() as db:
        board = db.get(Whiteboard, c.world.ids["board"])
        collab = WhiteboardCollabDocument(
            id="synthetic-room-record",
            whiteboard_id=board.id,
            room_key="whiteboard:" + board.id,
            snapshot_scene=board.scene,
            updated_at=board.updated_at + timedelta(seconds=1),
        )
        db.add(collab)
        db.commit()
    c.collab_id = "synthetic-room-record"
    return c


def invoke(c):
    return room.load_prepared_whiteboard_room_state(
        c.factory, item_id=c.world.ids["board"], user=context(c).user
    )


def test_genuine_room_state_and_socket_use_read_only_columns_without_global_initial_factory(
    room_world, monkeypatch
):
    c = room_world
    commands = []
    event.listen(
        c.engine,
        "before_cursor_execute",
        lambda conn, cur, statement, *args: commands.append(statement.lstrip().split()[0].upper()),
    )
    state = invoke(c)
    assert state.yjs_state is None and state.context.whiteboard_id == c.world.ids["board"]
    shared(c)
    # Owner reassignment advanced board.updated_at; retain a current valid row.
    with c.world.core() as db:
        db.get(WhiteboardCollabDocument, c.collab_id).updated_at = db.get(
            Whiteboard, c.world.ids["board"]
        ).updated_at + timedelta(seconds=1)
        db.commit()
    app, hub = socket_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/whiteboard/collab/items/{c.world.ids['board']}/ws"
        ) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            initial_message = socket.receive()
            close_code = initial_message.get("code")
            public_code = close_code if type(close_code) is int else None
            ready_received = (
                initial_message.get("type") == "websocket.send"
                and initial_message.get("bytes") == b"ready"
            )
            assert ready_received, f"initial_room_close_code={public_code}"
            socket.send_bytes(b"synthetic update")
            assert socket.receive_bytes() == b"echo:synthetic update"
    assert hub.room.effects == [b"synthetic update"]
    assert set(commands) <= {"SELECT", "SHOW", "SET"}

    # The same native profile may read its declared data, but cannot expand authority.
    with room_world.engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(text("SELECT token_hash FROM public.auth_sessions"))
        assert denied.value.orig.sqlstate == "42501"
    with room_world.engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(
                text("UPDATE public.whiteboard_collab_documents SET yjs_state=NULL WHERE false")
            )
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("deny", ["read_share", "app"])
def test_genuine_current_app_and_edit_acl_deny_before_any_room_body_query(room_world, deny):
    c = room_world
    user = context(c).user
    if deny == "read_share":
        shared(c, level="read")
    else:
        with c.world.core() as db:
            db.get(CompanyAppControl, "whiteboard").enabled = False
            db.commit()
    paired = []

    def observed(connection, cursor, statement, *args):
        if "LEFT OUTER JOIN whiteboard_collab_documents" in statement:
            paired.append(1)

    event.listen(c.engine, "before_cursor_execute", observed)
    try:
        with pytest.raises(HTTPException) as caught:
            room.load_prepared_whiteboard_room_state(
                c.factory, item_id=c.world.ids["board"], user=user
            )
        assert caught.value.status_code == 403
        assert paired == []
    finally:
        event.remove(c.engine, "before_cursor_execute", observed)


def test_genuine_final_acl_does_not_reuse_first_orm_identity(room_world, monkeypatch):
    c = room_world
    shared(c)
    with c.world.core() as db:
        collab = db.get(WhiteboardCollabDocument, c.collab_id)
        collab.updated_at = db.get(Whiteboard, c.world.ids["board"]).updated_at + timedelta(
            seconds=1
        )
        db.commit()
    original = room._room_state

    def change_after_pair(row, **kwargs):
        result = original(row, **kwargs)
        with c.world.core() as db:
            db.get(Whiteboard, c.world.ids["board"]).trashed_at = utcnow_naive()
            db.commit()
        return result

    monkeypatch.setattr(room, "_room_state", change_after_pair)
    with pytest.raises(HTTPException) as caught:
        invoke(c)
    assert caught.value.status_code == 404


@pytest.mark.parametrize("missing", ["prepared_whiteboard_room_loader"])
def test_genuine_configured_initial_missing_option_never_falls_back(
    room_world, monkeypatch, missing
):
    c = room_world
    app, hub = socket_app(c, monkeypatch)
    setattr(app.state, missing, None)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(
                f"/api/v1/whiteboard/collab/items/{c.world.ids['board']}/ws"
            ) as socket:
                socket.send_json({"type": "auth", "token": c.world.token})
                socket.receive_bytes()
        assert caught.value.code == 1013
    assert hub.room.effects == []
    assert hub.acquired == [] and hub.released == []
