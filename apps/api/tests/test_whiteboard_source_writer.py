"""Inactive Whiteboard service SQL admission in disposable migrated PostgreSQL.

The actual LOGIN/CAS cases prove a fixed service principal and producer fence.
They supply synthetic test authority; they do not prove current actor/resource
ACL through COMMIT, select a runtime factory, or activate an operational service.
Missing new APIs are readiness failures, never behavioral RED evidence.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
import re
from shutil import copyfile
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
import y_py as Y

from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_contracts import (
    SUITE_SCOPE,
)
from miy_api.domains.official_apps.writer_roles import (
    ROLE_GUARD,
    install_role_guard,
)
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
import test_alembic_migrations as migration_tests
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster  # noqa: F401
from test_official_writer_roles import (
    ACTIVE,
    BASE,
    DRAIN,
    PASSWORD,
    denied,
    move,
    role_template as role_template,  # noqa: F401
    sa_dsn,
    world as current_head_world,  # noqa: F401
)

CAPABILITY = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER = "public.miy_recording_lock_producer(bigint,text,integer,text)"
READ_COLUMNS = {
    "whiteboards": ("id", "trashed_at"),
    "whiteboard_collab_documents": (
        "id",
        "whiteboard_id",
        "room_key",
        "yjs_state",
        "updated_at",
        "writer_scope",
    ),
}
UPDATE_COLUMNS = {
    "whiteboards": ("writer_scope",),
    "whiteboard_collab_documents": ("yjs_state", "updated_at", "writer_scope"),
}
USER_NAMESPACE = (
    "n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname !~ '^pg_(toast|temp)(_|$)'"
)


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    """Keep service tests at head; pin only the Source revision's own contract."""
    revision = getattr(request, "param", None)
    if revision is None:
        return current_head_world
    assert revision == "wb_source_writer_20261009"
    original_config = migration_tests._migration_config
    config = original_config(sa_dsn(current_head_world.dsn))
    ancestors = list(ScriptDirectory.from_config(config).walk_revisions(base="base", head=revision))
    command.downgrade(config, revision)
    versions = tmp_path / "source_migration_versions"
    versions.mkdir()
    for ancestor in ancestors:
        source = Path(ancestor.path)
        copyfile(source, versions / source.name)

    def source_config(dsn=None):
        scoped = original_config(dsn)
        scoped.set_main_option("version_locations", str(versions))
        return scoped

    monkeypatch.setattr(migration_tests, "_migration_config", source_config)
    return current_head_world


def _api():
    try:
        roles = import_module("miy_api.domains.official_apps.whiteboard_source_writer_roles")
        runtime = import_module("miy_api.domains.official_apps.whiteboard_source_writer")
    except ModuleNotFoundError:
        pytest.fail(
            "Whiteboard Source writer API readiness missing; no behavioral RED", pytrace=False
        )
    return SimpleNamespace(roles=roles, runtime=runtime)


def _native_state(label):
    doc = Y.YDoc()
    with doc.begin_transaction() as txn:
        doc.get_map("scene").set(txn, "marker", label)
    return bytes(Y.encode_state_as_update(doc))


def _oid(conn, name):
    return conn.execute(
        "SELECT oid::bigint FROM pg_catalog.pg_roles WHERE rolname=%s", (name,)
    ).fetchone()[0]


