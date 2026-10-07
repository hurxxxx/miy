"""Pinned writer checks and actual source preservation across Docs WS drain."""

import asyncio
import base64
from dataclasses import asdict
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect
import y_py as Y

from miy_api.core.db import official_writer_unavailable
from miy_api.domains.collaboration.yjs_runtime import InProcessCollabBus
from miy_api.domains.docs import collab, router as docs_router
from miy_api.domains.docs.collab import (
    CollabPageContext,
    DocsCollabHub,
    make_page_ref,
    make_room_key,
    writer_close_choice,
)
from miy_api.domains.docs.collab_codec import blocks_to_yjs_state, yjs_state_to_blocks
from miy_api.domains.docs.models import DocsCollabDocument, NativeDocPage
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_docs_collab import _paragraph_blocks
from test_official_writer_docs import docs_source as docs_source
from test_official_writer_fence import change, writer as writer


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


def test_docs_close_choice_recognizes_only_exact_localized_writer_failure():
    assert writer_close_choice(official_writer_unavailable()) == (
        1013,
        "official_writer_unavailable",
    )
    assert writer_close_choice(HTTPException(503, "official_apps.writer_unavailable")) is None
    assert writer_close_choice(HTTPException(403)) is None


@pytest.mark.parametrize("generation_advanced", [False, True])
def test_existing_collab_noop_session_and_ws_do_not_adopt_new_generation(
    client, docs_source, generation_advanced
):
    factory, admin, headers, _, page = docs_source
    session, ws = _paths(page)
    assert client.get(session, headers=headers).status_code == 200
    with factory.begin() as db:
        change(db, admin, state="active" if generation_advanced else "draining")
    response = client.get(session, headers=headers)
    assert response.status_code == 503
    assert response.json()["code"] == "official_apps.writer_unavailable"
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(ws) as connection:
            connection.send_json({"type": "auth", "token": admin["token"]})
            connection.receive_bytes()
    assert denied.value.code == 1013
    assert denied.value.reason == "official_writer_unavailable"
    assert client.app.state.docs_collab.writer_identity.generation == 1


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


def test_two_docs_hubs_reject_mismatched_relay_and_each_check_authoritative_writer(
    docs_source, monkeypatch
):
    factory, admin, _, _, page = docs_source

    async def exercise():
        # Same bus models Redis fanout deterministically; each hub has its own
        # runtime/identity and independently opens a real PostgreSQL session.
        bus = InProcessCollabBus(instance_id="fanout")
        hubs = [DocsCollabHub(instance_id=str(i), bus=bus) for i in range(2)]
        await bus.startup()
        context = _context(page, admin)
        for hub in hubs:
            monkeypatch.setattr(hub, "_schedule_flush", lambda runtime: None)
        try:
            one, two = [await hub.get_room(context, None) for hub in hubs]
            update = blocks_to_yjs_state(_paragraph_blocks("Relayed but uncommitted"))
            wrong = {
                "instance_id": "foreign",
                "room_key": context.room_key,
                "type": "yjs_update",
                "data": base64.b64encode(update).decode(),
                "writer": asdict(WriterIdentity(SUITE_SCOPE, "legacy", 2)),
            }
            before = bytes(Y.encode_state_as_update(two.room.ydoc))
            await hubs[1]._apply_remote_relay_message(two, json.dumps(wrong).encode())
            assert bytes(Y.encode_state_as_update(two.room.ydoc)) == before
            Y.apply_update(one.room.ydoc, update)
            await _eventually(
                lambda: (
                    yjs_state_to_blocks(Y.encode_state_as_update(two.room.ydoc))
                    == yjs_state_to_blocks(update)
                )
            )
            with factory.begin() as db:
                change(db, admin)
            # Matching old generation still cannot bypass the live DB check.
            wrong["writer"] = asdict(hubs[1].writer_identity)
            await hubs[1]._apply_remote_relay_message(two, json.dumps(wrong).encode())
            assert context.room_key not in hubs[1]._rooms
            assert await hubs[0]._flush_runtime(one) is False
            assert context.room_key not in hubs[0]._rooms
        finally:
            for hub in hubs:
                await hub.shutdown()

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


