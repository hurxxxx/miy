"""Explicit inactive Docs existing-room Source reads; registry red first."""

import asyncio
from dataclasses import replace
from functools import partial
from threading import Event
from types import SimpleNamespace

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event, null, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect
import y_py as Y

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.collaboration.yjs_runtime import InProcessCollabBus
from miy_api.domains.docs import collab, collab_source_room as room, router as docs
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state, yjs_state_to_blocks
from miy_api.domains.docs.models import DocsCollabDocument, NativeDoc, NativeDocPage
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_prepared_docs_source_access import (
    actor,
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    docs_world as docs_world,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
    ws_world as ws_world,  # noqa: F401
)
from test_prepared_official_ws_auth import SyntheticHub, socket_connection, socket_path
from test_prepared_whiteboard_source_access import Marker, MarkerBase
from test_docs_collab import _paragraph_blocks


def test_explicit_docs_room_source_requires_complete_prepared_server_assembly(monkeypatch):
    # Assembly binds callbacks without allocating SQL, starting rooms or codecs.
    monkeypatch.setattr(api_registry, "router_specs", lambda _: ())
    app = FastAPI()

    def auth_factory():
        raise AssertionError("Assembly allocated an auth Session")

    def acl_factory():
        raise AssertionError("Assembly allocated a Docs ACL Session")

    def writer_factory():
        raise AssertionError("Assembly allocated a Core writer Session")

    def room_factory():
        raise AssertionError("Assembly allocated a Docs room Session")

    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=auth_factory,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=acl_factory,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=writer_factory,
        official_writer_read_max_concurrent_reads=1,
        official_docs_room_source_session_factory=room_factory,
        official_docs_room_source_max_concurrent_reads=1,
    )
    assert callable(app.state.prepared_official_auth_dependency)
    assert callable(app.state.prepared_docs_source_access)
    assert callable(app.state.prepared_official_writer_access)
    assert callable(app.state.prepared_docs_room_loader)
    assert app.state.prepared_docs_room_configured is True


def options():
    return dict(
        composition="official",
        official_auth_session_factory=lambda: None,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=lambda: None,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=lambda: None,
        official_writer_read_max_concurrent_reads=1,
        official_docs_room_source_session_factory=lambda: None,
        official_docs_room_source_max_concurrent_reads=1,
    )


@pytest.mark.parametrize(
    "missing",
    [
        "official_auth_session_factory",
        "official_docs_source_session_factory",
        "official_writer_read_session_factory",
        "official_docs_room_source_session_factory",
        "official_docs_room_source_max_concurrent_reads",
    ],
)
def test_partial_room_assembly_refuses_before_state_or_dependency_mutation(monkeypatch, missing):
    chosen = options()
    del chosen[missing]
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert not app.state._state and not app.dependency_overrides


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "1"])
def test_room_budget_refuses_complete_assembly_before_state(monkeypatch, budget):
    chosen = options()
    chosen["official_docs_room_source_max_concurrent_reads"] = budget
    app = FastAPI()
    with pytest.raises(ValueError):
        api_registry.register_api_routers(app, get_settings(), **chosen)
    assert not app.state._state and not app.dependency_overrides


def row_for(page=None, snapshot=None, yjs=None):
    return dict(
        page_id="unit",
        doc_id="parent",
        parent_id="parent",
        content_format="block",
        page_trash=None,
        doc_trash=None,
        created_by_id="creator",
        collab_id="collab",
        source_type="native_doc_page",
        source_page_id="unit",
        room_key="native_doc_page:unit",
        page_text=page,
        snapshot_text=snapshot,
        yjs_state=yjs,
        body_bytes=sum(len(value.encode()) for value in (page, snapshot) if value is not None)
        + len(yjs or b""),
    )


@pytest.mark.parametrize(
    "page,snapshot,yjs",
    [
        (None, None, None),
        ("null", "null", None),
        (None, "null", b""),
        ("null", None, b""),
        ("[]", "[]", b""),
    ],
)
def test_sqlnull_jsonnull_and_empty_binary_preserve_native_none_empty_distinction(
    page, snapshot, yjs
):
    state = room._room_state(row_for(page, snapshot, yjs), page_id="unit")
    assert state.yjs_state == yjs and (state.yjs_state is None) == (yjs is None)
    assert state.context.default_actor_user_id == "creator"
    assert state.context.room_key == "native_doc_page:unit"
    assert state.context.content_blocks == (None if page in {None, "null"} else [])