def _install(c, db):
    return c.api.roles.install_whiteboard_source_writer_guard(
        db,
        c.world.actor,
        guard_owner=c.capability_owner,
        expected=DRAIN,
        expected_migration_owner_oid=c.migration_owner_oid,
        expected_producer_owner_oid=c.producer_owner_oid,
        expected_source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _prepare(c, db, role_name, *, identity=ACTIVE, expected=None, expected_state=None):
    return c.api.roles.prepare_whiteboard_source_writer_principal(
        db,
        c.world.actor,
        role_name=role_name,
        identity=identity,
        expected=c.expected if expected is None else expected,
        expected_state=c.expected_state if expected_state is None else expected_state,
        capability_owner_oid=c.capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _contract(c, db):
    return c.api.roles.whiteboard_source_writer_contract(
        db,
        capability_owner_oid=c.capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _admit(c, db, writer=None):
    return c.api.runtime.admit_whiteboard_source_writer(db, c.writer if writer is None else writer)


def _direct_lock(conn, identity=ACTIVE):
    return conn.execute(
        "SELECT public.miy_whiteboard_lock_source_writer(%s::integer,%s::text)",
        (identity.generation, identity.artifact),
    ).fetchone()


def _cas(db, c, state, *, collab_id=None, room_key=None):
    assert (
        db.scalar(
            text(
                "SELECT id FROM public.whiteboards WHERE id=:board AND trashed_at IS NULL FOR SHARE"
            ),
            {"board": c.board_id},
        )
        == c.board_id
    )
    return db.scalar(
        text("""
          UPDATE public.whiteboard_collab_documents
          SET yjs_state=:state,
              updated_at=CASE WHEN yjs_state IS DISTINCT FROM :state
                THEN timezone('UTC',clock_timestamp()) ELSE updated_at END
          WHERE id=:collab AND whiteboard_id=:board AND room_key=:room
          RETURNING id
        """),
        {
            "state": state,
            "collab": c.collab_id if collab_id is None else collab_id,
            "board": c.board_id,
            "room": c.room_key if room_key is None else room_key,
        },
    )


def _catalog_snapshot(c):
    with c.world.connect() as conn:
        return (
            conn.execute("SELECT count(*) FROM public.official_writer_principals").fetchone()[0],
            conn.execute("SELECT count(*) FROM public.audit_logs").fetchone()[0],
            conn.execute(
                "SELECT proowner::bigint,proacl::text,proconfig FROM pg_catalog.pg_proc WHERE oid=%s::regprocedure",
                (CAPABILITY,),
            ).fetchone(),
            conn.execute(
                "SELECT c.relname,c.relacl::text,a.attname,a.attacl::text FROM pg_catalog.pg_class c "
                "JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
                "WHERE c.oid IN ('public.whiteboards'::regclass,'public.whiteboard_collab_documents'::regclass) "
                "ORDER BY c.relname,a.attnum"
            ).fetchall(),
        )


@contextmanager
def _mutation_capture(engine):
    mutations = []

    def observe(_conn, _cursor, statement, *_):
        normalized = statement.lstrip().upper()
        if normalized.startswith(("GRANT ", "REVOKE ", "ALTER ")) or (
            normalized.startswith("INSERT ") and "AUDIT_LOGS" in normalized
        ):
            mutations.append(normalized.split()[0])

    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield mutations
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _wait_for_blocker(observer, waiter, holder):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if observer.execute(
            "SELECT %s=ANY(pg_catalog.pg_blocking_pids(%s))", (holder, waiter)
        ).fetchone()[0]:
            return
        time.sleep(0.02)
    pytest.fail("Native admission did not wait on its actual captured control-row holder")


def _replace_body(conn, signature):
    definition = conn.execute(
        "SELECT pg_catalog.pg_get_functiondef(%s::regprocedure)", (signature,)
    ).fetchone()[0]
    marker = re.search(r"\bAS (\$[A-Za-z0-9_]*\$)", definition)
    assert marker is not None
    ending = definition.index(marker.group(1), marker.end())
    conn.execute(definition[: marker.end()] + "\nBEGIN RETURN; END;\n" + definition[ending:])


@pytest.fixture
def writer_boundary(world):
    api = _api()
    board_id, collab_id = str(uuid4()), str(uuid4())
    room_key = "whiteboard:" + board_id + ":collab"
    state = _native_state("synthetic-service-original")
    stamp = datetime(2026, 10, 9, 0, 0, 0)
    # Only the migrated legacy fixture owns this seed; no source guard is bypassed.
    with Session(world.engine) as db:
        db.add(
            Whiteboard(
                id=board_id,
                owner_id=world.user_id,
                title="Synthetic service board",
                scene={"elements": [], "appState": {}, "files": {}},
                updated_at=stamp,
            )
        )
        db.flush()
        db.add(
            WhiteboardCollabDocument(
                id=collab_id,
                whiteboard_id=board_id,
                room_key=room_key,
                yjs_state=state,
                snapshot_scene={"elements": []},
                updated_at=stamp + timedelta(seconds=1),
            )
        )
        db.commit()
    with world.connect() as conn:
        migration_owner_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (CAPABILITY,)
        ).fetchone()[0]
        producer_owner_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (PRODUCER,)
        ).fetchone()[0]
    guard_owner, capability_owner = world.role(login=False), world.role(login=False)
    assert move(world, BASE, "active", state="draining") == DRAIN
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=guard_owner, expected=DRAIN)
        db.commit()
    with world.connect() as conn:
        guard_oid, capability_oid = _oid(conn, guard_owner), _oid(conn, capability_owner)
        assert conn.execute(
            "SELECT DISTINCT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer'"
        ).fetchall() == [(ROLE_GUARD,)]
    return SimpleNamespace(
        world=world,
        api=api,
        board_id=board_id,
        collab_id=collab_id,
        room_key=room_key,
        initial_state=state,
        initial_timestamp=stamp + timedelta(seconds=1),
        guard_owner=guard_owner,
        source_guard_owner_oid=guard_oid,
        capability_owner=capability_owner,
        capability_owner_oid=capability_oid,
        migration_owner_oid=migration_owner_oid,
        producer_owner_oid=producer_owner_oid,
        expected=DRAIN,
        expected_state="draining",
    )


