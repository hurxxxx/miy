"""Explicit native GC drains parallel SQL owners across hubs and event loops."""

import asyncio
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session
import y_py as Y

from miy_api.domains.collaboration import yjs_runtime as native
from miy_api.domains.docs import collab as docs
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state
from miy_api.domains.whiteboard import collab as whiteboard
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_collab_persistence import persistence_world as persistence_world  # noqa: F401


async def eventually(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


def test_pure_four_parallel_readers_drain_before_priority_disposal_and_new_reader():
    async def exercise():
        coordinator = native.NativePersistenceGC()
        release, disposing, dispose_release, late_entered = (asyncio.Event() for _ in range(4))
        active, maximum, order = 0, 0, []

        async def read():
            nonlocal active, maximum
            async with coordinator.persistence():
                active += 1
                maximum = max(maximum, active)
                try:
                    await release.wait()
                finally:
                    active -= 1

        async def dispose():
            async with coordinator.disposal():
                assert active == 0
                order.append("disposal")
                disposing.set()
                await dispose_release.wait()

        async def late_read():
            async with coordinator.persistence():
                order.append("new_reader")
                late_entered.set()

        readers = [asyncio.create_task(read()) for _ in range(4)]
        await eventually(lambda: active == 4)
        disposal = asyncio.create_task(dispose())
        await asyncio.sleep(0)  # Disposal has queued before the new reader.
        late = asyncio.create_task(late_read())
        try:
            for _ in range(4):
                await asyncio.sleep(0)
            assert maximum == active == 4
            assert not disposing.is_set() and not late_entered.is_set()
            release.set()
            await disposing.wait()
            assert not late_entered.is_set()
            dispose_release.set()
            await asyncio.gather(*readers, disposal, late)
            assert order == ["disposal", "new_reader"]
        finally:
            release.set()
            dispose_release.set()
            await asyncio.gather(*readers, disposal, late, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["reader", "disposal"])
def test_pure_cancel_after_reserved_grant_before_future_delivery_releases_exactly_once(kind):
    async def exercise():
        coordinator = native.NativePersistenceGC()
        blocker = coordinator.disposal() if kind == "reader" else coordinator.persistence()
        await blocker.__aenter__()
        entered = []

        async def pending():
            lease = coordinator.persistence() if kind == "reader" else coordinator.disposal()
            async with lease:
                entered.append(True)

        task = asyncio.create_task(pending())
        await asyncio.sleep(0)
        # __aexit__ reserves and schedules delivery synchronously; cancel before
        # yielding to that callback, exercising the grant/cancel race itself.
        await blocker.__aexit__(None, None, None)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert entered == []
        async with asyncio.timeout(1), coordinator.disposal():
            pass
        async with asyncio.timeout(1), coordinator.persistence():
            pass

    asyncio.run(exercise())


def test_pure_disposal_waits_across_event_loop_threads_and_wakes_on_its_own_loop():
    coordinator = native.NativePersistenceGC()
    foreign_entered, foreign_release, foreign_finished = Event(), Event(), Event()
    failures = []

    def foreign():
        async def exercise():
            async with coordinator.persistence():
                foreign_entered.set()
                await eventually(foreign_release.is_set)

        try:
            asyncio.run(exercise())
        except BaseException as error:
            failures.append(type(error))
        finally:
            foreign_finished.set()

    thread = Thread(target=foreign)
    thread.start()

    async def exercise():
        await eventually(foreign_entered.is_set)
        owner = get_ident()
        disposed, late_entered = asyncio.Event(), asyncio.Event()
        order = []

        async def dispose():
            async with coordinator.disposal():
                assert get_ident() == owner
                order.append("disposal")
                disposed.set()

        async def late_read():
            async with coordinator.persistence():
                assert get_ident() == owner
                order.append("reader")
                late_entered.set()

        disposal = asyncio.create_task(dispose())
        await asyncio.sleep(0)
        reader = asyncio.create_task(late_read())
        try:
            for _ in range(8):
                await asyncio.sleep(0)
            # Our event loop remains responsive while a different loop holds SQL.
            assert not disposed.is_set() and not late_entered.is_set()
            foreign_release.set()
            await asyncio.wait_for(asyncio.gather(disposal, reader), 3)
            assert order == ["disposal", "reader"]
        finally:
            foreign_release.set()
            await asyncio.gather(disposal, reader, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        foreign_release.set()
        thread.join(timeout=6)
    assert not thread.is_alive() and foreign_finished.is_set() and failures == []


def test_pure_native_release_cancellation_keeps_owner_until_shared_drain_and_collect(monkeypatch):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    collections = []
    monkeypatch.setattr(native.gc, "collect", lambda: collections.append(get_ident()))

    async def exercise():
        owner = get_ident()
        room = SimpleNamespace(on_message=object(), clients=[], awareness=object(), ydoc=Y.YDoc())
        original = room.ydoc
        lease = native.native_persistence_lease()
        await lease.__aenter__()
        disposal = asyncio.create_task(native.release_yroom_thread_bound_state(room))
        try:
            for _ in range(3):
                await asyncio.sleep(0)
            disposal.cancel()
            await asyncio.sleep(0)
            disposal.cancel()
            await asyncio.sleep(0)
            assert not disposal.done() and room.ydoc is original and collections == []
        finally:
            await lease.__aexit__(None, None, None)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(disposal, 1)
        assert room.ydoc is None and room.awareness is None and collections == [owner]
        async with asyncio.timeout(1), native.native_persistence_lease():
            pass

    asyncio.run(exercise())


def test_pure_failed_explicit_collect_still_reopens_snapshot_admission(monkeypatch):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())

    def failed_collect():
        raise RuntimeError("synthetic_collect_failure")

    monkeypatch.setattr(native.gc, "collect", failed_collect)

    async def exercise():
        room = SimpleNamespace(on_message=None, clients=[], awareness=None, ydoc=Y.YDoc())
        with pytest.raises(RuntimeError, match="synthetic_collect_failure"):
            await native.release_yroom_thread_bound_state(room)
        assert room.ydoc is None
        async with asyncio.timeout(1), native.native_persistence_lease():
            pass

    asyncio.run(exercise())


@pytest.mark.parametrize("persisting", ["whiteboard", "docs"])
def test_genuine_other_app_disposal_drains_actual_transaction_close_before_owner_gc(
    persistence_world, monkeypatch, persisting
):
    c = persistence_world
    close_entered, close_release = Event(), Event()
    commits, collections, worker_threads = [], [], []
    original_collect = native.gc.collect

    def observed_collect():
        collections.append(get_ident())
        return original_collect()

    monkeypatch.setattr(native.gc, "collect", observed_collect)

    class ObservedSession(Session):
        def commit(self):
            value = super().commit()
            commits.append(True)
            return value

        def close(self):
            super().close()
            close_entered.set()
            assert close_release.wait(5), "Synthetic transaction cleanup was not released"

    def factory():
        worker_threads.append(get_ident())
        return ObservedSession(c.engine, autoflush=False)

    async def exercise():
        owner = get_ident()
        board_hub = whiteboard.WhiteboardCollabHub(
            bus=native.InProcessCollabBus(instance_id="gc-board")
        )
        docs_hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="gc-docs"))
        hubs = (board_hub, docs_hub)
        for hub in hubs:
            await hub.startup()
            hub._settings = hub._settings.model_copy(
                update={"collab_snapshot_debounce_ms": 60000, "collab_cleanup_timeout_seconds": 1}
            )
        board = await board_hub.get_room(c.context, c.yjs)
        actor = c.world.state["admin"]["user"]["id"]
        page = c.world.ids["page"]
        doc_context = docs.CollabPageContext(
            page_ref=docs.make_page_ref("native_doc_page", page),
            source_type="native_doc_page",
            source_page_id=page,
            room_key=docs.make_room_key("native_doc_page", page),
            can_edit=True,
            content_blocks=[],
            default_actor_user_id=actor,
        )
        doc = await docs_hub.get_room(
            doc_context,
            blocks_to_yjs_state(
                [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Synthetic native drain"}],
                    }
                ]
            ),
        )
        saving_hub, saving_room, disposing_hub, disposing_room = (
            (board_hub, board, docs_hub, doc)
            if persisting == "whiteboard"
            else (docs_hub, doc, board_hub, board)
        )
        saving_hub._session_factory = factory
        saving = disposal = None
        try:
            saving = asyncio.create_task(saving_hub._flush_runtime(saving_room))
            await eventually(close_entered.is_set)
            assert commits == [True] and len(worker_threads) == 1
            assert worker_threads[0] != owner
            disposing_hub._rooms.pop(disposing_room.room_key)
            disposing_hub._stop_room(disposing_room)
            await asyncio.gather(disposing_room.room_task, return_exceptions=True)
            disposal = asyncio.create_task(disposing_hub._release_room_state(disposing_room))
            for _ in range(5):
                await asyncio.sleep(0)
            assert collections == [] and disposing_room.room.ydoc is not None
            assert not disposal.done() and not saving.done()
            close_release.set()
            assert await asyncio.wait_for(saving, 3) is True
            await asyncio.wait_for(disposal, 3)
            assert collections == [owner] and disposing_room.room.ydoc is None
            if persisting == "whiteboard":
                assert board.persistence_outcome.status == "acknowledged"
        finally:
            close_release.set()
            await asyncio.gather(
                *(task for task in (saving, disposal) if task is not None), return_exceptions=True
            )
            docs_hub.fence_runtime(doc)
            await asyncio.gather(*(hub.shutdown() for hub in hubs))

    try:
        asyncio.run(exercise())
    finally:
        close_release.set()