@pytest.mark.parametrize(
    "page,snapshot,yjs",
    [
        ("[]", "[]", None),
        ("[]", None, b"state"),
        ('[{"type":"paragraph"}]', "[]", b""),
        (None, '[{"type":"paragraph"}]', None),
        ("null", "[{}]", b""),
    ],
)
def test_needs_repair_or_meaningful_body_without_yjs_refuses(page, snapshot, yjs):
    with pytest.raises(room.DocsRoomReaderRefused):
        room._room_state(row_for(page, snapshot, yjs), page_id="unit")


@pytest.mark.parametrize(
    "change",
    ["missing", "suffix", "source", "parent", "actor", "size", "transferred", "json", "shape"],
)
def test_invalid_missing_binding_or_oversized_state_is_private_refusal(change):
    row = row_for("[]", "[]", b"state")
    if change == "missing":
        row["collab_id"] = None
    elif change == "suffix":
        row["room_key"] += "::old"
    elif change == "source":
        row["source_type"] = "other"
    elif change == "parent":
        row["parent_id"] = "other"
    elif change == "actor":
        row["created_by_id"] = None
    elif change == "size":
        row["body_bytes"] = room.ROOM_STATE_MAX_BYTES + 1
    elif change == "transferred":
        row["body_bytes"] += 1
    elif change == "json":
        row["page_text"] = "bad"
        row["body_bytes"] = len("bad") + 2 + 5
    else:
        row["page_text"] = '"x"'
        row["body_bytes"] = 3 + 2 + 5
    with pytest.raises(room.DocsRoomReaderRefused):
        room._room_state(row, page_id="unit")


def test_paired_projection_has_one_whole_state_bound_before_transfer():
    query = str(room._paired_room_query("unit").compile(dialect=postgresql.dialect()))
    assert query.count("CASE WHEN") == 3
    assert "LEFT OUTER JOIN docs_collab_documents" in query and "JOIN docs_native_docs" in query
    assert "convert_to" in query and "octet_length" in query
    assert "created_by_id" in query
    assert "updated_at" not in query and "content_text" not in query and "writer_scope" not in query
    row = row_for('[{"text":"é"}]', "[]", b"state")
    assert room._room_state(row, page_id="unit").context.content_blocks == [{"text": "é"}]


@pytest.mark.parametrize("state", ["active", "nested", "new", "cached"])
def test_borrowed_room_session_is_refused_before_sql_or_cleanup(monkeypatch, state):
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
    previous = (
        db.get_transaction(),
        db.get_nested_transaction(),
        tuple(db.new),
        tuple(db.identity_map.values()),
    )
    statements, cleanup = [], []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(1))
    close, rollback = db.close, db.rollback
    monkeypatch.setattr(db, "close", lambda: cleanup.append("close"))
    monkeypatch.setattr(db, "rollback", lambda: cleanup.append("rollback"))
    try:
        with pytest.raises(room.DocsRoomReaderRefused) as denied:
            room.load_prepared_docs_room_state(
                lambda: db, page_ref="native_doc_page__unit", user=User(id="member")
            )
        assert denied.value.reason == "fresh_session_required"
        assert previous == (
            db.get_transaction(),
            db.get_nested_transaction(),
            tuple(db.new),
            tuple(db.identity_map.values()),
        )
        assert statements == cleanup == []
    finally:
        rollback()
        close()
        engine.dispose()


def test_room18_detects_its_extra_model_engine_before_owned_sql():
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    db = Session(bind=first, binds={DocsCollabDocument: second})
    try:
        with pytest.raises(room.DocsRoomReaderRefused) as denied:
            room.load_prepared_docs_room_state(
                lambda: db, page_ref="native_doc_page__unit", user=User(id="member")
            )
        assert denied.value.reason == "single_engine_required"
    finally:
        db.close()
        first.dispose()
        second.dispose()


