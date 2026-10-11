"""Explicit inactive Docs existing-room Source reads; registry red first."""

import asyncio
from functools import partial
from threading import Event

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from starlette.websockets import WebSocketDisconnect
import y_py as Y

from miy_api import api_registry, official_auth
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, utcnow_naive
from miy_api.domains.collaboration.yjs_runtime import InProcessCollabBus
from miy_api.domains.docs import collab, collab_source_room as room, router as docs
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state, yjs_state_to_blocks
from miy_api.domains.docs.models import DocsCollabDocument, NativeDocPage
from test_prepared_docs_source_access import (
    actor as actor,
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    docs_world as docs_world,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
    ws_world as ws_world,  # noqa: F401
)
from test_prepared_official_ws_auth import (
    SyntheticHub as SyntheticHub,
    socket_connection as socket_connection,
    socket_path as socket_path,
)
from test_prepared_whiteboard_source_access import Marker as Marker, MarkerBase as MarkerBase
from test_docs_collab import _paragraph_blocks as _paragraph_blocks


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

    # The same native profile may read its declared data, but cannot expand authority.
    with room_world.source_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(
                text("SELECT content_text FROM public.docs_native_doc_pages LIMIT 0")
            )
        assert denied.value.orig.sqlstate == "42501"
    with room_world.source_engine.connect() as scoped_connection:
        with pytest.raises(DBAPIError) as denied:
            scoped_connection.execute(
                text("UPDATE public.docs_collab_documents SET room_key=room_key WHERE false")
            )
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("change", ["meaningful_null", "oversize"])
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


@pytest.mark.parametrize("revoke", ["session"])
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