def test_room_fenced_between_lookup_and_connection_admission_returns_retryable_failure():
    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="slot-fence"))
        context = CollabPageContext(
            page_ref="native_doc_page__unit",
            source_type="native_doc_page",
            source_page_id="unit",
            room_key="native_doc_page:unit",
            can_edit=True,
            content_blocks=[],
            default_actor_user_id="unit",
        )
        try:
            runtime = await hub.get_room(context, None)
            hub.fence_runtime(runtime)
            with pytest.raises(HTTPException) as denied:
                await hub.acquire_connection_slot(runtime, "unit")
            assert writer_close_choice(denied.value) == (1013, "official_writer_unavailable")
            assert runtime.active_connection_count == 0
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("generation", [True, 1.0, None, 2])
def test_relay_requires_exact_integer_generation_before_database_or_yjs_access(
    monkeypatch, generation
):
    def unexpected_database_access():
        raise AssertionError("Invalid relay identity reached the database")

    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="invalid-relay"))
        monkeypatch.setattr(hub, "require_writer", unexpected_database_access)
        context = CollabPageContext(
            page_ref="native_doc_page__unit",
            source_type="native_doc_page",
            source_page_id="unit",
            room_key="native_doc_page:unit",
            can_edit=True,
            content_blocks=[],
            default_actor_user_id="unit",
        )
        try:
            runtime = await hub.get_room(context, None)
            before = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            payload = {
                "instance_id": "foreign",
                "room_key": runtime.room_key,
                "writer": asdict(hub.writer_identity) | {"generation": generation},
                "type": "yjs_update",
                "data": "not-a-valid-update",
            }
            await hub._apply_remote_relay_message(runtime, json.dumps(payload).encode())
            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == before
            hub.fence_runtime(runtime)
        finally:
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


@pytest.mark.parametrize("next_state", ["draining", "active"])
def test_initial_untagged_legacy_relay_and_tagged_return_are_bidirectional(
    client, docs_source, monkeypatch, next_state
):
    factory, admin, _, _, page = docs_source

    async def exercise():
        bus = InProcessCollabBus(instance_id="mixed-version")
        hub = DocsCollabHub(instance_id="current", bus=bus)
        await hub.startup()
        context = _context(page, admin)
        monkeypatch.setattr(hub, "_schedule_flush", lambda runtime: None)
        old_subscription = await bus.create_pubsub(context.room_key)
        old_doc = Y.YDoc()
        try:
            runtime = await hub.get_room(context, None)
            initial = blocks_to_yjs_state(_paragraph_blocks("Old producer edit"))
            Y.apply_update(old_doc, initial)
            # Exact original wire shape; there was no writer field before this change.
            await bus.publish(
                context.room_key,
                {
                    "instance_id": "old",
                    "room_key": context.room_key,
                    "type": "yjs_update",
                    "data": base64.b64encode(initial).decode(),
                },
            )
            await _eventually(
                lambda: (
                    yjs_state_to_blocks(Y.encode_state_as_update(runtime.room.ydoc))
                    == yjs_state_to_blocks(initial)
                )
            )
            with runtime.room.ydoc.begin_transaction() as transaction:
                runtime.room.ydoc.get_text("mixed-version-proof").insert(
                    transaction, 0, "Return edit"
                )
            # Original receiver ignores unknown fields and applies the same data.
            # This is a wire-compatibility check, not execution of an old API binary.
            async with asyncio.timeout(5):
                while True:
                    message = await old_subscription.get_message(timeout=0.1)
                    if message is None:
                        continue
                    payload = json.loads(message["data"])
                    if payload["instance_id"] == "current" and payload["type"] == "yjs_update":
                        assert payload["writer"] == asdict(collab.DOCS_WRITER_IDENTITY)
                        Y.apply_update(old_doc, base64.b64decode(payload["data"]))
                        if str(old_doc.get_text("mixed-version-proof")) == "Return edit":
                            break
            with factory.begin() as db:
                change(db, admin, state=next_state)
            before = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            # The absent-tag compatibility path must perform a new DB check on
            # every receive, and cannot retain admission from the prior frame.
            await hub._apply_remote_relay_message(
                runtime,
                json.dumps(
                    {
                        "instance_id": "old",
                        "room_key": context.room_key,
                        "type": "yjs_update",
                        "data": base64.b64encode(initial).decode(),
                    }
                ).encode(),
            )
            assert runtime.metadata["writer_fenced"] == "true"
            assert context.room_key not in hub._rooms
            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == before
        finally:
            await hub.shutdown()
            del old_doc

    asyncio.run(exercise())
    with factory() as db:
        assert db.get(NativeDocPage, page["source_page_id"]).content_blocks == []


@pytest.mark.parametrize(
    "identity",
    [
        WriterIdentity(SUITE_SCOPE, "legacy", 2),
        WriterIdentity(SUITE_SCOPE, "legacy", 1, "sha256:" + "a" * 64),
        WriterIdentity(SUITE_SCOPE, "official-suite", 1),
    ],
)
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


@pytest.mark.parametrize("wire_identity", [None, {}, {"generation": 1}, [], "legacy"])
def test_explicit_invalid_relay_identity_cannot_use_absent_tag_compatibility(
    wire_identity, monkeypatch
):
    async def exercise():
        hub = DocsCollabHub(bus=InProcessCollabBus(instance_id="invalid"))
        monkeypatch.setattr(
            hub, "require_writer", lambda: pytest.fail("Invalid explicit identity was admitted")
        )
        runtime = SimpleNamespace(metadata={}, room_key="invalid-room")
        await hub._apply_remote_relay_message(
            runtime,
            json.dumps(
                {
                    "instance_id": "old",
                    "room_key": runtime.room_key,
                    "type": "yjs_update",
                    "writer": wire_identity,
                    "data": "invalid",
                }
            ).encode(),
        )
        await hub.shutdown()

    asyncio.run(exercise())