def test_cancelled_queued_and_repeated_running_room_read_join_before_permit(monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    calls = []

    def read(*a, **k):
        calls.append(1)
        entered.set()
        try:
            assert release.wait(8)
            return room._room_state(row_for(), page_id="unit")
        finally:
            finished.set()

    monkeypatch.setattr(room, "load_prepared_docs_room_state", read)
    invoke = partial(
        room.build_prepared_docs_room_loader(session_factory=lambda: None, max_concurrent_reads=1),
        page_ref="native_doc_page__unit",
        user=User(id="member"),
    )

    async def scenario():
        with anyio.fail_after(8):
            running = asyncio.create_task(invoke())
            queued = None
            try:
                while not entered.is_set():
                    await anyio.sleep(0)
                queued = asyncio.create_task(invoke())
                await anyio.sleep(0)
                queued.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued
                queued = None
                running.cancel()
                await anyio.sleep(0)
                running.cancel()
                await anyio.sleep(0.02)
                assert not running.done() and not finished.is_set() and calls == [1]
            finally:
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await running

    anyio.run(scenario)
    assert finished.is_set() and calls == [1]


@pytest.mark.parametrize("point", [("writer", 1), ("room", 1), ("writer", 2), ("auth", 1)])
@pytest.mark.parametrize(
    "change", ["room", "auth", "Source", "Core", "hub", "identity", "actor", "session"]
)
def test_every_initial_read_await_requires_original_assembly_and_identity(point, change):
    app = FastAPI()
    seen = []
    counts = {"writer": 0, "room": 0, "auth": 0}
    identity = WriterIdentity(SUITE_SCOPE, "legacy", 1)
    hub = SyntheticHub(identity)
    context = SimpleNamespace(user=User(id="member"), session=SimpleNamespace(id="session"))

    def mutate(name):
        counts[name] += 1
        seen.append(name)
        if (name, counts[name]) != point:
            return
        if change == "actor":
            context.user.id = "other"
        elif change == "session":
            context.session.id = "other"
        elif change == "hub":
            app.state.docs_collab = SyntheticHub(identity)
        elif change == "identity":
            hub.writer_identity = replace(identity)
        else:
            field = {
                "room": "prepared_docs_room_loader",
                "auth": "prepared_official_auth_dependency",
                "Source": "prepared_docs_source_access",
                "Core": "prepared_official_writer_access",
            }[change]

            async def replacement(*a, **k):
                return None

            setattr(app.state, field, replacement)

    async def auth(*a, **k):
        mutate("auth")
        return context

    async def acl(*a, **k):
        pytest.fail("Initial room read should own its ACL in the same Source Session")

    async def core(*a, **k):
        mutate("writer")

    async def loader(*a, **k):
        mutate("room")
        return room._room_state(row_for(), page_id="unit")

    app.state.prepared_official_auth_dependency = auth
    app.state.prepared_docs_source_access = acl
    app.state.prepared_official_writer_access = core
    app.state.docs_collab = hub
    app.state.prepared_docs_source_configured = True
    app.state.prepared_docs_room_loader = loader
    app.state.prepared_docs_room_configured = True

    async def scenario():
        with pytest.raises(HTTPException) as denied:
            await docs._load_prepared_docs_collab_context(
                socket_connection(app),
                page_ref="native_doc_page__unit",
                token="synthetic",
                auth_context=context,
                room_loader=loader,
                auth_dependency=auth,
                source_access=acl,
                writer_access=core,
                hub=hub,
                writer_identity=identity,
            )
        assert denied.value.status_code == (401 if change in {"actor", "session"} else 503)

    anyio.run(scenario)
    assert (
        seen
        == ["writer", "room", "writer", "auth"][
            : [("writer", 1), ("room", 1), ("writer", 2), ("auth", 1)].index(point) + 1
        ]
    )


# The accepted Docs ACL fixture keeps its exact original profile. This separate
# room fixture explicitly adds only two page and six collab read columns.
@pytest.fixture
def room_world(docs_world):
    c = docs_world
    role = sql.Identifier(c.source_engine.url.username)
    c.world.core_sql(
        sql.SQL(
            "GRANT SELECT (created_by_id, content_blocks) ON public.docs_native_doc_pages TO {}"
        ).format(role)
    )
    columns = (
        "id",
        "source_type",
        "source_page_id",
        "room_key",
        "yjs_state",
        "snapshot_content_blocks",
    )
    c.world.core_sql(
        sql.SQL("GRANT SELECT ({}) ON public.docs_collab_documents TO {}").format(
            sql.SQL(",").join(map(sql.Identifier, columns)), role
        )
    )
    return c


def load(c, page_ref=None):
    return room.load_prepared_docs_room_state(
        c.source_factory,
        page_ref=page_ref or "native_doc_page__" + c.world.ids["ws_page"],
        user=actor(c),
    )


def persist_test_state(c, page, snapshot, yjs):
    with c.world.core() as db:
        db.get(NativeDocPage, c.world.ids["ws_page"]).content_blocks = page
        record = db.scalar(
            select(DocsCollabDocument).where(
                DocsCollabDocument.source_page_id == c.world.ids["ws_page"]
            )
        )
        record.snapshot_content_blocks = snapshot
        record.yjs_state = yjs
        db.commit()


def native_app(c, monkeypatch):
    selected = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == "miy_api.domains.docs.router" and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: selected)
    app = FastAPI()
    hub = SyntheticHub(c.world.writer)
    app.state.docs_collab = hub
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=c.world.factory,
        official_auth_max_concurrent_reads=1,
        official_docs_source_session_factory=c.source_factory,
        official_docs_source_max_concurrent_reads=1,
        official_writer_read_session_factory=c.writer_factory,
        official_writer_read_max_concurrent_reads=1,
        official_docs_room_source_session_factory=c.source_factory,
        official_docs_room_source_max_concurrent_reads=1,
    )
    monkeypatch.setattr(
        docs,
        "get_session_factory",
        lambda: pytest.fail("Configured Docs room allocated global initial Source"),
    )
    monkeypatch.setattr(
        docs,
        "ensure_collab_document_state",
        lambda *a, **k: pytest.fail("Read-only room tried initialization/repair"),
    )
    return app, hub


