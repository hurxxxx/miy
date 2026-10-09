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


def test_pure_pending_disposal_cancel_withdraws_priority_without_draining_active_reader():
    async def exercise():
        coordinator = native.NativePersistenceGC()
        lease = coordinator.persistence()
        await lease.__aenter__()
        later_entered = asyncio.Event()

        async def dispose():
            async with coordinator.disposal():
                pytest.fail("cancelled_disposal_entered")

        async def read():
            async with coordinator.persistence():
                later_entered.set()

        disposal = asyncio.create_task(dispose())
        await asyncio.sleep(0)
        reader = asyncio.create_task(read())
        try:
            await asyncio.sleep(0)
            assert not later_entered.is_set()
            disposal.cancel()
            with pytest.raises(asyncio.CancelledError):
                await disposal
            # The first reader is still held: withdrawal must reopen readers now.
            await asyncio.wait_for(later_entered.wait(), 1)
            await reader
        finally:
            await lease.__aexit__(None, None, None)
            await asyncio.gather(disposal, reader, return_exceptions=True)
        async with asyncio.timeout(1), coordinator.disposal():
            pass

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


def test_pure_cancel_queued_reader_then_active_reader_leaves_no_exclusive_or_reader_leak():
    async def exercise():
        coordinator = native.NativePersistenceGC()
        entered, release = asyncio.Event(), asyncio.Event()

        async def read():
            async with coordinator.persistence():
                entered.set()
                await release.wait()

        async with coordinator.disposal():
            queued = asyncio.create_task(read())
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            assert not entered.is_set()
        reader = asyncio.create_task(read())
        await entered.wait()
        reader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader
        async with asyncio.timeout(1), coordinator.disposal():
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


@pytest.mark.parametrize("app", ["docs", "whiteboard"])
@pytest.mark.parametrize("cancel_pending", [False, True])
def test_pure_hub_waits_before_session_and_budget_and_can_cancel_before_shared_grant(
    monkeypatch, app, cancel_pending
):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    module = docs if app == "docs" else whiteboard
    opened = []

    def factory():
        opened.append("session")
        return object()

    def persist(session_factory, **kwargs):
        assert kwargs["timeout_seconds"] == 1
        session_factory()
        return (
            None
            if app == "docs"
            else whiteboard.WhiteboardPersistenceResult("acknowledged", "commit_acknowledged")
        )

    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            instance_id="pure-drain",
            collab_cleanup_timeout_seconds=1,
            collab_snapshot_debounce_ms=60000,
        ),
    )
    monkeypatch.setattr(module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        module,
        "_persist_docs_runtime_state_sync" if app == "docs" else "persist_runtime_yjs_state",
        persist,
    )

    async def exercise():
        hub_type = docs.DocsCollabHub if app == "docs" else whiteboard.WhiteboardCollabHub
        hub = hub_type(bus=native.InProcessCollabBus(instance_id="pure-admission"))
        await hub.startup()
        context = (
            docs.CollabPageContext(
                "page", "native_doc_page", "page", "native_doc_page:page", True, [], "actor"
            )
            if app == "docs"
            else whiteboard.WhiteboardCollabContext(
                "board", "whiteboard:board", True, {}, "actor", "collab"
            )
        )
        room = await hub.get_room(context, None)
        blocker = native.native_persistence_lease()
        await blocker.__aenter__()
        orphan = SimpleNamespace(on_message=None, clients=[], awareness=None, ydoc=Y.YDoc())
        disposal = asyncio.create_task(native.release_yroom_thread_bound_state(orphan))
        saving = None
        try:
            for _ in range(3):
                await asyncio.sleep(0)
            saving = asyncio.create_task(hub._flush_runtime(room))
            for _ in range(3):
                await asyncio.sleep(0)
            assert opened == [] and not saving.done() and orphan.ydoc is not None
            if cancel_pending:
                saving.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await saving
                assert opened == []
        finally:
            await blocker.__aexit__(None, None, None)
        await asyncio.wait_for(disposal, 5)
        if not cancel_pending:
            assert await asyncio.wait_for(saving, 5) is True
        assert opened == ([] if cancel_pending else ["session"])
        hub._rooms.pop(room.room_key)
        hub._stop_room(room)
        await asyncio.gather(room.room_task, return_exceptions=True)
        await hub._release_room_state(room)
        await hub.shutdown()

    asyncio.run(exercise())