@pytest.fixture
def writer_prepared(writer_boundary):
    c = writer_boundary
    c.source = c.world.role()
    with Session(c.world.engine) as db:
        assert _install(c, db) is None
        prepared = _prepare(c, db, c.source)
        assert prepared.profile_prepared is True
        c.writer = prepared.writer
        c.source_oid = prepared.principal.role_oid
        db.commit()
    assert move(c.world, DRAIN, "draining", state="active", artifact=ACTIVE.artifact) == ACTIVE
    c.expected, c.expected_state = ACTIVE, "active"
    c.source_engine = create_engine(
        sa_dsn(make_conninfo(c.world.dsn, user=c.source, password=PASSWORD)),
        pool_size=1,
        max_overflow=0,
    )
    try:
        yield c
    finally:
        c.source_engine.dispose()


def test_genuine_same_name_new_role_oid_cannot_reuse_immutable_binding(writer_prepared):
    c = writer_prepared
    c.source_engine.dispose()
    with c.world.connect() as conn:
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(c.source)))
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(c.source)))
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(c.source), sql.Literal(PASSWORD))
        )
        assert _oid(conn, c.source) != c.source_oid
        # Synthetic test EXEC exposes the identity check; it is no product grant.
        conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_whiteboard_lock_source_writer(integer,text) TO {}"
            ).format(sql.Identifier(c.source))
        )
    with c.world.connect(c.source) as conn:
        with pytest.raises(psycopg.Error) as caught:
            _direct_lock(conn)
        assert caught.value.sqlstate == "55000"
    with Session(c.world.engine) as db:
        with pytest.raises(WriterControlError):
            _prepare(c, db, c.source)
        db.rollback()
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused):
            _admit(c, db)
        db.rollback()


@pytest.mark.parametrize("target,finish", [("principal", "commit")])
def test_genuine_admission_share_locks_live_until_actual_caller_transaction_finish(
    writer_prepared, target, finish
):
    c = writer_prepared
    state = _native_state("synthetic-caller-transaction")
    with (
        c.world.connect(autocommit=True) as observer,
        c.world.connect() as controller,
        Session(c.source_engine) as db,
    ):
        controller_pid = controller.execute("SELECT pg_backend_pid()").fetchone()[0]
        controller.rollback()
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _admit(c, db) is None
        assert _cas(db, c, state) == c.collab_id
        statement = (
            "UPDATE official_runtime_ownership SET state='draining' WHERE scope='official.suite'"
            if target == "ownership"
            else "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_oid=%s"
        )
        parameters = () if target == "ownership" else (c.source_oid,)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(controller.execute, statement, parameters)
            try:
                _wait_for_blocker(observer, controller_pid, source_pid)
                assert not future.done()
                getattr(db, finish)()
                future.result(timeout=5)
                controller.commit()
            finally:
                db.rollback()
                controller.rollback()
        persisted = observer.execute(
            "SELECT yjs_state FROM whiteboard_collab_documents WHERE id=%s", (c.collab_id,)
        ).fetchone()[0]
        assert bytes(persisted) == (state if finish == "commit" else c.initial_state)
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused):
            _admit(c, db)
        db.rollback()