def test_genuine_native_blocknote_yjs_state_and_socket_load_without_global_init(
    room_world, monkeypatch
):
    c = room_world
    blocks = _paragraph_blocks("Owned room native codec")
    yjs = blocks_to_yjs_state(blocks)
    assert yjs
    persist_test_state(c, blocks, blocks, yjs)
    commands = []
    event.listen(
        c.source_engine,
        "before_cursor_execute",
        lambda _a, _b, statement, *_: commands.append(statement),
    )
    loaded = load(c)
    assert loaded.context.content_blocks == blocks and loaded.yjs_state == yjs

    # Real Y.py/YRoom lifecycle, using qualified in-process relay and no writes.
    async def native():
        hub = collab.DocsCollabHub(bus=InProcessCollabBus(instance_id="owned-room-read"))
        try:
            runtime = await hub.get_room(loaded.context, loaded.yjs_state)
            decoded = yjs_state_to_blocks(bytes(Y.encode_state_as_update(runtime.room.ydoc)))
            assert collab.block_content_equal(decoded, blocks)
        finally:
            await hub.shutdown()

    anyio.run(native)
    app, hub = native_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            socket.send_bytes(b"owned read context")
            assert socket.receive_bytes() == b"echo:owned read context"
    assert hub.room.effects == [b"owned read context"]
    assert not any(
        statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        for statement in commands
    )


@pytest.mark.parametrize("jsonnull", [False, True])
@pytest.mark.parametrize("yjs", [None, b""])
def test_genuine_sqlnull_jsonnull_with_null_or_empty_yjs_native_empty_room(
    room_world, jsonnull, yjs
):
    c = room_world
    persist_test_state(c, None if jsonnull else null(), None if jsonnull else null(), yjs)
    loaded = load(c)
    assert loaded.context.content_blocks is None and loaded.snapshot_content_blocks is None
    assert loaded.yjs_state == yjs and (loaded.yjs_state is None) == (yjs is None)
    # Probe Source bytes before the native legacy shutdown persists its snapshot.
    with c.source_factory() as db:
        row = db.execute(room._paired_room_query(c.world.ids["ws_page"])).mappings().one()
        assert row["body_bytes"] == (8 if jsonnull else 0)

    async def native():
        hub = collab.DocsCollabHub(bus=InProcessCollabBus(instance_id="owned-empty-room"))
        try:
            runtime = await hub.get_room(loaded.context, loaded.yjs_state)
            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == b"\x00\x00"
        finally:
            await hub.shutdown()

    anyio.run(native)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "key",
        "snapshot",
        "null_empty_page",
        "meaningful_null",
        "meaningful_empty",
        "oversize",
    ],
)
def test_genuine_missing_invalid_repair_or_oversized_room_never_repairs_or_admits(
    room_world, monkeypatch, change
):
    c = room_world
    with c.world.core() as db:
        page = db.get(NativeDocPage, c.world.ids["ws_page"])
        record = db.scalar(
            select(DocsCollabDocument).where(DocsCollabDocument.source_page_id == page.id)
        )
        if change == "missing":
            db.delete(record)
        elif change == "key":
            record.room_key += "::invalid"
        elif change == "snapshot":
            record.snapshot_content_blocks = None
        elif change == "null_empty_page":
            record.yjs_state = None
        elif change in {"meaningful_null", "meaningful_empty"}:
            page.content_blocks = [{"type": "paragraph"}]
            record.snapshot_content_blocks = page.content_blocks
            record.yjs_state = None if change == "meaningful_null" else b""
        else:
            record.yjs_state = b"x" * (room.ROOM_STATE_MAX_BYTES + 1)
        db.commit()
    app, hub = native_app(c, monkeypatch)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
                socket.send_json({"type": "auth", "token": c.world.token})
                socket.receive_bytes()
    assert denied.value.code == 1013 and not hub.acquired and not hub.room.effects


