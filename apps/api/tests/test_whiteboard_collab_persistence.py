"""Whiteboard structural persistence: genuine SQL/Yjs red before product changes.

The red_contract cases call the existing admission, hub and persistence APIs.
They do not depend on a new identity field or substitute the persistence function.
All storage and users come from the accepted disposable migrated PG fixture.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
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


def test_pure_native_yjs_fixture_roundtrips_detached_bytes():
    state = _native_state("detached-native-state")
    assert type(state) is bytes and state != b"\x00\x00"
    assert _native_label(state) == "detached-native-state"


def test_genuine_current_native_room_flush_saves_exact_state(persistence_world):
    c = persistence_world
    changed = _native_state("valid-current-incarnation")

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="normal-save"))
        try:
            runtime = await hub.get_room(c.context, changed)
            await hub._flush_runtime(runtime)
            with c.world.core() as db:
                row = db.get(WhiteboardCollabDocument, c.collab_id)
                assert row.room_key == c.context.room_key
                assert row.yjs_state == changed
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_genuine_red_contract_old_room_rotation_never_overwrites_r2(persistence_world):
    c = persistence_world

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="rotation"))
        runtime = await hub.get_room(c.context, c.yjs)
        try:
            with c.world.core() as db:
                result = scene_state.apply_rest_scene_update(
                    db,
                    whiteboard=db.get(Whiteboard, c.context.whiteboard_id),
                    scene={
                        "elements": [{"id": "rest-r2", "type": "rectangle"}],
                        "appState": {},
                        "files": {},
                    },
                )
                assert result.whiteboard_changed and result.collab_changed
                assert result.collab.id == c.collab_id
                assert result.collab.room_key != c.context.room_key
                db.commit()
            expected = _stored_state(c)
            commands, observe = _collab_mutation_capture(c)
            try:
                await hub._flush_runtime(runtime)
                assert _stored_state(c) == expected, "R1 flush overwrote REST-rotated R2"
                attempts = len(commands)
                await hub.cleanup_room(c.context.room_key)
                await hub.shutdown()
                assert len(commands) == attempts, "A refused R1 payload was replayed on cleanup"
                assert _stored_state(c) == expected
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_genuine_red_contract_same_key_new_row_aba_preserves_r2(persistence_world):
    c = persistence_world
    r2_yjs = _native_state("recreated-r2")

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="same-key-aba"))
        runtime = await hub.get_room(c.context, c.yjs)
        try:
            with c.world.core() as db:
                db.delete(db.get(WhiteboardCollabDocument, c.collab_id))
                db.flush()
                replacement = WhiteboardCollabDocument(
                    # The persisted ID contract is VARCHAR(36), not UUID-only.
                    id="recreated-source-row",
                    whiteboard_id=c.context.whiteboard_id,
                    room_key=c.context.room_key,
                    yjs_state=r2_yjs,
                    snapshot_scene={"elements": [], "appState": {}, "files": {}},
                    updated_at=db.get(Whiteboard, c.context.whiteboard_id).updated_at
                    + timedelta(seconds=1),
                )
                db.add(replacement)
                db.commit()
                assert replacement.id != c.collab_id
                incoming, row = router._ensure_whiteboard_collab_context(
                    db, db.get(User, c.world.state["member_id"]), c.context.whiteboard_id
                )
                assert row.id == replacement.id and incoming.room_key == c.context.room_key
                db.commit()
            expected = _stored_state(c)
            commands, observe = _collab_mutation_capture(c)
            try:
                await hub._flush_runtime(runtime)
                assert _stored_state(c) == expected, "R1 flush adopted same-key R2 incarnation"
                attempts = len(commands)
                admitted_r2 = await hub.get_room(incoming, r2_yjs)
                assert admitted_r2 is not runtime, "Same-key R2 reused the R1 native YDoc"
                assert _native_label(bytes(Y.encode_state_as_update(admitted_r2.room.ydoc))) == (
                    "recreated-r2"
                )
                assert len(commands) == attempts
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


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


def test_genuine_default_admission_captures_exact_existing_opaque_collab_id(persistence_world):
    c = persistence_world
    with c.world.core() as db:
        original = db.get(WhiteboardCollabDocument, c.collab_id)
        db.delete(original)
        db.flush()
        row = WhiteboardCollabDocument(
            id="opaque-captured-record",
            whiteboard_id=c.context.whiteboard_id,
            room_key=c.context.room_key,
            yjs_state=c.yjs,
            snapshot_scene={"elements": [], "appState": {}, "files": {}},
            updated_at=db.get(Whiteboard, c.context.whiteboard_id).updated_at
            + timedelta(seconds=1),
        )
        db.add(row)
        db.commit()
        admitted, current = router._ensure_whiteboard_collab_context(
            db, db.get(User, c.world.state["member_id"]), c.context.whiteboard_id
        )
        assert admitted.collab_document_id == current.id == "opaque-captured-record"
        assert admitted.room_key == current.room_key == c.context.room_key
        db.commit()


def test_genuine_prepared_read_only_admission_preserves_captured_row_id(room_world):
    from miy_api.domains.whiteboard import collab_source_room
    from test_prepared_whiteboard_source_access import context

    c = room_world
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split()[0].upper())

    event.listen(c.engine, "before_cursor_execute", observe)
    try:
        state = collab_source_room.load_prepared_whiteboard_room_state(
            c.factory, item_id=c.world.ids["board"], user=context(c).user
        )
        assert state.context.collab_document_id == c.collab_id == "synthetic-room-record"
        assert state.context.room_key == "whiteboard:" + c.world.ids["board"]
        assert set(commands) <= {"SELECT", "SHOW", "SET"}
    finally:
        event.remove(c.engine, "before_cursor_execute", observe)


def test_genuine_captured_save_and_noop_keep_original_scene_snapshot_and_timestamps(
    persistence_world,
):
    c = persistence_world
    before = _stored_state(c)
    changed = _native_state("captured-normal-write")
    result = _captured_persist(c, state=changed)
    assert result.status == "acknowledged"
    accepted = _stored_state(c)
    assert accepted[:4] == before[:4]
    old_row, saved_row = before[4][0], accepted[4][0]
    assert saved_row[:3] == old_row[:3]
    assert saved_row[3] == changed and saved_row[4:7] == old_row[4:7]
    noop = _captured_persist(c, state=changed)
    assert noop.status == "acknowledged" and _stored_state(c) == accepted


def test_genuine_explicit_trusted_helper_retains_neither_argument_initialization(
    persistence_world,
):
    c = persistence_world
    with c.world.core() as db:
        db.delete(db.get(WhiteboardCollabDocument, c.collab_id))
        db.commit()
    changed = _native_state("trusted-current-room")
    assert (
        scene_state.persist_runtime_yjs_state(
            c.world.core, whiteboard_id=c.context.whiteboard_id, yjs_state=changed
        )
        is None
    )
    stored = _stored_state(c)
    assert len(stored[4]) == 1
    assert stored[4][0][0] != c.collab_id
    assert stored[4][0][2] == "whiteboard:" + c.context.whiteboard_id
    assert stored[4][0][3] == changed
    assert (
        scene_state.persist_runtime_yjs_state(
            c.world.core, whiteboard_id="absent-owned-board", yjs_state=changed
        )
        is None
    )
    assert _stored_state(c) == stored


@pytest.mark.parametrize(
    "expected_id,expected_key",
    [
        (None, "whiteboard:unit"),
        ("opaque", None),
        ("", "whiteboard:unit"),
        (True, "whiteboard:unit"),
        ("x" * 37, "whiteboard:unit"),
        ("opaque", ""),
        ("opaque", True),
        ("opaque", "x" * 129),
    ],
)
def test_pure_partial_or_invalid_capture_refuses_before_session_factory(expected_id, expected_key):
    calls = []

    def forbidden():
        calls.append("factory")
        pytest.fail("Invalid captured identity opened a Session")

    with pytest.raises(scene_state.WhiteboardPersistenceRefused) as caught:
        scene_state.persist_runtime_yjs_state(
            forbidden,
            whiteboard_id="unit",
            yjs_state=_native_state("invalid-identity"),
            expected_room_key=expected_key,
            expected_collab_id=expected_id,
        )
    assert str(caught.value) == "whiteboard_persistence_refused"
    assert calls == []


def test_pure_idless_memory_room_flush_has_no_session_or_trusted_fallback():
    calls = []

    def forbidden():
        calls.append("factory")
        pytest.fail("ID-less in-memory room acquired persistence authority")

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="idless-slot-room"))
        hub._session_factory = forbidden
        context = collab.WhiteboardCollabContext("unit", "whiteboard:unit", True, {}, "owner")
        try:
            runtime = await hub.get_room(context, _native_state("memory-only"))
            await hub.acquire_connection_slot(runtime, "owner")
            await hub.release_connection_slot(runtime, "owner")
            assert await hub._flush_runtime(runtime) is False
            assert runtime.persistence_outcome.status == "refused"
            assert runtime.metadata["persistence_terminal"] == "refused"
            assert calls == []
            await hub.cleanup_room(context.room_key, expected_runtime=runtime)
            await hub.shutdown()
            assert calls == []
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("missing", ["collab", "board", "trashed"])
def test_genuine_captured_missing_or_trashed_source_never_initializes(persistence_world, missing):
    c = persistence_world
    with c.world.core() as db:
        db.delete(db.get(WhiteboardCollabDocument, c.collab_id))
        db.flush()
        if missing == "board":
            board = db.get(Whiteboard, c.context.whiteboard_id)
            # The owned fixture board has no independent target/share children.
            db.delete(board)
        elif missing == "trashed":
            from miy_api.domains.auth.models import utcnow_naive

            db.get(Whiteboard, c.context.whiteboard_id).trashed_at = utcnow_naive()
        db.commit()
    commands, observe = _collab_mutation_capture(c)
    try:
        result = _captured_persist(c, state=_native_state("must-not-initialize"))
        assert result.status == "refused"
        with c.world.core() as db:
            assert (
                db.scalar(
                    select(WhiteboardCollabDocument).where(
                        WhiteboardCollabDocument.whiteboard_id == c.context.whiteboard_id
                    )
                )
                is None
            )
        assert "INSERT" not in commands
    finally:
        event.remove(c.engine, "before_cursor_execute", observe)


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


@pytest.mark.parametrize("invalidate_fault", [False, True])
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


def test_genuine_host_cancel_during_post_ack_session_close_preserves_ack(persistence_world):
    c = persistence_world
    entered, release, closed = Event(), Event(), Event()
    changed = _native_state("ack-before-host-cancel")
    opened = []

    class GatedCloseSession(Session):
        def close(self):
            super().close()
            entered.set()
            try:
                assert release.wait(8), "The owned post-ACK close gate was not released"
            finally:
                closed.set()

    def factory():
        db = GatedCloseSession(c.engine, autoflush=False)
        opened.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="ack-host-cancel"))
        hub._session_factory = factory
        task = None
        try:
            runtime = await hub.get_room(c.context, changed)
            task = asyncio.create_task(hub._flush_runtime(runtime))
            await _eventually(entered.is_set)
            assert _stored_state(c)[4][0][3] == changed
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.05)
            assert not task.done() and runtime.flush_lock.locked()
            assert not closed.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed.is_set()
            assert runtime.persistence_outcome.status == "acknowledged"
            assert runtime.last_acknowledged_yjs_state == changed
            assert runtime.retained_yjs_state is None
            await hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
            await hub.shutdown()
            assert len(opened) == 1 and runtime.persistence_outcome.status == "acknowledged"
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        release.set()


@pytest.mark.parametrize("shutdown", [False, True])
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


def test_genuine_get_room_replaces_captured_same_key_aba_before_any_old_flush(persistence_world):
    c = persistence_world
    changed = _native_state("replacement-admitted-without-old-flush")

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="direct-aba-admission"))
        try:
            old = await hub.get_room(c.context, c.yjs)
            with c.world.core() as db:
                db.delete(db.get(WhiteboardCollabDocument, c.collab_id))
                db.flush()
                db.add(
                    WhiteboardCollabDocument(
                        id="direct-aba-opaque-row",
                        whiteboard_id=c.context.whiteboard_id,
                        room_key=c.context.room_key,
                        yjs_state=changed,
                        snapshot_scene={"elements": [], "appState": {}, "files": {}},
                    )
                )
                db.commit()
            incoming = replace(c.context, collab_document_id="direct-aba-opaque-row")
            commands, observe = _collab_mutation_capture(c)
            try:
                runtime = await hub.get_room(incoming, changed)
                assert runtime is not old
                assert runtime.persistence_identity.collab_document_id == "direct-aba-opaque-row"
                assert old.persistence_outcome.status == "refused"
                assert hub._rooms[c.context.room_key] is runtime
                assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == changed
                assert commands == []
                await hub.cleanup_room(c.context.room_key, expected_runtime=old)
                assert hub._rooms[c.context.room_key] is runtime
                assert runtime.room.ydoc is not None
            finally:
                event.remove(c.engine, "before_cursor_execute", observe)
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_pure_orphan_native_observer_and_queued_publish_cannot_target_replacement():
    published = []

    class ObservedBus(InProcessCollabBus):
        async def publish(self, room_key, payload):
            published.append((room_key, payload))
            return await super().publish(room_key, payload)

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=ObservedBus(instance_id="orphan-callback"))
        await hub.startup()
        context = collab.WhiteboardCollabContext("unit", "whiteboard:unit", True, {}, "owner")
        old = None
        try:
            old = await hub.get_room(context, _native_state("old-native"))
            queued = asyncio.create_task(
                hub._publish_update(old, _native_state("queued-old"), "owned-hash")
            )
            hub._rooms.pop(context.room_key)
            runtime = await hub.get_room(context, _native_state("current-native"))
            with old.room.ydoc.begin_transaction() as txn:
                old.room.ydoc.get_map("scene").set(txn, "marker", "late-old-observer")
            assert old.room.on_message(b"\x01owned-late-awareness") is True
            await hub._publish_awareness(old, b"\x01owned-late-awareness")
            await queued
            await asyncio.sleep(0)
            assert published == []
            assert old.flush_task is None and runtime.flush_task is None
            assert hub._rooms[context.room_key] is runtime
            assert (
                _native_label(bytes(Y.encode_state_as_update(runtime.room.ydoc)))
                == "current-native"
            )
        finally:
            await hub.shutdown()
            if old is not None:
                await _release_test_orphan(hub, old)

    asyncio.run(exercise())


@pytest.mark.parametrize("lifecycle", ["active", "replaced", "disposing", "terminal"])
def test_pure_actual_native_serve_applies_only_current_active_room_frame(lifecycle):
    from ypy_websocket.yutils import create_update_message

    class OneNativeFrame:
        path = "/owned-whiteboard-native-frame"

        def __init__(self, update):
            self.update = create_update_message(update)
            self.received = False
            self.sent = []

        async def send(self, message):
            self.sent.append(message)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.received:
                raise StopAsyncIteration
            self.received = True
            return self.update

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="native-frame-guard"))
        await hub.startup()
        hub._settings = hub._settings.model_copy(update={"collab_snapshot_debounce_ms": 60000})
        context = collab.WhiteboardCollabContext("unit", "whiteboard:unit", True, {}, "owner")
        runtime = replacement = None
        try:
            runtime = await hub.get_room(context, _native_state("native-before-frame"))
            before = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            remote = Y.YDoc()
            Y.apply_update(remote, before)
            with remote.begin_transaction() as txn:
                remote.get_map("scene").set(txn, "marker", "native-frame-applied")
            if lifecycle == "replaced":
                hub._rooms.pop(context.room_key)
                replacement = await hub.get_room(context, _native_state("native-replacement"))
            elif lifecycle == "disposing":
                runtime.metadata["disposing"] = "true"
            elif lifecycle == "terminal":
                runtime.metadata["persistence_terminal"] = "unknown"
            transport = OneNativeFrame(bytes(Y.encode_state_as_update(remote)))
            # Real pinned YRoom.serve and process_sync_message; only transport is owned.
            async with asyncio.timeout(5):
                await runtime.room.serve(transport)
            assert transport.received and transport.sent
            state = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            if lifecycle == "active":
                assert _native_label(state) == "native-frame-applied"
                assert runtime.room.on_message(b"\x01owned-awareness") is False
            else:
                assert state == before, "Native serve applied a late inactive runtime frame"
                assert runtime.room.on_message(b"\x01owned-awareness") is True
            if replacement is not None:
                assert _native_label(bytes(Y.encode_state_as_update(replacement.room.ydoc))) == (
                    "native-replacement"
                )
                assert replacement.flush_task is None
        finally:
            if runtime is not None and lifecycle == "disposing":
                # Remove only this test's metadata flag so ordinary shutdown owns disposal.
                runtime.metadata.pop("disposing")
            await hub.shutdown()
            if runtime is not None and lifecycle == "replaced":
                await _release_test_orphan(hub, runtime)

    asyncio.run(exercise())


@pytest.mark.parametrize("unknown", [False, True])
def test_genuine_cleanup_pending_identity_cannot_reopen_before_join_and_unknown_stays_blocked(
    persistence_world, unknown
):
    c = persistence_world
    changed = _native_state("pending-incarnation-save")
    entered, release = Event(), Event()
    opened, active = [], []

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

    def gate(_conn, _cursor, statement, *_):
        if (
            statement.lstrip().upper().startswith("UPDATE")
            and ("whiteboard_collab_documents" in statement)
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(8), "The owned retiring-incarnation gate was not released"

    event.listen(c.engine, "before_cursor_execute", gate)

    async def exercise():
        from contextlib import nullcontext

        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="pending-incarnation"))
        hub._session_factory = factory
        first = disposing = None
        try:
            runtime = await hub.get_room(c.context, changed)
            identity = runtime.persistence_identity
            fault = _driver_commit_fault(c.engine, after_commit=True) if unknown else nullcontext()
            with fault as driver:
                first = asyncio.create_task(hub._flush_runtime(runtime))
                runtime.flush_task = first
                await _eventually(entered.is_set)
                disposing = asyncio.create_task(
                    hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
                )
                await _eventually(lambda: c.context.room_key not in hub._rooms)
                with pytest.raises(scene_state.WhiteboardPersistenceRefused) as caught:
                    await hub.get_room(c.context, c.yjs)
                assert str(caught.value) == "whiteboard_persistence_refused"
                assert caught.value.reason
                assert not first.done() and not disposing.done()
                assert len(opened) == 1 and len(active) == 1
                assert runtime.flush_lock.locked() and runtime.room.ydoc is not None
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await first
                await disposing
                if unknown:
                    assert driver["real_driver_commits"] == driver["dispatches"] == 1
                    assert driver["psycopg_driver"] is True
            assert runtime.room.ydoc is None and active == []
            assert _stored_state(c)[4][0][3] == changed
            if unknown:
                assert runtime.persistence_outcome.status == "unknown"
                assert runtime.retained_yjs_state == changed
                assert runtime.persistence_identity == identity
                await hub.shutdown()
                with pytest.raises(scene_state.WhiteboardPersistenceRefused) as caught:
                    await hub.get_room(c.context, _stored_state(c)[4][0][3])
                assert caught.value.reason == "unresolved_incarnation"
                assert len(opened) == 1
                assert runtime.persistence_outcome.status == "unknown"
                assert runtime.retained_yjs_state == changed
            else:
                assert runtime.persistence_outcome.status == "acknowledged"
                incoming = await hub.get_room(c.context, changed)
                assert incoming is not runtime and incoming.persistence_identity == identity
                assert bytes(Y.encode_state_as_update(incoming.room.ydoc)) == changed
                assert len(opened) == 1
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (first, disposing) if task is not None), return_exceptions=True
            )
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        event.remove(c.engine, "before_cursor_execute", gate)


def test_genuine_borrowed_caller_session_is_refused_without_rollback_or_close(persistence_world):
    c = persistence_world
    lifecycle = []

    class CallerSession(Session):
        def rollback(self):
            lifecycle.append("rollback")
            return super().rollback()

        def close(self):
            lifecycle.append("close")
            return super().close()

    caller = CallerSession(c.engine, autoflush=False)
    try:
        board = caller.get(Whiteboard, c.context.whiteboard_id)
        original_title = board.title
        board.title = "owned-uncommitted-caller-work"
        with pytest.raises(scene_state.WhiteboardPersistenceRefused) as caught:
            _captured_persist(c, factory=lambda: caller, state=_native_state("must-not-borrow"))
        assert str(caught.value) == "whiteboard_persistence_refused"
        assert caller.in_transaction() and board in caller.dirty
        assert board.title == "owned-uncommitted-caller-work"
        assert lifecycle == []
        with c.world.core() as db:
            assert db.get(Whiteboard, c.context.whiteboard_id).title == original_title
            assert db.get(WhiteboardCollabDocument, c.collab_id).yjs_state == c.yjs
    finally:
        caller.rollback()
        caller.close()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_captured_write_refuses_non_read_committed_session_profile(
    persistence_world, isolation
):
    c = persistence_world
    before = _stored_state(c)
    engine = c.engine.execution_options(isolation_level=isolation)
    commands, observe = _collab_mutation_capture(c)
    try:
        result = _captured_persist(
            c, factory=lambda: Session(engine, autoflush=False), state=_native_state("bad-profile")
        )
        assert result.status == "refused"
        assert commands == [] and _stored_state(c) == before
    finally:
        event.remove(c.engine, "before_cursor_execute", observe)


def test_pure_native_empty_read_delta_does_not_schedule_or_publish_but_delete_delta_does():
    import base64

    published = []

    class ObservedBus(InProcessCollabBus):
        async def publish(self, room_key, payload):
            published.append((room_key, payload))
            return await super().publish(room_key, payload)

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=ObservedBus(instance_id="native-empty-vs-delete"))
        await hub.startup()
        hub._settings = hub._settings.model_copy(update={"collab_snapshot_debounce_ms": 60000})
        context = collab.WhiteboardCollabContext("unit", "whiteboard:unit", True, {}, "owner")
        native_deltas = []
        try:
            runtime = await hub.get_room(context, _native_state("delete-this-native-marker"))
            # Independent native observer; the registered product callback is unchanged.
            runtime.room.ydoc.observe_after_transaction(
                lambda transaction: native_deltas.append(bytes(transaction.get_update()))
            )
            encoded = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            await asyncio.sleep(0)
            assert _native_label(encoded) == "delete-this-native-marker"
            assert native_deltas and all(delta == b"\x00\x00" for delta in native_deltas)
            assert runtime.flush_task is None and published == []

            native_deltas.clear()
            with runtime.room.ydoc.begin_transaction() as transaction:
                removed = runtime.room.ydoc.get_map("scene").pop(transaction, "marker")
                assert removed == "delete-this-native-marker"
            await _eventually(lambda: bool(published))
            delete_deltas = [delta for delta in native_deltas if delta != b"\x00\x00"]
            assert delete_deltas, "A real native delete-only transaction must remain substantive"
            scheduled = runtime.flush_task
            assert scheduled is not None and not scheduled.done()
            assert len(published) == 1
            key, payload = published[0]
            assert key == context.room_key and payload["type"] == "yjs_update"
            assert base64.b64decode(payload["data"]) in delete_deltas

            native_deltas.clear()
            deleted_state = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            await asyncio.sleep(0)
            assert _native_label(deleted_state) is None
            assert native_deltas and all(delta == b"\x00\x00" for delta in native_deltas)
            assert runtime.flush_task is scheduled and not scheduled.done()
            assert len(published) == 1, "Encoding after a delete must not requeue or republish"
        finally:
            await hub.shutdown()

    asyncio.run(exercise())


def test_genuine_native_debounce_ack_then_encode_read_has_no_new_timer_or_sql(persistence_world):
    c = persistence_world
    opened, committed = [], []

    class ObservedSession(Session):
        def commit(self):
            result = super().commit()
            committed.append(self)
            return result

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        opened.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(
            bus=InProcessCollabBus(instance_id="normal-native-debounce")
        )
        await hub.startup()
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(
            update={"collab_snapshot_debounce_ms": 20, "collab_cleanup_timeout_seconds": 5}
        )
        commands, observe = _collab_mutation_capture(c)
        try:
            runtime = await hub.get_room(c.context, c.yjs)
            with runtime.room.ydoc.begin_transaction() as transaction:
                runtime.room.ydoc.get_map("scene").set(
                    transaction, "marker", "substantive-edit-through-normal-debounce"
                )
            scheduled = runtime.flush_task
            assert scheduled is not None
            expected = bytes(Y.encode_state_as_update(runtime.room.ydoc))
            assert runtime.flush_task is scheduled
            await _eventually(
                lambda: bool(
                    runtime.persistence_outcome
                    and runtime.persistence_outcome.status == "acknowledged"
                    and scheduled.done()
                )
            )
            assert not scheduled.cancelled() and scheduled.exception() is None
            assert opened == committed and len(committed) == 1
            assert commands == ["UPDATE"]
            assert runtime.last_acknowledged_yjs_state == expected
            assert runtime.retained_yjs_state is None
            with c.world.core() as db:
                assert db.get(WhiteboardCollabDocument, c.collab_id).yjs_state == expected
            accepted = _stored_state(c)

            assert bytes(Y.encode_state_as_update(runtime.room.ydoc)) == expected
            # Let a wrongly requeued 20ms timer reach real SQL before checking.
            await asyncio.sleep(0.06)
            assert runtime.flush_task is scheduled and scheduled.done()
            assert len(opened) == len(committed) == 1 and commands == ["UPDATE"]
            assert runtime.persistence_outcome.status == "acknowledged"
            assert _stored_state(c) == accepted
            await hub.cleanup_room(c.context.room_key, expected_runtime=runtime)
            await hub.shutdown()
            assert len(opened) == len(committed) == 1 and commands == ["UPDATE"]
        finally:
            await hub.shutdown()
            event.remove(c.engine, "before_cursor_execute", observe)

    asyncio.run(exercise())


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


@pytest.mark.parametrize("queued_action", ["wait", "cancel", "replace"])
def test_genuine_shared_worker_capacity_holds_slots_through_cleanup_and_rechecks_queued_room(
    persistence_world, queued_action
):
    from threading import Lock

    from test_official_writer_fence import wait_for_blockers

    c = persistence_world
    entries = _capacity_source_contexts(c)
    holders, holder_pids = [], []
    opened, active, committed, active_peaks = [], [], [], []
    worker_ordinals, sql_pids, row_sql_pids = {}, {}, {}
    blocked_collab_ids = {entry.collab_id for entry in entries[:4]}
    close_entered, close_release = Event(), Event()
    tracking_lock = Lock()

    class ObservedSession(Session):
        def commit(self):
            result = super().commit()
            committed.append(self)
            return result

        def close(self):
            try:
                super().close()
                if self is opened[0]:
                    close_entered.set()
                    assert close_release.wait(10), (
                        "The bounded capacity close gate was not released"
                    )
            finally:
                with tracking_lock:
                    active.remove(self)

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        with tracking_lock:
            worker_ordinals[get_ident()] = len(opened)
            opened.append(db)
            active.append(db)
            active_peaks.append(len(active))
        return db

    def observe(connection, _cursor, statement, _parameters, execution_context, _executemany):
        ordinal = worker_ordinals.get(get_ident())
        if (
            ordinal is not None
            and statement.lstrip().upper().startswith("UPDATE")
            and ("whiteboard_collab_documents" in statement)
        ):
            pid = connection.connection.driver_connection.info.backend_pid
            if ordinal < 4:
                captured_ids = {
                    value
                    for parameters in execution_context.compiled_parameters
                    for value in parameters.values()
                    if isinstance(value, str) and value in blocked_collab_ids
                }
                assert len(captured_ids) == 1, (
                    "Capacity observer must identify one captured collab row"
                )
                row_sql_pids[captured_ids.pop()] = pid
            sql_pids[ordinal] = pid

    async def exercise():
        hub = collab.WhiteboardCollabHub(
            bus=InProcessCollabBus(instance_id="native-shared-capacity")
        )
        await hub.startup()
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(
            update={
                "collab_snapshot_debounce_ms": 60000,
                "collab_cleanup_timeout_seconds": 15,
            }
        )
        tasks, runtimes, expected = [], [], []
        fifth = replacement_task = None
        try:
            for ordinal, entry in enumerate(entries):
                state = _native_state(f"owned-capacity-native-{ordinal}")
                runtime = await hub.get_room(entry.context, state)
                runtimes.append(runtime)
                expected.append(bytes(Y.encode_state_as_update(runtime.room.ydoc)))
            # Launch room zero first so its observed Session is the close-gated worker.
            tasks.append(asyncio.create_task(hub._flush_runtime(runtimes[0])))
            await _eventually(lambda: 0 in sql_pids)
            for runtime in runtimes[1:4]:
                tasks.append(asyncio.create_task(hub._flush_runtime(runtime)))
            await _eventually(lambda: len(sql_pids) == 4)
            for ordinal in range(4):
                await asyncio.to_thread(
                    wait_for_blockers,
                    c.world.core,
                    row_sql_pids[entries[ordinal].collab_id],
                    {holder_pids[ordinal]},
                )
            assert len(opened) == len(active) == 4
            fifth = asyncio.create_task(hub._flush_runtime(runtimes[4]))

            def queued_or_real_overflow():
                limiter = getattr(hub, "_persistence_limiter", None)
                return len(sql_pids) >= 5 or bool(
                    limiter is not None and limiter.statistics().tasks_waiting == 1
                )

            await _eventually(queued_or_real_overflow)
            # Baseline per-flush limiters reach real fifth SQL before this assertion.
            assert len(opened) == 4 and len(sql_pids) == 4, (
                "A fifth native room opened a Session/SQL worker beyond the shared bound"
            )
            assert not fifth.done() and max(active_peaks) == 4
            assert hub._persistence_limiter.statistics().borrowed_tokens == 4
            if queued_action == "cancel":
                fifth.cancel()
                await asyncio.sleep(0)
                fifth.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await fifth
                assert len(opened) == len(sql_pids) == 4
                assert runtimes[4].persistence_outcome is None
                assert hub._persistence_limiter.statistics().borrowed_tokens == 4
                fifth = asyncio.create_task(hub._flush_runtime(runtimes[4]))
                await _eventually(lambda: hub._persistence_limiter.statistics().tasks_waiting == 1)
            elif queued_action == "replace":
                replacement_state = _native_state("owned-capacity-new-incarnation")
                with c.world.core() as db:
                    db.delete(db.get(WhiteboardCollabDocument, entries[4].collab_id))
                    db.flush()
                    replacement_row = WhiteboardCollabDocument(
                        id="owned-capacity-new-row",
                        whiteboard_id=entries[4].context.whiteboard_id,
                        room_key=entries[4].context.room_key,
                        yjs_state=replacement_state,
                        snapshot_scene={"elements": [], "appState": {}, "files": {}},
                        updated_at=db.get(Whiteboard, entries[4].context.whiteboard_id).updated_at
                        + timedelta(seconds=1),
                    )
                    db.add(replacement_row)
                    db.flush()
                    incoming, row = router._ensure_whiteboard_collab_context(
                        db, db.get(User, c.world.state["member_id"]), replacement_row.whiteboard_id
                    )
                    assert incoming.collab_document_id == row.id == replacement_row.id
                    db.commit()
                replacement = await hub.get_room(incoming, replacement_state)
                assert replacement is not runtimes[4]
                assert runtimes[4].persistence_outcome.status == "refused"
                assert not fifth.done() and len(opened) == len(sql_pids) == 4

            # Only worker zero's real DB COMMIT proceeds; three other SQL locks stay held.
            holders[0].rollback()
            await _eventually(close_entered.is_set)
            assert committed == [opened[0]]
            assert not tasks[0].done() and runtimes[0].flush_lock.locked()
            assert len(active) == len(opened) == len(sql_pids) == 4
            assert not fifth.done(), "A permit was released at COMMIT before Session cleanup joined"
            assert hub._persistence_limiter.statistics().borrowed_tokens == 4
            for ordinal in range(1, 4):
                await asyncio.to_thread(
                    wait_for_blockers,
                    c.world.core,
                    row_sql_pids[entries[ordinal].collab_id],
                    {holder_pids[ordinal]},
                )
            close_release.set()
            assert await tasks[0] is True
            if queued_action == "replace":
                assert await fifth is False
                assert len(opened) == len(sql_pids) == 4, "A retired slot waiter entered SQL"
                assert hub._rooms[incoming.room_key] is replacement
                replacement_task = asyncio.create_task(hub._flush_runtime(replacement))
                assert await replacement_task is True
                saved_entry = SimpleNamespace(
                    context=incoming, collab_id=incoming.collab_document_id
                )
                saved_state = replacement_state
            else:
                assert await fifth is True
                saved_entry, saved_state = entries[4], expected[4]
            assert len(opened) == 5 and len(sql_pids) == 5 and max(active_peaks) == 4
            assert len(active) == 3 and len(committed) == 2
            with c.world.core() as db:
                assert (
                    db.get(WhiteboardCollabDocument, saved_entry.collab_id).yjs_state == saved_state
                )
            for holder in holders[1:]:
                holder.rollback()
            assert await asyncio.gather(*tasks) == [True] * 4
            assert active == [] and len(opened) == len(committed) == 5
            assert hub._persistence_limiter.statistics().borrowed_tokens == 0
            for ordinal, entry in enumerate(entries[:4]):
                assert runtimes[ordinal].persistence_outcome.status == "acknowledged"
                with c.world.core() as db:
                    assert (
                        db.get(WhiteboardCollabDocument, entry.collab_id).yjs_state
                        == expected[ordinal]
                    )
            await hub.shutdown()
            assert active == [] and len(opened) == len(committed) == 5
        finally:
            close_release.set()
            for holder in holders:
                holder.rollback()
            await asyncio.gather(
                *tasks,
                *(task for task in (fifth, replacement_task) if task is not None),
                return_exceptions=True,
            )
            await hub.shutdown()

    try:
        for entry in entries[:4]:
            holder = c.world.core()
            holders.append(holder)
            holder.scalar(
                select(WhiteboardCollabDocument)
                .where(WhiteboardCollabDocument.id == entry.collab_id)
                .with_for_update()
            )
            holder_pids.append(holder.scalar(text("SELECT pg_backend_pid()")))
        event.listen(c.engine, "before_cursor_execute", observe)
        asyncio.run(exercise())
    finally:
        close_release.set()
        for holder in holders:
            holder.rollback()
            holder.close()
        if event.contains(c.engine, "before_cursor_execute", observe):
            event.remove(c.engine, "before_cursor_execute", observe)


@pytest.mark.parametrize("lifecycle", ["cleanup", "shutdown"])
def test_genuine_saturated_final_disposal_retains_native_bytes_until_admission_and_ack(
    persistence_world, lifecycle
):
    from threading import Lock

    c = persistence_world
    entries = _capacity_source_contexts(c)
    opened, active, committed, close_entered = [], [], [], []
    tracking_lock = Lock()
    close_release = Event()

    class ObservedSession(Session):
        def commit(self):
            result = super().commit()
            with tracking_lock:
                committed.append(self)
            return result

        def close(self):
            try:
                super().close()
                with tracking_lock:
                    gated = self in opened[:4]
                    if gated:
                        close_entered.append(self)
                if gated:
                    assert close_release.wait(10), (
                        "The saturated final-save gates were not released"
                    )
            finally:
                with tracking_lock:
                    active.remove(self)

    def factory():
        db = ObservedSession(c.engine, autoflush=False)
        with tracking_lock:
            opened.append(db)
            active.append(db)
        return db

    async def exercise():
        hub = collab.WhiteboardCollabHub(bus=InProcessCollabBus(instance_id="saturated-final-save"))
        await hub.startup()
        hub._session_factory = factory
        hub._settings = hub._settings.model_copy(
            update={
                "collab_snapshot_debounce_ms": 60000,
                "collab_cleanup_timeout_seconds": 1,
            }
        )
        tasks, runtimes = [], []
        disposing = None
        try:
            for ordinal, entry in enumerate(entries):
                runtime = await hub.get_room(
                    entry.context, _native_state(f"owned-saturated-final-{ordinal}")
                )
                runtimes.append(runtime)
            for runtime in runtimes[:4]:
                tasks.append(asyncio.create_task(hub._flush_runtime(runtime)))
            await _eventually(lambda: len(close_entered) == 4)
            assert len(opened) == len(active) == len(committed) == 4
            assert hub._persistence_limiter.statistics().borrowed_tokens == 4

            pending = runtimes[4]
            await hub.acquire_connection_slot(pending, c.world.state["member_id"])
            with pending.room.ydoc.begin_transaction() as transaction:
                pending.room.ydoc.get_map("scene").set(
                    transaction, "marker", "last-connection-final-bytes"
                )
            expected = bytes(Y.encode_state_as_update(pending.room.ydoc))
            assert pending.flush_task is not None
            await hub.release_connection_slot(pending, c.world.state["member_id"])
            assert pending.active_connection_count == 0
            identity = pending.persistence_identity
            disposing = asyncio.create_task(
                hub.cleanup_room(pending.room_key, expected_runtime=pending)
                if lifecycle == "cleanup"
                else hub.shutdown()
            )
            await _eventually(lambda: pending.metadata.get("disposing") == "true")
            await _eventually(lambda: hub._persistence_limiter.statistics().tasks_waiting == 1)
            # Baseline finalsave used the same outer timeout for slot admission.
            await asyncio.sleep(1.3)
            assert pending.room.ydoc is not None, (
                "Final disposal released unsaved native bytes while shared slots were saturated"
            )
            assert bytes(Y.encode_state_as_update(pending.room.ydoc)) == expected
            assert pending.retained_yjs_state == expected
            assert pending.persistence_identity == identity
            assert pending.persistence_outcome is None
            assert not disposing.done() and len(opened) == len(active) == 4
            assert hub._persistence_limiter.statistics().borrowed_tokens == 4
            with c.world.core() as db:
                assert db.get(WhiteboardCollabDocument, entries[4].collab_id).yjs_state == c.yjs

            if lifecycle == "shutdown":
                disposing.cancel()
                await asyncio.sleep(0)
                disposing.cancel()
                await asyncio.sleep(0.05)
                assert not disposing.done(), "Shutdown cancellation detached final byte ownership"
                assert pending.room.ydoc is not None and pending.retained_yjs_state == expected
                assert pending.persistence_identity == identity
                assert len(opened) == len(active) == 4
            close_release.set()
            assert await asyncio.gather(*tasks) == [True] * 4
            if lifecycle == "shutdown":
                with pytest.raises(asyncio.CancelledError):
                    await disposing
            else:
                await disposing
            assert pending.persistence_outcome.status == "acknowledged"
            assert pending.last_acknowledged_yjs_state == expected
            assert pending.retained_yjs_state is None
            assert pending.persistence_identity == identity
            assert pending.room.ydoc is None
            assert active == [] and len(opened) == len(committed) == 5
            assert hub._persistence_limiter.statistics().borrowed_tokens == 0
            with c.world.core() as db:
                row = db.get(WhiteboardCollabDocument, entries[4].collab_id)
                assert row.id == identity.collab_document_id
                assert row.room_key == identity.room_key and row.yjs_state == expected
            await hub.shutdown()
            assert all(runtime.room.ydoc is None for runtime in runtimes)
            assert active == [] and len(opened) == len(committed) == 5
        finally:
            close_release.set()
            await asyncio.gather(
                *tasks, *(task for task in (disposing,) if task is not None), return_exceptions=True
            )
            await hub.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        close_release.set()


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
                assert db.get(WhiteboardCollabDocument, c.collab_id).yjs_state == expected
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