@pytest.mark.parametrize("closing,cancel_parent", [("last_disconnect", False), ("shutdown", True)])
def test_genuine_docs_final_save_retains_native_state_past_cleanup_budget_until_admission(
    persistence_world, monkeypatch, closing, cancel_parent
):
    c = persistence_world
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    opened, committed, closed = [], [], []

    class ObservedSession(Session):
        def commit(self):
            value = super().commit()
            committed.append(True)
            return value

        def close(self):
            super().close()
            closed.append(True)

    def factory():
        opened.append(True)
        return ObservedSession(c.engine, autoflush=False)

    async def exercise():
        hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="docs-final-drain"))
        await hub.startup()
        hub._settings = hub._settings.model_copy(
            update={"collab_snapshot_debounce_ms": 60000, "collab_cleanup_timeout_seconds": 1}
        )
        actor, page = c.world.state["admin"]["user"]["id"], c.world.ids["page"]
        context = docs.CollabPageContext(
            docs.make_page_ref("native_doc_page", page),
            "native_doc_page",
            page,
            docs.make_room_key("native_doc_page", page),
            True,
            [],
            actor,
        )
        runtime = await hub.get_room(context, None)
        hub._session_factory = factory
        with runtime.room.ydoc.begin_transaction() as transaction:
            runtime.room.ydoc.get_map("synthetic").set(transaction, "marker", "final-edit")
        expected = bytes(Y.encode_state_as_update(runtime.room.ydoc))
        assert runtime.flush_task is not None
        blocker = native.native_persistence_lease()
        await blocker.__aenter__()
        orphan = SimpleNamespace(on_message=None, clients=[], awareness=None, ydoc=Y.YDoc())
        disposal = asyncio.create_task(native.release_yroom_thread_bound_state(orphan))
        finishing = None
        try:
            for _ in range(4):
                await asyncio.sleep(0)
            finishing = asyncio.create_task(
                hub.cleanup_room(runtime.room_key, expected_runtime=runtime)
                if closing == "last_disconnect"
                else hub.shutdown()
            )
            await eventually(lambda: runtime.metadata.get("disposing"))
            # A real native GC waiter keeps new SQL admission closed beyond the
            # unchanged one-second cleanup/SQL budget. This is not SQL time.
            await asyncio.sleep(1.2)
            assert opened == committed == closed == []
            assert runtime.room.ydoc is not None and not finishing.done()
            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == expected
            if cancel_parent:
                finishing.cancel()
                await asyncio.sleep(0)
                finishing.cancel()
                for _ in range(4):
                    await asyncio.sleep(0)
                assert not finishing.done() and runtime.room.ydoc is not None
                assert opened == []
        finally:
            await blocker.__aexit__(None, None, None)
            await asyncio.wait_for(disposal, 5)
            if finishing is not None:
                result = await asyncio.wait_for(
                    asyncio.gather(finishing, return_exceptions=True), 5
                )
            await hub.shutdown()
        assert opened == committed == closed == [True]
        assert runtime.room.ydoc is None and not hub._disposals
        if cancel_parent:
            assert isinstance(result[0], asyncio.CancelledError)
        else:
            assert result == [None]
        with Session(c.engine) as db:
            saved = db.query(docs.DocsCollabDocument).filter_by(room_key=context.room_key).one()
            assert saved.yjs_state == expected
            restored = Y.YDoc()
            Y.apply_update(restored, saved.yjs_state)
            assert restored.get_map("synthetic").get("marker") == "final-edit"

    asyncio.run(exercise())