def test_genuine_exact_whole_state_bound_and_page_snapshot_inequality_are_valid(room_world):
    c = room_world
    persist_test_state(c, [], [{"different": "snapshot"}], b"state")
    with c.source_factory() as db:
        row = db.execute(room._paired_room_query(c.world.ids["ws_page"])).mappings().one()
    yjs = b"x" * (room.ROOM_STATE_MAX_BYTES - (row["body_bytes"] - 5))
    persist_test_state(c, [], [{"different": "snapshot"}], yjs)
    assert len(load(c).yjs_state) == len(yjs)


@pytest.mark.parametrize("prefix", ["native_doc__", "", "other__"])
def test_genuine_native_page_refuses_wrong_source_prefix(room_world, prefix):
    with pytest.raises(HTTPException) as denied:
        load(room_world, prefix + room_world.world.ids["ws_page"])
    assert denied.value.status_code == 404


def test_genuine_existing_double_native_prefix_normalizes_like_default(room_world):
    c = room_world
    state = load(c, "native_doc_page__native_doc_page__" + c.world.ids["ws_page"])
    assert state.context.page_ref == "native_doc_page__" + c.world.ids["ws_page"]


@pytest.mark.parametrize("missing", ["marker", "room", "auth", "Source", "Core"])
def test_genuine_configured_room_missing_option_does_not_fall_back(
    room_world, monkeypatch, missing
):
    c = room_world
    app, hub = native_app(c, monkeypatch)
    field = {
        "marker": "prepared_docs_room_configured",
        "room": "prepared_docs_room_loader",
        "auth": "prepared_official_auth_dependency",
        "Source": "prepared_docs_source_access",
        "Core": "prepared_official_writer_access",
    }[missing]
    delattr(app.state, field)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
                socket.send_json({"type": "auth", "token": c.world.token})
                socket.receive_bytes()
    assert denied.value.code == 1013 and not hub.acquired and not hub.room.effects


@pytest.mark.parametrize("revoke", ["session", "app"])
def test_genuine_room_source_wait_rechecks_current_auth_after_cleanup(
    room_world, monkeypatch, revoke
):
    c = room_world
    app, hub = native_app(c, monkeypatch)
    context = official_auth.resolve_prepared_official_auth_context(
        c.world.factory, c.world.token, logical_app_id="docs"
    )
    read = partial(
        docs._load_prepared_docs_collab_context,
        socket_connection(app),
        page_ref="native_doc_page__" + c.world.ids["ws_page"],
        token=c.world.token,
        auth_context=context,
        room_loader=app.state.prepared_docs_room_loader,
        auth_dependency=app.state.prepared_official_auth_dependency,
        source_access=app.state.prepared_docs_source_access,
        writer_access=app.state.prepared_official_writer_access,
        hub=hub,
        writer_identity=hub.writer_identity,
    )
    waiting, pids = Event(), []

    def observe(connection, _cursor, statement, *_):
        if "CASE WHEN" in statement and "docs_collab_documents" in statement:
            pids.append(connection.connection.driver_connection.info.backend_pid)
            waiting.set()

    event.listen(c.source_engine, "before_cursor_execute", observe)
    lock, observer, revoker = c.world.core(), c.world.core(), c.world.core()
    for db in (lock, observer, revoker):
        db.execute(select(1))
    lock.execute(text("LOCK TABLE public.docs_collab_documents IN ACCESS EXCLUSIVE MODE"))

    async def scenario():
        with anyio.fail_after(8):
            running = asyncio.create_task(read())
            try:
                while not waiting.is_set():
                    await anyio.sleep(0)
                blocked = False
                for _ in range(200):
                    blocked = bool(
                        observer.scalar(
                            text("SELECT cardinality(pg_catalog.pg_blocking_pids(:pid))>0"),
                            {"pid": pids[0]},
                        )
                    )
                    if blocked:
                        break
                    await anyio.sleep(0.005)
                assert blocked
                if revoke == "session":
                    revoker.get(AuthSession, c.world.state["source_id"]).revoked_at = utcnow_naive()
                else:
                    revoker.get(CompanyAppControl, "docs").enabled = False
                revoker.commit()
            finally:
                lock.rollback()
            with pytest.raises(HTTPException) as denied:
                await running
            assert denied.value.status_code == (401 if revoke == "session" else 403)

    try:
        anyio.run(scenario)
    finally:
        lock.close()
        observer.close()
        revoker.close()
        event.remove(c.source_engine, "before_cursor_execute", observe)
    assert not hub.acquired and not hub.room.effects


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT title FROM public.docs_native_doc_pages LIMIT 0",
        "SELECT content_text FROM public.docs_native_doc_pages LIMIT 0",
        "SELECT writer_scope FROM public.docs_collab_documents LIMIT 0",
        "SELECT scope FROM public.official_runtime_ownership LIMIT 0",
        "UPDATE public.docs_collab_documents SET room_key=room_key WHERE false",
    ],
)
def test_genuine_room_role_keeps_other_columns_controls_and_writes_forbidden(room_world, statement):
    with room_world.source_engine.connect() as db:
        with pytest.raises(DBAPIError) as denied:
            db.execute(text(statement))
        assert denied.value.orig.sqlstate == "42501"