def test_pure_docs_admission_wait_keeps_original_snapshot_and_actor(monkeypatch):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    monkeypatch.setattr(
        docs,
        "get_settings",
        lambda: SimpleNamespace(
            instance_id="pure-original-capture",
            collab_cleanup_timeout_seconds=1,
            collab_snapshot_debounce_ms=60000,
        ),
    )
    monkeypatch.setattr(docs, "get_session_factory", lambda: lambda: None)
    captured = []

    def persist(_factory, **kwargs):
        captured.append((kwargs["yjs_state"], kwargs["actor_user_id"]))

    monkeypatch.setattr(docs, "_persist_docs_runtime_state_sync", persist)

    async def exercise():
        hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="original-capture"))
        monkeypatch.setattr(hub, "_schedule_flush", lambda _runtime: None)
        await hub.startup()
        context = docs.CollabPageContext(
            "page", "native_doc_page", "page", "native_doc_page:page", True, [], "first-actor"
        )
        room = await hub.get_room(context, None)
        original = bytes(Y.encode_state_as_update(room.room.ydoc))
        blocker = native.native_persistence_lease()
        await blocker.__aenter__()
        orphan = SimpleNamespace(on_message=None, clients=[], awareness=None, ydoc=Y.YDoc())
        disposal = asyncio.create_task(native.release_yroom_thread_bound_state(orphan))
        saving = None
        try:
            for _ in range(3):
                await asyncio.sleep(0)
            saving = asyncio.create_task(hub._flush_runtime(room))
            for _ in range(3):
                await asyncio.sleep(0)
            assert captured == [] and not saving.done()
            room.last_editor_user_id = "later-actor"
            with room.room.ydoc.begin_transaction() as transaction:
                room.room.ydoc.get_map("synthetic").set(transaction, "marker", "later-state")
            assert bytes(Y.encode_state_as_update(room.room.ydoc)) != original
        finally:
            await blocker.__aexit__(None, None, None)
        await asyncio.wait_for(disposal, 5)
        assert await asyncio.wait_for(saving, 5) is True
        assert captured == [(original, "first-actor")]
        hub._rooms.pop(room.room_key)
        hub._stop_room(room)
        await asyncio.gather(room.room_task, return_exceptions=True)
        await hub._release_room_state(room)
        await hub.shutdown()

    asyncio.run(exercise())


def test_pure_docs_fence_during_shared_admission_opens_no_session(monkeypatch):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    monkeypatch.setattr(
        docs,
        "get_settings",
        lambda: SimpleNamespace(
            instance_id="pure-fenced-admission",
            collab_cleanup_timeout_seconds=1,
            collab_snapshot_debounce_ms=60000,
        ),
    )
    opened = []
    monkeypatch.setattr(docs, "get_session_factory", lambda: lambda: opened.append("session"))

    def persist(session_factory, **_kwargs):
        session_factory()

    monkeypatch.setattr(docs, "_persist_docs_runtime_state_sync", persist)

    async def exercise():
        hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="fenced-admission"))
        monkeypatch.setattr(hub, "_schedule_flush", lambda _runtime: None)
        await hub.startup()
        context = docs.CollabPageContext(
            "page", "native_doc_page", "page", "native_doc_page:page", True, [], "actor"
        )
        room = await hub.get_room(context, None)
        blocker = native.native_persistence_lease()
        await blocker.__aenter__()
        orphan = SimpleNamespace(on_message=None, clients=[], awareness=None, ydoc=Y.YDoc())
        disposal = asyncio.create_task(native.release_yroom_thread_bound_state(orphan))
        saving = None
        try:
            for _ in range(3):
                await asyncio.sleep(0)
            saving = asyncio.create_task(hub._flush_runtime(room))
            for _ in range(3):
                await asyncio.sleep(0)
            assert opened == [] and not saving.done() and room.flush_task is None
            hub.fence_runtime(room)
            assert room.metadata["writer_fenced"] and room.room_key not in hub._rooms
            for _ in range(3):
                await asyncio.sleep(0)
            assert opened == [] and not saving.done()
        finally:
            await blocker.__aexit__(None, None, None)
        await asyncio.wait_for(disposal, 5)
        assert await asyncio.wait_for(saving, 5) is False
        await hub.shutdown()
        assert opened == [] and room.room.ydoc is None

    asyncio.run(exercise())