@pytest.mark.parametrize("change", ["revoked"])
def test_genuine_actual_control_row_wait_rechecks_original_identity_after_release(
    writer_prepared, change
):
    c = writer_prepared
    with (
        c.world.connect(autocommit=True) as observer,
        c.world.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        # All three connections are established before a control row is held.
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        target = (
            "official_writer_principals WHERE role_oid=%s"
            if change in {"revoked", "role_name"}
            else "official_runtime_ownership WHERE scope=%s"
        )
        key = c.source_oid if change in {"revoked", "role_name"} else SUITE_SCOPE
        revoker.execute("SELECT 1 FROM " + target + " FOR UPDATE", (key,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_admit, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder_pid)
                assert not future.done()
                changes = {
                    "revoked": (
                        "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_oid=%s",
                        (c.source_oid,),
                    ),
                    "draining": (
                        "UPDATE official_runtime_ownership SET state='draining' WHERE scope=%s",
                        (SUITE_SCOPE,),
                    ),
                    "generation": (
                        "UPDATE official_runtime_ownership SET generation=4 WHERE scope=%s",
                        (SUITE_SCOPE,),
                    ),
                    "artifact": (
                        "UPDATE official_runtime_ownership SET artifact=%s WHERE scope=%s",
                        ("sha256:" + "c" * 64, SUITE_SCOPE),
                    ),
                }
                if change == "role_name":
                    renamed = "renamed_writer_" + uuid4().hex[:12]
                    revoker.execute(
                        sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                            sql.Identifier(c.source), sql.Identifier(renamed)
                        )
                    )
                else:
                    revoker.execute(*changes[change])
                revoker.commit()
                if change == "role_name":
                    c.world.roles[c.world.roles.index(c.source)] = renamed
                with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_source_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()
        assert (
            bytes(
                observer.execute(
                    "SELECT yjs_state FROM whiteboard_collab_documents WHERE id=%s", (c.collab_id,)
                ).fetchone()[0]
            )
            == c.initial_state
        )


def _migration_boundary_snapshot(world):
    """Only synthetic owned rows and public catalogs; never auth secrets."""
    with world.connect() as conn:
        return {
            "version": conn.execute("SELECT version_num FROM alembic_version").fetchone()[0],
            "capabilities": conn.execute(
                "SELECT pg_get_function_identity_arguments(p.oid),p.proowner::bigint,"
                "p.prosecdef,p.proconfig,p.proacl::text,pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_source_writer' "
                "ORDER BY pg_get_function_identity_arguments(p.oid)"
            ).fetchall(),
            "existing": (
                conn.execute("SELECT * FROM whiteboards ORDER BY id").fetchall(),
                conn.execute("SELECT * FROM whiteboard_collab_documents ORDER BY id").fetchall(),
                conn.execute("SELECT * FROM official_runtime_ownership ORDER BY scope").fetchall(),
                conn.execute(
                    "SELECT * FROM official_writer_principals ORDER BY role_oid"
                ).fetchall(),
                conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0],
                conn.execute(
                    "SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE t.tgname IN ('miy_official_source_writer','miy_official_principal_immutable') "
                    "ORDER BY n.nspname,c.relname,t.tgname"
                ).fetchall(),
                conn.execute(
                    "SELECT p.proname,p.proowner::bigint,p.proacl::text,p.proconfig,pg_get_functiondef(p.oid) "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname IN "
                    "('miy_guard_official_source_writer','miy_guard_official_source_writer_by_role',"
                    "'miy_recording_lock_producer','miy_immutable_official_writer_principal') "
                    "ORDER BY p.proname"
                ).fetchall(),
                conn.execute(
                    "SELECT oid::bigint,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
                    "rolcreaterole,rolreplication,rolbypassrls,rolconfig FROM pg_roles "
                    "WHERE rolname=ANY(%s::text[]) ORDER BY oid",
                    (world.roles,),
                ).fetchall(),
                conn.execute(
                    "SELECT c.relname,c.relacl::text,a.attname,a.attacl::text FROM pg_class c "
                    "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
                    "WHERE c.oid IN ('public.whiteboards'::regclass,'public.whiteboard_collab_documents'::regclass) "
                    "ORDER BY c.relname,a.attnum"
                ).fetchall(),
            ),
        }