def test_genuine_final_acl_does_not_reuse_page_or_doc_identity_cache(room_world):
    c = room_world
    rechecked = []
    revoker = c.world.core()
    revoker.execute(select(1))

    def revoke_after_projection(_connection, _cursor, statement, *_):
        if "CASE WHEN" in statement and "docs_collab_documents" in statement and not rechecked:
            rechecked.append(1)
            revoker.get(NativeDoc, c.world.ids["owned"]).owner_id = c.world.state["admin"]["user"][
                "id"
            ]
            revoker.commit()

    event.listen(c.source_engine, "after_cursor_execute", revoke_after_projection)
    try:
        with pytest.raises(HTTPException) as denied:
            load(c)
        assert denied.value.status_code == 403 and rechecked == [1]
    finally:
        event.remove(c.source_engine, "after_cursor_execute", revoke_after_projection)
        revoker.close()


@pytest.mark.parametrize("change", ["remove", "replace"])
def test_genuine_room_callback_rebind_after_connect_denies_next_frame_without_fence(
    room_world, monkeypatch, change
):
    c = room_world
    app, hub = native_app(c, monkeypatch)
    with TestClient(app) as client:
        with client.websocket_connect(socket_path("docs", c.world.ids["ws_page"])) as socket:
            socket.send_json({"type": "auth", "token": c.world.token})
            assert socket.receive_bytes() == b"ready"
            if change == "remove":
                del app.state.prepared_docs_room_loader
            else:

                async def replacement(*a, **k):
                    return None

                app.state.prepared_docs_room_loader = replacement
            socket.send_bytes(b"forbidden rebound frame")
            with pytest.raises(WebSocketDisconnect) as denied:
                socket.receive_bytes()
            assert (
                denied.value.code == 1013
                and denied.value.reason == "official_authority_unavailable"
            )
    assert not hub.room.effects and not hub.fenced


def test_room_cleanup_baseexception_preserves_original_policy(monkeypatch):
    engine = create_engine("sqlite://")
    db = Session(engine)
    actions = []

    class Stop(BaseException):
        pass

    original = HTTPException(status_code=403, detail="owned denial")

    def refuse(_):
        raise original

    monkeypatch.setattr(room, "require_owned_read_transaction", refuse)

    def fail(name):
        def action():
            actions.append(name)
            raise Stop()

        return action

    rollback, close = db.rollback, db.close
    monkeypatch.setattr(db, "rollback", fail("rollback"))
    monkeypatch.setattr(db, "close", fail("close"))
    monkeypatch.setattr(db, "invalidate", lambda: actions.append("invalidate"))
    try:
        with pytest.raises(HTTPException) as denied:
            room.load_prepared_docs_room_state(
                lambda: db, page_ref="native_doc_page__unit", user=User(id="member")
            )
        assert denied.value is original and actions == [
            "rollback",
            "invalidate",
            "close",
            "invalidate",
        ]
    finally:
        rollback()
        close()
        engine.dispose()


@pytest.mark.parametrize("value", [None, object()])
def test_invalid_factory_return_is_private_refusal_before_cleanup(value):
    with pytest.raises(room.DocsRoomReaderRefused) as denied:
        room.load_prepared_docs_room_state(
            lambda: value, page_ref="native_doc_page__unit", user=User(id="member")
        )
    assert denied.value.reason == "standard_session_required"