def test_pure_docs_native_automatic_debounce_completes_persistence_before_stop(monkeypatch):
    monkeypatch.setattr(native, "_native_persistence_gc", native.NativePersistenceGC())
    monkeypatch.setattr(
        docs,
        "get_settings",
        lambda: SimpleNamespace(
            instance_id="pure-native-automatic-save",
            collab_cleanup_timeout_seconds=1,
            collab_snapshot_debounce_ms=10,
        ),
    )
    opened, persisted, completed = [], [], Event()
    monkeypatch.setattr(docs, "get_session_factory", lambda: lambda: opened.append("session"))

    def persist(session_factory, **kwargs):
        session_factory()
        persisted.append(kwargs["yjs_state"])
        completed.set()

    monkeypatch.setattr(docs, "_persist_docs_runtime_state_sync", persist)

    async def exercise():
        hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="native-automatic-save"))
        await hub.startup()
        context = docs.CollabPageContext(
            "page", "native_doc_page", "page", "native_doc_page:page", True, [], "actor"
        )
        room = await hub.get_room(context, None)
        try:
            with room.room.ydoc.begin_transaction() as transaction:
                room.room.ydoc.get_map("synthetic").set(transaction, "marker", "ordinary-edit")
            assert room.flush_task is not None
            await eventually(completed.is_set)
            await asyncio.wait_for(room.flush_task, 5)
            assert opened == ["session"] and len(persisted) == 1
            saved = Y.YDoc()
            Y.apply_update(saved, persisted[0])
            assert saved.get_map("synthetic").get("marker") == "ordinary-edit"
            assert room.room.ydoc is not None and room.room_key in hub._rooms
        finally:
            # Prevent a shutdown final flush from satisfying an absent automatic
            # save; preserve the actual original scheduled lifecycle until here.
            hub.fence_runtime(room)
            await hub.shutdown()

    asyncio.run(exercise())


def test_pure_docs_native_empty_read_skips_save_and_relay_but_delete_only_delta_does_not(
    monkeypatch,
):
    monkeypatch.setattr(
        docs,
        "get_settings",
        lambda: SimpleNamespace(instance_id="pure-native-empty-delta"),
    )
    monkeypatch.setattr(docs, "get_session_factory", lambda: lambda: None)

    async def exercise():
        hub = docs.DocsCollabHub(bus=native.InProcessCollabBus(instance_id="native-empty-delta"))
        await hub.startup()
        document = Y.YDoc()
        content = document.get_map("synthetic")
        with document.begin_transaction() as transaction:
            content.set(transaction, "marker", "delete-me")
        before_delete = bytes(Y.encode_state_vector(document))
        consumed, scheduled, published, observed = [], [], [], []
        runtime = SimpleNamespace(
            room_key="native-empty-delta",
            consume_remote_update_hash=lambda value: consumed.append(value) or False,
        )
        hub._rooms[runtime.room_key] = runtime
        monkeypatch.setattr(hub, "_schedule_flush", lambda value: scheduled.append(value))

        async def publish(value, update, update_hash):
            published.append((value, update, update_hash))

        monkeypatch.setattr(hub, "_publish_update", publish)

        def handle(event):
            update = bytes(event.get_update())
            observed.append(update)
            hub._handle_room_update(runtime, update)

        document.observe_after_transaction(handle)
        try:
            Y.encode_state_as_update(document)
            await asyncio.sleep(0)
            assert observed and all(update == b"\x00\x00" for update in observed)
            assert consumed == scheduled == published == []
            with document.begin_transaction() as transaction:
                content.pop(transaction, "marker")
            deletion = bytes(Y.encode_state_as_update(document, before_delete))
            await asyncio.sleep(0)
            assert deletion != b"\x00\x00" and deletion[0] == 0
            assert scheduled == [runtime]
            assert consumed == [docs.hash_bytes(deletion)]
            assert published == [(runtime, deletion, docs.hash_bytes(deletion))]
            assert content.get("marker") is None
        finally:
            hub._rooms.pop(runtime.room_key)
            await hub.shutdown()

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
