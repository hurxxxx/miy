"""Prepared existing Whiteboard room reads; no Source writes or hub cutover."""

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
import json
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.whiteboard import collab_source_access as access
from miy_api.domains.whiteboard import collab_source_room as room
from miy_api.domains.whiteboard import router as whiteboard
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
from test_prepared_whiteboard_source_access import (
    Marker,
    MarkerBase,
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    context,
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
    shared,
    source_world as source_world,  # noqa: F401
)
from test_prepared_official_ws_auth import SyntheticHub, socket_connection


def test_explicit_room_loader_requires_prepared_server_assembly(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())

    def create_session():
        return None

    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=create_session,
        official_auth_max_concurrent_reads=1,
        official_whiteboard_source_session_factory=create_session,
        official_whiteboard_source_max_concurrent_reads=1,
        official_whiteboard_room_session_factory=create_session,
        official_whiteboard_room_max_concurrent_reads=1,
    )
    assert callable(app.state.prepared_whiteboard_room_loader)
    assert callable(app.state.prepared_whiteboard_source_access)
    assert callable(app.state.prepared_official_auth_dependency)
    assert app.state.prepared_whiteboard_room_configured is True


@pytest.mark.parametrize("missing", ["auth", "source", "room_factory", "room_budget"])
def test_partial_room_assembly_refuses_before_mutating_app_state(monkeypatch, missing):
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    options = dict(
        official_auth_session_factory=lambda: None,
        official_auth_max_concurrent_reads=1,
        official_whiteboard_source_session_factory=lambda: None,
        official_whiteboard_source_max_concurrent_reads=1,
        official_whiteboard_room_session_factory=lambda: None,
        official_whiteboard_room_max_concurrent_reads=1,
    )
    names = {
        "auth": ("official_auth_session_factory", "official_auth_max_concurrent_reads"),
        "source": (
            "official_whiteboard_source_session_factory",
            "official_whiteboard_source_max_concurrent_reads",
        ),
        "room_factory": ("official_whiteboard_room_session_factory",),
        "room_budget": ("official_whiteboard_room_max_concurrent_reads",),
    }
    for name in names[missing]:
        del options[name]
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), composition="official", **options)
    assert app.dependency_overrides == {}
    assert not hasattr(app.state, "prepared_whiteboard_room_configured")


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_room_read_budget_is_explicit_positive_integer(budget):
    with pytest.raises(ValueError):
        room.build_prepared_whiteboard_room_loader(
            session_factory=lambda: None, max_concurrent_reads=budget
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


def test_transferred_room_dto_keeps_null_yjs_and_native_scene_semantics():
    result = room._room_state(row_for(), item_id="unit")
    assert result.yjs_state is None
    assert result.context.room_key == "whiteboard:unit"
    assert result.context.default_actor_user_id == "owner"
    assert result.context.scene == {"elements": [], "appState": {}, "files": {}}
    assert result.snapshot_scene == {}


@pytest.mark.parametrize(
    "change",
    ["missing", "stale", "timestamp", "mismatch", "key", "snapshot", "size", "transferred"],
)
def test_room_dto_rejects_absent_stale_invalid_or_oversized_state(change):
    row = row_for()
    if change == "missing":
        row["collab_id"] = None
    elif change == "stale":
        row["collab_updated_at"] -= timedelta(seconds=1)
    elif change == "timestamp":
        row["collab_updated_at"] = row["collab_updated_at"].replace(tzinfo=UTC)
    elif change == "mismatch":
        row["collab_board_id"] = "other"
    elif change == "key":
        row["room_key"] = "whiteboard:other"
    elif change == "snapshot":
        row["snapshot_text"] = "null"
        row["body_bytes"] += 2
    elif change == "size":
        row["body_bytes"] = room.ROOM_STATE_MAX_BYTES + 1
    else:
        row["yjs_state"] = b"unreported bytes"
    with pytest.raises(room.WhiteboardRoomReaderRefused):
        room._room_state(row, item_id="unit")


def test_json_utf8_and_binary_are_one_aggregate_bound_and_one_paired_case():
    row = row_for(yjs=b"state")
    row["scene_text"] = '{"payload":"é"}'
    row["body_bytes"] = len(row["scene_text"].encode()) + len(row["snapshot_text"].encode()) + 5
    assert room._room_state(row, item_id="unit").context.scene == {"payload": "é"}
    query = str(room._paired_room_query("unit").compile(dialect=postgresql.dialect()))
    assert query.count("CASE WHEN") == 3
    assert "convert_to" in query and "octet_length" in query
    assert "LEFT OUTER JOIN whiteboard_collab_documents" in query
    assert "whiteboards.title" not in query and "users" not in query


@pytest.mark.parametrize("state", ["active", "nested", "new", "cached"])
def test_room_rejects_borrowed_session_before_sql_or_cleanup(monkeypatch, state):
    engine = create_engine("sqlite://")
    MarkerBase.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(Marker(id=1, value="original"))
    db.commit()
    db.expunge_all()
    if state == "new":
        db.add(Marker(id=2, value="pending"))
    elif state == "cached":
        marker = db.get(Marker, 1)
        db.commit()
        assert marker.value == "original"
    else:
        db.begin()
        if state == "nested":
            db.begin_nested()
    transaction, nested = db.get_transaction(), db.get_nested_transaction()
    before = (tuple(db.new), tuple(db.identity_map.values()))
    commands, cleanup = [], []
    event.listen(engine, "before_cursor_execute", lambda *args: commands.append(1))
    rollback, close = db.rollback, db.close
    monkeypatch.setattr(db, "rollback", lambda: cleanup.append("rollback"))
    monkeypatch.setattr(db, "close", lambda: cleanup.append("close"))
    try:
        with pytest.raises(access.WhiteboardSourceReaderRefused):
            room.load_prepared_whiteboard_room_state(
                lambda: db, item_id="unit", user=User(id="member")
            )
        assert commands == [] and cleanup == []
        assert db.get_transaction() is transaction and db.get_nested_transaction() is nested
        assert before == (tuple(db.new), tuple(db.identity_map.values()))
    finally:
        rollback()
        close()
        engine.dispose()


@pytest.mark.parametrize("route", ["model", "table", "connection", "custom"])
def test_room_model_route_and_custom_text_route_refuse_before_owned_sql(monkeypatch, route):
    engine, other = create_engine("sqlite://"), create_engine("sqlite://")
    connection = other.connect()
    if route == "custom":

        class Routed(Session):
            def get_bind(self, mapper=None, clause=None, **kwargs):
                return other if clause is not None else engine

        db = Routed(engine)
    elif route == "connection":
        db = Session(connection)
    else:
        binding = (
            WhiteboardCollabDocument if route == "model" else WhiteboardCollabDocument.__table__
        )
        db = Session(engine, binds={binding: other})
    commands, cleanup = [], []
    event.listen(engine, "before_cursor_execute", lambda *args: commands.append(1))
    event.listen(other, "before_cursor_execute", lambda *args: commands.append(1))
    monkeypatch.setattr(access, "_cleanup", lambda _: cleanup.append(1))
    try:
        with pytest.raises(access.WhiteboardSourceReaderRefused):
            room.load_prepared_whiteboard_room_state(
                lambda: db, item_id="unit", user=User(id="member")
            )
        assert commands == [] and cleanup == []
    finally:
        db.close()
        connection.close()
        engine.dispose()
        other.dispose()


@pytest.mark.parametrize("action", ["rollback", "close"])
def test_room_cleanup_baseexception_preserves_original_read_error(monkeypatch, action):
    engine = create_engine("sqlite://")
    db = Session(engine)
    original = room.WhiteboardRoomReaderRefused("original_read_control")
    calls = []

    def fail(_):
        raise original

    def cleanup(label):
        calls.append(label)
        if label == action:
            raise KeyboardInterrupt

    monkeypatch.setattr(access, "require_whiteboard_source_read_transaction", fail)
    monkeypatch.setattr(db, "rollback", partial(cleanup, "rollback"))
    monkeypatch.setattr(db, "close", partial(cleanup, "close"))
    monkeypatch.setattr(db, "invalidate", partial(cleanup, "invalidate"))
    try:
        with pytest.raises(room.WhiteboardRoomReaderRefused) as caught:
            room.load_prepared_whiteboard_room_state(
                lambda: db, item_id="unit", user=User(id="member")
            )
        assert caught.value is original
        assert "rollback" in calls and "close" in calls
    finally:
        engine.dispose()


def test_cancelled_queued_and_repeated_running_room_read_keep_owned_worker_permit(monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    calls = []
    result = room._room_state(row_for(), item_id="unit")

    def read(factory, **kwargs):
        calls.append(factory())
        entered.set()
        try:
            assert release.wait(3)
            return result
        finally:
            finished.set()

    monkeypatch.setattr(room, "load_prepared_whiteboard_room_state", read)
    loader = room.build_prepared_whiteboard_room_loader(
        session_factory=lambda: "owned", max_concurrent_reads=1
    )

    async def scenario():
        with anyio.fail_after(4):
            running = asyncio.create_task(loader(item_id="unit", user=User(id="member")))
            queued = None
            try:
                while not entered.is_set():
                    await anyio.sleep(0)
                queued = asyncio.create_task(loader(item_id="unit", user=User(id="member")))
                await anyio.sleep(0.01)
                queued.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued
                running.cancel()
                await anyio.sleep(0.01)
                running.cancel()
                await anyio.sleep(0.01)
                assert not running.done() and not finished.is_set()
                assert calls == ["owned"]
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await running
                if queued is not None:
                    await asyncio.gather(queued, return_exceptions=True)
            assert finished.is_set()
            assert await loader(item_id="unit", user=User(id="member")) is result

    anyio.run(scenario)
    assert calls == ["owned", "owned"]


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


@pytest.mark.parametrize("change", ["dependency", "loader", "acl", "marker", "actor", "session"])
def test_after_room_cleanup_captured_assembly_actor_and_session_are_current(change):
    app, context, dependency, acl, _ = assembly()

    async def load(**kwargs):
        if change in {"actor", "session"}:
            if change == "actor":
                context.user.id = "other"
            else:
                context.session.id = "other"
        else:
            field = {
                "dependency": "prepared_official_auth_dependency",
                "loader": "prepared_whiteboard_room_loader",
                "acl": "prepared_whiteboard_source_access",
                "marker": "prepared_whiteboard_room_configured",
            }[change]
            setattr(app.state, field, None)
        return room._room_state(row_for(), item_id="unit")

    app.state.prepared_whiteboard_room_loader = load

    async def scenario():
        with pytest.raises(HTTPException) as caught:
            await whiteboard._load_prepared_whiteboard_room(
                socket_connection(app),
                item_id="unit",
                token="synthetic",
                context=context,
                dependency=dependency,
                loader=load,
                source_access=acl,
            )
        assert caught.value.status_code == (401 if change in {"actor", "session"} else 503)

    anyio.run(scenario)


@pytest.mark.parametrize("change", ["dependency", "loader", "acl"])
def test_dependency_swap_during_final_auth_await_is_not_an_auth_grant(change):
    app, context, _, acl, load = assembly()

    async def dependency(*args):
        field = {
            "dependency": "prepared_official_auth_dependency",
            "loader": "prepared_whiteboard_room_loader",
            "acl": "prepared_whiteboard_source_access",
        }[change]
        setattr(app.state, field, None)
        return context

    app.state.prepared_official_auth_dependency = dependency

    async def scenario():
        with pytest.raises(HTTPException) as caught:
            await whiteboard._load_prepared_whiteboard_room(
                socket_connection(app),
                item_id="unit",
                token="synthetic",
                context=context,
                dependency=dependency,
                loader=load,
                source_access=acl,
            )
        assert caught.value.status_code == 503

    anyio.run(scenario)


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
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"synthetic update")
            assert socket.receive_bytes() == b"echo:synthetic update"
    assert hub.room.effects == [b"synthetic update"]
    assert set(commands) <= {"SELECT", "SHOW", "SET"}


@pytest.mark.parametrize(
    "change", ["missing", "stale", "key", "invalid", "scene", "snapshot", "yjs", "aggregate"]
)
def test_genuine_invalid_and_oversized_room_never_repairs_or_admits_room(
    room_world, monkeypatch, change
):
    c = room_world
    with c.world.core() as db:
        board, collab = (
            db.get(Whiteboard, c.world.ids["board"]),
            db.get(WhiteboardCollabDocument, c.collab_id),
        )
        if change == "missing":
            db.delete(collab)
        elif change == "stale":
            board.updated_at = collab.updated_at + timedelta(seconds=1)
        elif change == "key":
            collab.room_key = "whiteboard:other"
        elif change == "invalid":
            collab.snapshot_scene = None
        elif change == "scene":
            board.scene = {"payload": "x" * room.ROOM_STATE_MAX_BYTES}
            board.updated_at = collab.updated_at
        elif change == "snapshot":
            collab.snapshot_scene = {"payload": "x" * room.ROOM_STATE_MAX_BYTES}
        elif change == "yjs":
            collab.yjs_state = b"x" * (room.ROOM_STATE_MAX_BYTES + 1)
        else:
            board.scene = {"payload": "x" * (room.ROOM_STATE_MAX_BYTES // 2)}
            board.updated_at = collab.updated_at = utcnow_naive()
            collab.snapshot_scene = {"payload": "x" * (room.ROOM_STATE_MAX_BYTES // 2)}
        db.commit()
        if change == "stale":
            db.refresh(board)
            db.refresh(collab)
            assert collab.updated_at < board.updated_at
    if change in {"scene", "snapshot", "yjs", "aggregate"}:
        with c.factory() as db:
            row = db.execute(room._paired_room_query(c.world.ids["board"])).mappings().one()
            assert row["body_bytes"] > room.ROOM_STATE_MAX_BYTES
            assert row["scene_text"] is row["snapshot_text"] is row["yjs_state"] is None
    app, hub = socket_app(c, monkeypatch)
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
    with c.world.core() as db:
        saved = db.get(WhiteboardCollabDocument, c.collab_id)
        assert (saved is None) == (change == "missing")
        if change == "key":
            assert saved.room_key == "whiteboard:other"


def test_genuine_exact_aggregate_bound_is_valid_without_yjs_initialization(room_world):
    c = room_world
    overhead = len(json.dumps({"payload": ""}).encode()) + len(json.dumps({}).encode())
    with c.world.core() as db:
        board = db.get(Whiteboard, c.world.ids["board"])
        collab = db.get(WhiteboardCollabDocument, c.collab_id)
        board.scene = {"payload": "x" * (room.ROOM_STATE_MAX_BYTES - overhead)}
        board.updated_at = collab.updated_at = utcnow_naive()
        collab.snapshot_scene = {}
        db.commit()
    with c.factory() as db:
        row = db.execute(room._paired_room_query(c.world.ids["board"])).mappings().one()
        assert row["body_bytes"] == room.ROOM_STATE_MAX_BYTES
    state = invoke(c)
    assert state.yjs_state is None
    assert len(state.context.scene["payload"]) == room.ROOM_STATE_MAX_BYTES - overhead
    assert state.snapshot_scene == {}


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


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_room_reader_requires_current_transaction(room_world, isolation):
    c = room_world
    engine = c.engine.execution_options(isolation_level=isolation)
    with pytest.raises(access.WhiteboardSourceReaderRefused):
        room.load_prepared_whiteboard_room_state(
            lambda: Session(engine), item_id=c.world.ids["board"], user=context(c).user
        )


def test_genuine_temp_room_shadow_never_replaces_current_public_row(room_world):
    c = room_world
    with c.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TEMP TABLE whiteboard_collab_documents AS SELECT id,whiteboard_id,room_key,yjs_state,snapshot_scene,updated_at FROM public.whiteboard_collab_documents"
            )
        )
        connection.execute(
            text("UPDATE pg_temp.whiteboard_collab_documents SET room_key='whiteboard:forged'")
        )
    assert invoke(c).context.room_key == "whiteboard:" + c.world.ids["board"]


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT title FROM public.whiteboards",
        "SELECT writer_scope FROM public.whiteboard_collab_documents",
        "SELECT token_hash FROM public.auth_sessions",
        "UPDATE public.whiteboard_collab_documents SET yjs_state=NULL WHERE false",
    ],
)
def test_genuine_room_test_role_has_only_new_scoped_reads(room_world, statement):
    with room_world.engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.execute(text(statement))
        assert caught.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "missing",
    [
        "prepared_whiteboard_room_loader",
        "prepared_official_auth_dependency",
        "prepared_whiteboard_source_access",
        "prepared_whiteboard_room_configured",
    ],
)
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


