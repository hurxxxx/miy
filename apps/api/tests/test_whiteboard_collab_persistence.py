"""Whiteboard structural persistence: genuine SQL/Yjs red before product changes.

The red_contract cases call the existing admission, hub and persistence APIs.
They do not depend on a new identity field or substitute the persistence function.
All storage and users come from the accepted disposable migrated PG fixture.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from threading import Event, get_ident
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import psycopg
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
import y_py as Y

from miy_api import api_registry
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import User
from miy_api.domains.collaboration.yjs_runtime import InProcessCollabBus
from miy_api.domains.whiteboard import collab, router, scene_state
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)
from test_prepared_whiteboard_source_access import source_world as source_world  # noqa: F401
from test_prepared_whiteboard_source_room import room_world as room_world  # noqa: F401


def _native_state(label):
    doc = Y.YDoc()
    with doc.begin_transaction() as txn:
        doc.get_map("scene").set(txn, "marker", label)
    return bytes(Y.encode_state_as_update(doc))


def _native_label(state):
    doc = Y.YDoc()
    Y.apply_update(doc, state)
    return doc.get_map("scene").get("marker")


async def _eventually(predicate, *, seconds=5):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
def persistence_world(http_world):
    world = http_world
    initial_yjs = _native_state("admitted-r1")
    with world.core() as db:
        user = db.get(User, world.state["member_id"])
        context, record = router._ensure_whiteboard_collab_context(db, user, world.ids["board"])
        record.yjs_state = initial_yjs
        record.updated_at = db.get(Whiteboard, context.whiteboard_id).updated_at + timedelta(
            seconds=1
        )
        db.commit()
        collab_id = record.id
        engine = db.get_bind()
    return SimpleNamespace(
        world=world, context=context, collab_id=collab_id, yjs=initial_yjs, engine=engine
    )


def _stored_state(c):
    with c.world.core() as db:
        board = db.get(Whiteboard, c.context.whiteboard_id)
        records = db.scalars(
            select(WhiteboardCollabDocument).where(
                WhiteboardCollabDocument.whiteboard_id == c.context.whiteboard_id
            )
        ).all()
        return deepcopy(
            (
                board.id,
                board.scene,
                board.updated_at,
                board.trashed_at,
                tuple(
                    (
                        row.id,
                        row.whiteboard_id,
                        row.room_key,
                        row.yjs_state,
                        row.snapshot_scene,
                        row.last_snapshot_at,
                        row.created_at,
                        row.updated_at,
                    )
                    for row in records
                ),
            )
        )


def _collab_mutation_capture(c):
    commands = []

    def observe(_conn, _cursor, statement, *_):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and (
            "whiteboard_collab_documents" in statement
        ):
            commands.append(statement.lstrip().split()[0].upper())

    event.listen(c.engine, "before_cursor_execute", observe)
    return commands, observe


def test_genuine_red_contract_repeated_host_cancel_keeps_worker_and_flush_lock(
    persistence_world,
):
    c = persistence_world
    entered, release, first_closed = Event(), Event(), Event()
    sessions, active, worker_ordinals = [], [], {}

    class ObservedSession(Session):
        def close(self):
            try:
                return super().close()
            finally:
                active.remove(self)
                if self is sessions[0]:
                    first_closed.set()

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        sessions.append(db)
        active.append(db)
        worker_ordinals[get_ident()] = len(sessions)
        return db

    def before_sql(_conn, _cursor, statement, *_):
        if (
            worker_ordinals.get(get_ident()) == 1
            and statement.lstrip().upper().startswith(("SELECT", "UPDATE"))
            and ("whiteboards" in statement or "whiteboard_collab_documents" in statement)
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(8), "The bounded test SQL gate was not released"

    event.listen(c.engine, "before_cursor_execute", before_sql)

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="cancel-join"))
        hub._session_factory = factory
        first = second = None
        try:
            runtime = await hub.get_room(c.context, c.yjs)
            first = asyncio.create_task(hub._flush_runtime(runtime))
            await _eventually(entered.is_set)
            first.cancel()
            await asyncio.sleep(0)
            first.cancel()
            second = asyncio.create_task(hub._flush_runtime(runtime))
            await asyncio.sleep(0.05)
            assert runtime.flush_lock.locked(), "Host cancellation released a live SQL worker lock"
            assert not first.done(), "Host cancellation detached its still-running SQL worker"
            assert len(sessions) == 1 and len(active) == 1
            assert not second.done(), "A later flush passed an unfinished SQL worker"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            await second
            assert first_closed.is_set() and len(sessions) == 2 and active == []
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (first, second) if task is not None), return_exceptions=True
            )
            if sessions:
                await _eventually(first_closed.is_set)
            await _eventually(lambda: not active)
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        event.remove(c.engine, "before_cursor_execute", before_sql)
    assert active == []


async def _release_test_orphan(hub, runtime):
    """Release only the native runtime explicitly unregistered by this fixture."""
    if runtime.room.ydoc is None:
        return
    for task in (runtime.flush_task, runtime.relay_task):
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if runtime.relay_pubsub is not None:
        await hub._bus.close_pubsub(runtime.relay_pubsub, runtime.room_key)
    hub._stop_room(runtime)
    await asyncio.gather(runtime.room_task, return_exceptions=True)
    await hub._release_room_state(runtime)


def test_genuine_red_contract_old_websocket_finalizer_keeps_same_key_replacement(
    persistence_world, monkeypatch
):
    c = persistence_world
    specs = tuple(
        spec
        for spec in api_registry.router_specs("official")
        if spec.source == "miy_api.domains.whiteboard.router" and spec.protection == "public"
    )
    monkeypatch.setattr(api_registry, "router_specs", lambda _: specs)
    app = FastAPI()
    api_registry.register_api_routers(
        app,
        get_settings(),
        composition="official",
        official_auth_session_factory=c.world.factory,
        official_auth_max_concurrent_reads=1,
    )
    old = replacement = None
    with TestClient(app) as client:

        async def create_hub():
            hub = collab.WhiteboardCollabHub(
                bus=InProcessCollabBus(instance_id="old-websocket-finalizer")
            )
            await hub.startup()
            return hub

        hub = client.portal.call(create_hub)
        app.state.whiteboard_collab = hub

        async def replace_runtime():
            resident = hub._rooms[c.context.room_key]
            assert resident.active_connection_count == 1
            # Model a local replacement while the original connection's finally is pending.
            hub._rooms.pop(c.context.room_key)
            incoming = await hub.get_room(c.context, c.yjs)
            assert incoming is not resident and incoming.active_connection_count == 0
            return resident, incoming

        async def assert_replacement_active():
            assert hub._rooms.get(c.context.room_key) is replacement, (
                "The old native websocket finalizer retired its same-key replacement"
            )
            assert replacement.room.ydoc is not None
            await hub.acquire_connection_slot(replacement, c.world.state["member_id"])
            await hub.release_connection_slot(replacement, c.world.state["member_id"])

        async def finish():
            await hub.shutdown()
            if old is not None:
                await _release_test_orphan(hub, old)

        try:
            with client.websocket_connect(
                f"/api/v1/whiteboard/collab/items/{c.context.whiteboard_id}/ws"
            ) as socket:
                socket.send_json({"type": "auth", "token": c.world.token})
                assert socket.receive_bytes()
                old, replacement = client.portal.call(replace_runtime)
            client.portal.call(assert_replacement_active)
        finally:
            client.portal.call(finish)


def _captured_persist(c, *, factory=None, state=None, timeout_seconds=5):
    return scene_state.persist_runtime_yjs_state(
        factory or c.world.core,
        whiteboard_id=c.context.whiteboard_id,
        yjs_state=c.yjs if state is None else state,
        expected_room_key=c.context.room_key,
        expected_collab_id=c.collab_id,
        timeout_seconds=timeout_seconds,
    )


@contextmanager
def _driver_commit_fault(engine, *, after_commit):
    """Inject at actual SQLAlchemy DBAPI dispatch, never at Session.commit.

    The after case calls the real psycopg commit successfully before injecting
    acknowledgement loss. The before case injects failure before DBAPI commit;
    rollback then preserves the uncommitted fixture. No network fault is claimed.
    """
    original = engine.dialect.do_commit
    observation = {"dispatches": 0, "real_driver_commits": 0, "psycopg_driver": False}

    def lose_ack(dbapi_connection):
        observation["dispatches"] += 1
        driver = getattr(dbapi_connection, "driver_connection", dbapi_connection)
        observation["psycopg_driver"] = isinstance(driver, psycopg.Connection)
        assert observation["psycopg_driver"], "Expected the actual owned psycopg driver"
        if after_commit:
            original(dbapi_connection)
            observation["real_driver_commits"] += 1
        raise psycopg.OperationalError("owned_whiteboard_commit_ack_unknown")

    engine.dialect.do_commit = lose_ack
    try:
        yield observation
    finally:
        engine.dialect.do_commit = original


@contextmanager
def _deferred_commit_rejection(engine):
    """Real server rejection at COMMIT in this disposable migrated database."""
    function = "miy_test_whiteboard_reject_commit"
    with engine.begin() as connection:
        assert (
            connection.scalar(
                text("SELECT pg_catalog.to_regprocedure(:name)"),
                {"name": "public." + function + "()"},
            )
            is None
        )
        connection.execute(
            text("""
            CREATE FUNCTION public.miy_test_whiteboard_reject_commit() RETURNS trigger
            LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,pg_temp AS $$
            BEGIN
                RAISE EXCEPTION 'owned_whiteboard_deferred_rejection' USING ERRCODE='23514';
            END;
            $$
        """)
        )
        connection.execute(
            text("""
            CREATE CONSTRAINT TRIGGER miy_test_whiteboard_reject_commit
            AFTER UPDATE ON public.whiteboard_collab_documents
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION public.miy_test_whiteboard_reject_commit()
        """)
        )
    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DROP TRIGGER miy_test_whiteboard_reject_commit "
                    "ON public.whiteboard_collab_documents"
                )
            )
            connection.execute(text("DROP FUNCTION public.miy_test_whiteboard_reject_commit()"))


@pytest.mark.parametrize("transition", ["rotation", "same_key_aba"])
def test_genuine_lock_wait_cas_rechecks_current_incarnation(persistence_world, transition):
    from test_official_writer_fence import wait_for_blockers

    c = persistence_world
    holder = c.world.core()
    held = holder.scalar(
        select(WhiteboardCollabDocument)
        .where(WhiteboardCollabDocument.id == c.collab_id)
        .with_for_update()
    )
    holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
    entered = Event()
    worker_pid = []

    def observe(connection, _cursor, statement, *_):
        if (
            statement.lstrip().upper().startswith("UPDATE")
            and ("whiteboard_collab_documents" in statement)
            and not worker_pid
        ):
            worker_pid.append(connection.connection.driver_connection.info.backend_pid)
            entered.set()

    event.listen(c.engine, "before_cursor_execute", observe)

    async def exercise():
        task = asyncio.create_task(
            asyncio.to_thread(_captured_persist, c, state=_native_state("old-waiting-payload"))
        )
        try:
            await _eventually(entered.is_set)
            await asyncio.to_thread(wait_for_blockers, c.world.core, worker_pid[0], {holder_pid})
            replacement_yjs = _native_state("replacement-after-lock-wait")
            if transition == "rotation":
                held.room_key = c.context.room_key + ":rotated"
                held.yjs_state = replacement_yjs
            else:
                holder.delete(held)
                holder.flush()
                holder.add(
                    WhiteboardCollabDocument(
                        id="opaque-after-lock-wait",
                        whiteboard_id=c.context.whiteboard_id,
                        room_key=c.context.room_key,
                        yjs_state=replacement_yjs,
                        snapshot_scene={"elements": [], "appState": {}, "files": {}},
                    )
                )
            holder.commit()
            expected = _stored_state(c)
            result = await task
            assert result.status == "refused"
            assert _stored_state(c) == expected
            assert _stored_state(c)[4][0][3] == replacement_yjs
        finally:
            holder.rollback()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        holder.rollback()
        holder.close()
        event.remove(c.engine, "before_cursor_execute", observe)


def test_genuine_real_row_lock_deadline_bounds_shutdown_and_releases_session(
    persistence_world,
):
    from test_official_writer_fence import wait_for_blockers

    c = persistence_world
    before = _stored_state(c)
    holder = c.world.core()
    holder.scalar(
        select(WhiteboardCollabDocument)
        .where(WhiteboardCollabDocument.id == c.collab_id)
        .with_for_update()
    )
    holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
    active, opened, worker_pid = [], [], []
    entered = Event()

    class ObservedSession(Session):
        def close(self):
            try:
                return super().close()
            finally:
                active.remove(self)

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        opened.append(db)
        active.append(db)
        return db

    def observe(connection, _cursor, statement, *_):
        if (
            statement.lstrip().upper().startswith("UPDATE")
            and ("whiteboard_collab_documents" in statement)
            and not worker_pid
        ):
            worker_pid.append(connection.connection.driver_connection.info.backend_pid)
            entered.set()

    event.listen(c.engine, "before_cursor_execute", observe)

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="held-lock-deadline"))
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(update={"collab_cleanup_timeout_seconds": 2})
        flush = shutdown = None
        try:
            runtime = await hub.get_room(c.context, _native_state("deadline-unsaved"))
            flush = asyncio.create_task(hub._flush_runtime(runtime))
            runtime.flush_task = flush
            await _eventually(entered.is_set)
            await asyncio.to_thread(wait_for_blockers, c.world.core, worker_pid[0], {holder_pid})
            shutdown = asyncio.create_task(hub.shutdown())
            done, _ = await asyncio.wait({shutdown}, timeout=5)
            assert shutdown in done, "Shutdown detached or waited beyond the SQL deadline"
            await shutdown
            await asyncio.gather(flush, return_exceptions=True)
            assert runtime.persistence_outcome.status == "rejected"
            assert runtime.metadata["persistence_terminal"] == "rejected"
            assert len(opened) == 1 and active == []
            assert runtime.room.ydoc is None
            assert _stored_state(c) == before
            with c.world.core() as db:
                assert db.scalar(text("SHOW statement_timeout")) == "0"
                assert db.scalar(text("SHOW lock_timeout")) == "0"
        finally:
            holder.rollback()
            await asyncio.gather(
                *(task for task in (flush, shutdown) if task is not None), return_exceptions=True
            )
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        holder.rollback()
        holder.close()
        event.remove(c.engine, "before_cursor_execute", observe)


def test_genuine_cancelled_queued_flush_never_opens_second_session(persistence_world):
    c = persistence_world
    entered, release = Event(), Event()
    sessions = []

    def factory():
        db = Session(c.engine, autoflush=False)
        sessions.append(db)
        return db

    def gate(_conn, _cursor, statement, *_):
        if (
            "whiteboard_collab_documents" in statement
            and statement.lstrip().upper().startswith("UPDATE")
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(8), "The owned queued-cancel SQL gate was not released"

    event.listen(c.engine, "before_cursor_execute", gate)

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="queued-cancel"))
        hub._session_factory = factory
        first = queued = None
        try:
            runtime = await hub.get_room(c.context, c.yjs)
            first = asyncio.create_task(hub._flush_runtime(runtime))
            await _eventually(entered.is_set)
            queued = asyncio.create_task(hub._flush_runtime(runtime))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            assert runtime.flush_lock.locked() and len(sessions) == 1
            release.set()
            assert await first is True
            assert runtime.persistence_outcome.status == "acknowledged"
            await hub.shutdown()
            assert len(sessions) == 1
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (first, queued) if task is not None), return_exceptions=True
            )
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        event.remove(c.engine, "before_cursor_execute", gate)


@pytest.mark.parametrize("after_commit", [False, True])
def test_genuine_dbapi_commit_unknown_retains_bytes_and_blocks_same_identity_readmission(
    persistence_world, after_commit
):
    c = persistence_world
    before = _stored_state(c)
    changed = _native_state("actual-driver-commit-unknown")
    opened = []

    def factory():
        db = Session(c.engine, autoflush=False)
        opened.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="dbapi-commit-unknown"))
        hub._session_factory = factory
        runtime = None
        try:
            runtime = await hub.get_room(c.context, changed)
            identity = runtime.persistence_identity
            commands, observe = _collab_mutation_capture(c)
            try:
                with _driver_commit_fault(c.engine, after_commit=after_commit) as driver:
                    assert await hub._flush_runtime(runtime) is False
                    assert driver == {
                        "dispatches": 1,
                        "real_driver_commits": int(after_commit),
                        "psycopg_driver": True,
                    }
                assert runtime.persistence_outcome.status == "unknown"
                assert runtime.metadata["persistence_terminal"] == "unknown"
                assert runtime.retained_yjs_state == changed
                assert runtime.last_acknowledged_yjs_state is None
                assert runtime.persistence_identity == identity
                stored = _stored_state(c)
                if after_commit:
                    assert stored[4][0][3] == changed
                    assert stored[4][0][:3] == before[4][0][:3]
                else:
                    assert stored == before
                # Source observation cannot turn this transaction's missing ACK into history.
                assert runtime.persistence_outcome.status == "unknown"
                attempts = len(commands)
                hub._schedule_flush(runtime)
                await asyncio.sleep(0)
                assert await hub._flush_runtime(runtime) is False
                await hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
                await hub.shutdown()
                for _ in range(2):
                    with pytest.raises(scene_state.WhiteboardPersistenceRefused) as caught:
                        await hub.get_room(c.context, stored[4][0][3])
                    assert str(caught.value) == "whiteboard_persistence_refused"
                    assert caught.value.reason == "unresolved_incarnation"
                assert len(opened) == 1 and len(commands) == attempts
                assert _stored_state(c) == stored
                assert runtime.persistence_identity == identity
                assert runtime.retained_yjs_state == changed
                assert runtime.persistence_outcome.status == "unknown"
                assert runtime.room.ydoc is None
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("rollback_fault", [False, True])
def test_genuine_deferred_server_commit_rejection_requires_successful_rollback(
    persistence_world, rollback_fault
):
    c = persistence_world
    before = _stored_state(c)
    changed = _native_state("must-not-commit")
    opened, rejections = [], []

    class ObservedSession(Session):
        def commit(self):
            try:
                return super().commit()
            except Exception as exc:
                rejections.append(getattr(getattr(exc, "orig", None), "sqlstate", None))
                raise

        def rollback(self):
            result = super().rollback()
            if rollback_fault:
                raise OSError("owned_rollback_completion_unknown")
            return result

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        opened.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="deferred-rejection"))
        hub._session_factory = factory
        try:
            runtime = await hub.get_room(c.context, changed)
            commands, observe = _collab_mutation_capture(c)
            try:
                with _deferred_commit_rejection(c.engine):
                    assert await hub._flush_runtime(runtime) is False
                assert rejections == ["23514"], "Expected a real server COMMIT rejection"
                expected_status = "unknown" if rollback_fault else "rejected"
                assert runtime.persistence_outcome.status == expected_status
                assert runtime.metadata["persistence_terminal"] == expected_status
                assert runtime.retained_yjs_state == changed
                assert _stored_state(c) == before
                attempts = len(commands)
                hub._schedule_flush(runtime)
                assert await hub._flush_runtime(runtime) is False
                await hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
                await hub.shutdown()
                assert len(opened) == 1 and len(commands) == attempts
                assert _stored_state(c) == before
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("invalidate_fault", [True])
def test_genuine_known_commit_ack_survives_close_and_invalidate_fault_without_cleanup_replay(
    persistence_world, invalidate_fault
):
    c = persistence_world
    changed = _native_state("ack-before-cleanup-fault")
    opened, closed, invalidated = [], [], []

    class CleanupFaultSession(Session):
        def close(self):
            super().close()
            closed.append(self)
            raise OSError("owned_session_close_observation_fault")

        def invalidate(self):
            super().invalidate()
            invalidated.append(self)
            if invalidate_fault:
                raise OSError("owned_session_invalidate_observation_fault")

    def factory():
        db = CleanupFaultSession(c.engine, autoflush=False)
        opened.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="ack-cleanup-fault"))
        hub._session_factory = factory
        try:
            runtime = await hub.get_room(c.context, changed)
            commands, observe = _collab_mutation_capture(c)
            try:
                assert await hub._flush_runtime(runtime) is True
                assert runtime.persistence_outcome.status == "acknowledged"
                assert "persistence_terminal" not in runtime.metadata
                assert runtime.retained_yjs_state is None
                assert runtime.last_acknowledged_yjs_state == changed
                assert opened == closed == invalidated
                assert len(opened) == 1 and _stored_state(c)[4][0][3] == changed
                accepted = _stored_state(c)
                attempts = len(commands)
                await hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
                await hub.shutdown()
                assert runtime.persistence_outcome.status == "acknowledged"
                assert len(opened) == 1 and len(commands) == attempts
                assert _stored_state(c) == accepted and runtime.room.ydoc is None
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("shutdown", [True])
def test_genuine_disposal_joins_replaced_debounce_pointer_through_sql_and_session_close(
    persistence_world, shutdown
):
    c = persistence_world
    sql_entered, sql_release, close_entered, close_release = Event(), Event(), Event(), Event()
    opened, active, ordinal = [], [], {}

    class GatedSession(Session):
        def close(self):
            try:
                super().close()
                if len(opened) > 1 and self is opened[1]:
                    close_entered.set()
                    assert close_release.wait(8), "The owned T1 close gate was not released"
            finally:
                active.remove(self)

    def factory():
        db = GatedSession(c.engine, autoflush=False)
        opened.append(db)
        active.append(db)
        ordinal[get_ident()] = len(opened)
        return db

    def gate(_conn, _cursor, statement, *_):
        if ordinal.get(get_ident()) == 2 and (
            statement.lstrip().upper().startswith("UPDATE")
            and "whiteboard_collab_documents" in statement
            and not sql_entered.is_set()
        ):
            sql_entered.set()
            assert sql_release.wait(8), "The owned T1 SQL gate was not released"

    event.listen(c.engine, "before_cursor_execute", gate)

    async def exercise():
        hub = collab.WhiteboardCollabHub(
            bus=InProcessCollabBus(instance_id="debounce-pointer-join")
        )
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(
            update={"collab_snapshot_debounce_ms": 60000, "collab_cleanup_timeout_seconds": 5}
        )
        first = disposing = None
        try:
            runtime = await hub.get_room(c.context, c.yjs)
            assert await hub._flush_runtime(runtime) is True
            assert len(opened) == 1 and active == []
            assert runtime.last_acknowledged_yjs_state == c.yjs
            first = asyncio.create_task(hub._flush_runtime(runtime))
            runtime.flush_task = first
            await _eventually(sql_entered.is_set)
            hub._schedule_flush(runtime)
            replacement_pointer = runtime.flush_task
            assert replacement_pointer is not first
            disposing = asyncio.create_task(
                hub.shutdown()
                if shutdown
                else hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
            )
            await asyncio.sleep(0.05)
            assert not first.done() and not disposing.done()
            assert runtime.flush_lock.locked() and runtime.room.ydoc is not None
            assert len(opened) == 2 and len(active) == 1
            sql_release.set()
            await _eventually(close_entered.is_set)
            await asyncio.sleep(0.05)
            assert not first.done() and not disposing.done(), (
                "Dispose skipped a replaced pointer's post-COMMIT Session cleanup"
            )
            assert runtime.flush_lock.locked() and runtime.room.ydoc is not None
            close_release.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            await disposing
            assert replacement_pointer.done()
            assert active == [] and len(opened) == 2
            assert runtime.room.ydoc is None
            assert runtime.persistence_outcome.status == "acknowledged"
            assert runtime.last_acknowledged_yjs_state == c.yjs
        finally:
            sql_release.set()
            close_release.set()
            await asyncio.gather(
                *(task for task in (first, disposing) if task is not None), return_exceptions=True
            )
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        sql_release.set()
        close_release.set()
        event.remove(c.engine, "before_cursor_execute", gate)


def _capacity_source_contexts(c):
    """Five genuine captured admissions in the existing disposable migrated DB."""
    entries = [SimpleNamespace(context=c.context, collab_id=c.collab_id)]
    with c.world.core() as db:
        user = db.get(User, c.world.state["member_id"])
        for ordinal in range(1, 5):
            board = Whiteboard(
                id=f"owned-capacity-board-{ordinal}",
                owner_id=user.id,
                title=f"Owned capacity board {ordinal}",
            )
            db.add(board)
            db.flush()
            context, record = router._ensure_whiteboard_collab_context(db, user, board.id)
            record.yjs_state = c.yjs
            record.updated_at = board.updated_at + timedelta(seconds=1)
            entries.append(SimpleNamespace(context=context, collab_id=record.id))
        db.commit()
    return entries


def test_genuine_last_connection_cleanup_cancellation_joins_post_commit_session_close(
    persistence_world,
):
    c = persistence_world
    opened, active, committed = [], [], []
    close_entered, close_release = Event(), Event()

    class ObservedSession(Session):
        def commit(self):
            result = super().commit()
            committed.append(self)
            return result

        def close(self):
            try:
                super().close()
                close_entered.set()
                assert close_release.wait(8), "The final cleanup close gate was not released"
            finally:
                active.remove(self)

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        opened.append(db)
        active.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="final-cleanup-cancel"))
        await hub.startup()
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(
            update={"collab_snapshot_debounce_ms": 60000, "collab_cleanup_timeout_seconds": 5}
        )
        cleanup = None
        try:
            runtime = await hub.get_room(c.context, c.yjs)
            identity = runtime.persistence_identity
            await hub.acquire_connection_slot(runtime, c.world.state["member_id"])
            with runtime.room.ydoc.begin_transaction() as transaction:
                runtime.room.ydoc.get_map("scene").set(
                    transaction, "marker", "cleanup-caller-cancel"
                )
            expected = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            await hub.release_connection_slot(runtime, c.world.state["member_id"])
            cleanup = asyncio.create_task(
                hub.cleanup_room(runtime.room_key, expected_runtime=runtime)
            )
            await _eventually(close_entered.is_set)
            assert opened == committed and len(committed) == 1
            with c.world.core() as db:
                stored = db.get(WhiteboardCollabDocument, c.collab_id)
                assert stored.yjs_state == expected
                assert stored.room_key == runtime.room_key
            cleanup.cancel()
            await asyncio.sleep(0)
            cleanup.cancel()
            await asyncio.sleep(0.05)
            assert not cleanup.done(), (
                "Last-connection cleanup detached post-COMMIT Session cleanup"
            )
            assert runtime.room.ydoc is not None and runtime.flush_lock.locked()
            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == expected
            assert (
                runtime.persistence_identity == identity and runtime.retained_yjs_state == expected
            )
            assert runtime.persistence_outcome is None
            assert active == opened and hub._persistence_limiter.statistics().borrowed_tokens == 1
            close_release.set()
            with pytest.raises(asyncio.CancelledError):
                await cleanup
            assert active == [] and len(opened) == len(committed) == 1
            assert runtime.room.ydoc is None and not runtime.flush_lock.locked()
            assert runtime.persistence_identity == identity
            assert runtime.persistence_outcome.status == "acknowledged"
            assert (
                runtime.last_acknowledged_yjs_state == expected
                and runtime.retained_yjs_state is None
            )
            assert hub._persistence_limiter.statistics().borrowed_tokens == 0
        finally:
            close_release.set()
            if cleanup is not None:
                await asyncio.gather(cleanup, return_exceptions=True)
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        close_release.set()
