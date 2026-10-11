"""Pinned writer checks and actual source preservation across Docs WS drain."""

import asyncio
import json
from types import SimpleNamespace

import pytest
import y_py as Y
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect
from test_docs_collab import _paragraph_blocks
from test_official_writer_docs import docs_source as docs_source
from test_official_writer_fence import change
from test_official_writer_fence import writer as writer

from miy_api.domains.collaboration.yjs_runtime import InProcessCollabBus
from miy_api.domains.docs import collab
from miy_api.domains.docs import router as docs_router
from miy_api.domains.docs.collab import (
    CollabPageContext,
    DocsCollabHub,
    make_page_ref,
    make_room_key,
)
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state
from miy_api.domains.docs.models import DocsCollabDocument, NativeDocPage
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE


def _paths(page):
    base = "/api/v1/docs/collab/pages/" + make_page_ref(page["source_type"], page["source_page_id"])
    return base + "/session", base + "/ws"


def _context(page, admin):
    return CollabPageContext(
        page_ref=make_page_ref(page["source_type"], page["source_page_id"]),
        source_type=page["source_type"],
        source_page_id=page["source_page_id"],
        room_key=make_room_key(page["source_type"], page["source_page_id"]),
        can_edit=True,
        content_blocks=[],
        default_actor_user_id=admin["user"]["id"],
    )


async def _settle_retired(hub):
    while hub._disposals:
        await asyncio.gather(*tuple(hub._disposals))


async def _eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


def test_active_docs_ws_frame_closes_and_retires_room_on_drain(client, docs_source):
    factory, admin, _, _, page = docs_source
    _, ws = _paths(page)
    hub = client.app.state.docs_collab
    with client.websocket_connect(ws) as connection:
        connection.send_json({"type": "auth", "token": admin["token"]})
        assert connection.receive_bytes()
        with factory.begin() as db:
            change(db, admin)
        connection.send_bytes(b"\x00must-not-apply")
        with pytest.raises(WebSocketDisconnect) as denied:
            while True:
                connection.receive_bytes()
        assert denied.value.code == 1013
    client.portal.call(_settle_retired, hub)
    assert not hub._rooms
    with factory() as db:
        assert db.get(NativeDocPage, page["source_page_id"]).content_blocks == []
        assert db.scalar(select(DocsCollabDocument)).snapshot_content_blocks == []


def test_idle_docs_ws_monitor_closes_without_another_client_frame(client, docs_source, monkeypatch):
    factory, admin, _, _, page = docs_source
    # Exercise the real periodic monitor without waiting the production interval.
    monkeypatch.setattr(
        docs_router, "get_settings", lambda: SimpleNamespace(collab_acl_recheck_seconds=0.01)
    )
    _, ws = _paths(page)
    hub = client.app.state.docs_collab
    with client.websocket_connect(ws) as connection:
        connection.send_json({"type": "auth", "token": admin["token"]})
        assert connection.receive_bytes()
        with factory.begin() as db:
            change(db, admin)
        with pytest.raises(WebSocketDisconnect) as denied:
            while True:
                connection.receive_bytes()
        assert denied.value.code == 1013
    client.portal.call(_settle_retired, hub)
    assert not hub._rooms


def test_dirty_flush_is_not_saved_or_retried_and_old_cleanup_keeps_replacement(
    docs_source, monkeypatch
):
    factory, admin, _, _, page = docs_source
    calls = []
    original = collab._persist_docs_runtime_state_sync

    def observe(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(collab, "_persist_docs_runtime_state_sync", observe)

    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="dirty"))
        await hub.startup()
        context = _context(page, admin)
        monkeypatch.setattr(hub, "_schedule_flush", lambda runtime: None)
        try:
            runtime = await hub.get_room(context, None)
            Y.apply_update(runtime.room.ydoc, blocks_to_yjs_state(_paragraph_blocks("Unsaved")))
            with factory.begin() as db:
                change(db, admin)
            assert await hub._flush_runtime(runtime) is False
            assert context.room_key not in hub._rooms
            # Internal get_room is not an admission boundary. Simulate a new
            # runtime arriving before an old handler's finally finishes.
            replacement = await hub.get_room(context, None)
            await hub.cleanup_room(context.room_key, expected_runtime=runtime)
            assert hub._rooms[context.room_key] is replacement
            hub.fence_runtime(replacement)
            await _settle_retired(hub)
            assert runtime.room.ydoc is None
        finally:
            await hub.shutdown()
        assert len(calls) == 1  # Neither retirement nor shutdown retries dirty state.

    asyncio.run(exercise())
    with factory() as db:
        assert db.get(NativeDocPage, page["source_page_id"]).content_blocks == []
        assert db.scalar(select(DocsCollabDocument)) is None


def test_cancelled_flush_keeps_serialization_until_its_sql_thread_finishes(monkeypatch):
    from threading import Event

    started, release = Event(), Event()
    calls = []
    active = []

    def persist(*args, **kwargs):
        active.append(1)
        calls.append(len(active))
        try:
            if len(calls) == 1:
                started.set()
                assert release.wait(5)
        finally:
            active.pop()

    monkeypatch.setattr(collab, "_persist_docs_runtime_state_sync", persist)

    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="cancel"))
        context = CollabPageContext(
            page_ref="native_doc_page__unit",
            source_type="native_doc_page",
            source_page_id="unit",
            room_key="native_doc_page:unit",
            can_edit=True,
            content_blocks=[],
            default_actor_user_id="unit",
        )
        first = second = None
        try:
            runtime = await hub.get_room(context, None)
            first = asyncio.create_task(hub._flush_runtime(runtime))
            await _eventually(started.is_set)
            first.cancel()
            await asyncio.sleep(0)
            first.cancel()  # Cleanup timeout/repeated cancellation cannot detach SQL.
            second = asyncio.create_task(hub._flush_runtime(runtime))
            await asyncio.sleep(0)
            assert calls == [1]
            assert not first.done() and not second.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert await second is True
            assert calls == [1, 1]
            hub.fence_runtime(runtime)
        finally:
            release.set()
            for task in (first, second):
                if task is not None:
                    await asyncio.gather(task, return_exceptions=True)
            await hub.shutdown()

    asyncio.run(exercise())