@pytest.mark.parametrize("revoke", ["source", "app"])
def test_genuine_room_wait_rechecks_current_auth_before_continuation(room_world, revoke):
    c = room_world
    app, initial, dependency, acl, _ = assembly()
    initial = context(c)
    dependency = official_auth.build_prepared_official_auth_dependency(
        session_factory=c.world.factory, max_concurrent_reads=1
    )
    loader = room.build_prepared_whiteboard_room_loader(
        session_factory=c.factory, max_concurrent_reads=1
    )
    app.state.prepared_official_auth_dependency = dependency
    app.state.prepared_whiteboard_room_loader = loader
    waiter, pid = Event(), []

    def observed(connection, cursor, statement, *args):
        if "LEFT OUTER JOIN whiteboard_collab_documents" in statement:
            pid.append(connection.scalar(text("SELECT pg_catalog.pg_backend_pid()")))
            waiter.set()

    event.listen(c.engine, "before_cursor_execute", observed)
    lock = c.world.core()
    observer = c.world.core()
    revoker = c.world.core()

    async def scenario():
        with anyio.fail_after(5):
            task = asyncio.create_task(
                whiteboard._load_prepared_whiteboard_room(
                    socket_connection(app),
                    item_id=c.world.ids["board"],
                    token=c.world.token,
                    context=initial,
                    dependency=dependency,
                    loader=loader,
                    source_access=acl,
                )
            )
            try:
                while not waiter.is_set():
                    await anyio.sleep(0)
                blocked = False
                for _ in range(100):
                    blocked = bool(
                        observer.scalar(
                            text("SELECT cardinality(pg_catalog.pg_blocking_pids(:pid))>0"),
                            {"pid": pid[0]},
                        )
                    )
                    if blocked:
                        break
                    await anyio.sleep(0.005)
                assert blocked
                if revoke == "source":
                    revoker.get(AuthSession, c.world.state["source_id"]).revoked_at = utcnow_naive()
                else:
                    revoker.get(CompanyAppControl, "whiteboard").enabled = False
                revoker.commit()
            finally:
                lock.rollback()
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == (401 if revoke == "source" else 403)

    try:
        lock.execute(text("LOCK TABLE public.whiteboard_collab_documents IN ACCESS EXCLUSIVE MODE"))
        observer.connection()
        revoker.connection()
        anyio.run(scenario)
    finally:
        lock.close()
        observer.close()
        revoker.close()
        event.remove(c.engine, "before_cursor_execute", observed)
    assert waiter.is_set()