@pytest.mark.parametrize("world", ["wb_source_writer_20261009"], indirect=True)
def test_source_capability_install_write_drain_retains_business_data(writer_prepared):
    c = writer_prepared
    with c.world.connect(c.source) as conn:
        assert conn.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),"
            "has_function_privilege(current_user,%s,'EXECUTE')",
            (CAPABILITY, PRODUCER),
        ).fetchone() == (True, False)
        denied(conn, "SELECT scene FROM whiteboards")
        denied(conn, "UPDATE whiteboards SET title='forbidden' WHERE false")
    c = writer_prepared
    next_state = _native_state("synthetic-service-updated")
    with Session(c.source_engine) as db:
        assert _admit(c, db) is None
        assert db.in_transaction()
        assert _cas(db, c, next_state) == c.collab_id
        db.commit()
        assert _admit(c, db) is None
        first_stamp = db.scalar(
            text("SELECT updated_at FROM public.whiteboard_collab_documents WHERE id=:id"),
            {"id": c.collab_id},
        )
        assert _cas(db, c, next_state) == c.collab_id
        db.commit()
        assert _admit(c, db) is None
        assert _cas(db, c, _native_state("wrong-row"), collab_id=str(uuid4())) is None
        assert _cas(db, c, _native_state("wrong-key"), room_key="different-incarnation") is None
        db.commit()
    with c.world.connect() as conn:
        state, stamp, snapshot = conn.execute(
            "SELECT yjs_state,updated_at,snapshot_scene FROM whiteboard_collab_documents WHERE id=%s",
            (c.collab_id,),
        ).fetchone()
        assert bytes(state) == next_state and stamp == first_stamp
        assert snapshot == {"elements": []}
        assert conn.execute(
            "SELECT title,scene FROM whiteboards WHERE id=%s", (c.board_id,)
        ).fetchone() == ("Synthetic service board", {"elements": [], "appState": {}, "files": {}})
    from alembic import command
    from test_alembic_migrations import _migration_config

    c = writer_prepared
    before = _migration_boundary_snapshot(c.world)
    with pytest.raises(RuntimeError, match="whiteboard_source_writer_requires_draining"):
        command.downgrade(_migration_config(sa_dsn(c.world.dsn)), "file_effect_20261007")
    assert _migration_boundary_snapshot(c.world) == before
    with Session(c.source_engine) as db:
        assert _admit(c, db) is None
        db.rollback()
    from alembic import command
    from test_alembic_migrations import _migration_config

    c = writer_prepared
    drained = move(c.world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation == 4 and drained.artifact == ACTIVE.artifact
    before = _migration_boundary_snapshot(c.world)
    command.downgrade(_migration_config(sa_dsn(c.world.dsn)), "file_effect_20261007")
    removed = _migration_boundary_snapshot(c.world)
    assert removed["version"] == "file_effect_20261007" and removed["capabilities"] == []
    assert removed["existing"] == before["existing"]
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
            _admit(c, db)
        assert str(caught.value) == "whiteboard_source_writer_refused"
        db.rollback()
    assert _migration_boundary_snapshot(c.world) == removed