def test_persistence_sql_deadline_cancels_pg_statement_and_resets_transaction_settings(writer):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    factory, _, _ = writer
    with factory() as db:
        before = db.execute(
            text("SELECT current_setting('statement_timeout'), current_setting('lock_timeout')")
        ).one()
        with pytest.raises(DBAPIError) as denied:
            with collab._docs_persistence_sql_deadline(db, 0.15):
                db.execute(text("SELECT pg_sleep(2)"))
        assert denied.value.orig.sqlstate == "57014"
        db.rollback()
        assert (
            db.execute(
                text("SELECT current_setting('statement_timeout'), current_setting('lock_timeout')")
            ).one()
            == before
        )
        # The hook must be removed, not left with an expired deadline on a pooled connection.
        with collab._docs_persistence_sql_deadline(db, 1):
            assert db.scalar(text("SELECT 1")) == 1
            db.commit()
        assert (
            db.execute(
                text("SELECT current_setting('statement_timeout'), current_setting('lock_timeout')")
            ).one()
            == before
        )


def test_shutdown_completes_while_actual_source_row_lock_remains_held(docs_source, monkeypatch):
    from time import monotonic

    from sqlalchemy import text
    from test_official_writer_fence import wait_for_blockers

    factory, admin, _, _, page = docs_source
    holder = factory()
    worker_pids = []
    failures, warnings = [], []
    original_persist = collab._persist_docs_runtime_state_sync

    def observe_persist(*args, **kwargs):
        try:
            return original_persist(*args, **kwargs)
        except Exception as error:
            failures.append(error)
            raise

    monkeypatch.setattr(collab, "_persist_docs_runtime_state_sync", observe_persist)
    monkeypatch.setattr(
        collab.logger, "warning", lambda message, *args: warnings.append(message % args)
    )
    try:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        holder.scalar(
            select(NativeDocPage)
            .where(NativeDocPage.id == page["source_page_id"])
            .with_for_update()
        )

        def observed_factory():
            db = factory()
            worker_pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            return db

        async def exercise():
            hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="blocked-sql"))
            hub._session_factory = observed_factory
            monkeypatch.setattr(hub._settings, "collab_cleanup_timeout_seconds", 1.5)
            monkeypatch.setattr(hub, "_schedule_flush", lambda runtime: None)
            runtime = await hub.get_room(_context(page, admin), None)
            Y.apply_update(
                runtime.room.ydoc, blocks_to_yjs_state(_paragraph_blocks("Must roll back"))
            )
            runtime.flush_task = asyncio.create_task(hub._flush_runtime(runtime))
            await _eventually(lambda: bool(worker_pids))
            await asyncio.to_thread(wait_for_blockers, factory, worker_pids[0], {holder_pid})
            started = monotonic()
            shutdown = asyncio.create_task(hub.shutdown())
            try:
                # wait(), unlike wait_for(), does not itself wait for cancellation
                # acknowledgement. Even a regression reaches finally and releases
                # only our test lock, so the failing test cannot strand the DB.
                done, _ = await asyncio.wait({shutdown}, timeout=4.5)
                assert shutdown in done, "Shutdown waited past its SQL budgets on a held row lock"
                await shutdown
                assert monotonic() - started < 4.5
                assert not hub._rooms and not hub._disposals
                assert runtime.room.ydoc is None
                with factory() as db:
                    assert (
                        db.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": holder_pid}) == []
                    )
                    assert db.get(NativeDocPage, page["source_page_id"]).content_blocks == []
                    assert db.scalar(select(DocsCollabDocument)) is None
            finally:
                # Failure cleanup releases only this disposable test's lock.
                holder.rollback()
                await shutdown
                await hub.shutdown()

        asyncio.run(exercise())
        assert failures and all(collab._is_persistence_timeout(error) for error in failures)
        assert any(
            getattr(getattr(error, "orig", None), "sqlstate", None) in {"57014", "55P03"}
            for error in failures
        )
        assert any("Docs collaboration persistence timed out" in warning for warning in warnings)
        assert all("UPDATE docs_native_doc_pages" not in warning for warning in warnings)
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.parametrize("identity", [WriterIdentity(SUITE_SCOPE, "legacy", 2)])
def test_untagged_relay_never_adopts_a_later_local_identity(identity, monkeypatch):
    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="future"))
        hub.writer_identity = identity  # Trusted runtime composition simulation, never wire input.
        monkeypatch.setattr(
            hub, "require_writer", lambda: pytest.fail("Untagged future identity was admitted")
        )
        runtime = SimpleNamespace(metadata={}, room_key="future-room")
        await hub._apply_remote_relay_message(
            runtime,
            json.dumps(
                {
                    "instance_id": "old",
                    "room_key": runtime.room_key,
                    "type": "yjs_update",
                    "data": "invalid",
                }
            ).encode(),
        )
        await hub.shutdown()

    asyncio.run(exercise())
