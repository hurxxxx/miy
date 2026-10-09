"""Inactive Whiteboard service SQL admission in disposable migrated PostgreSQL.

The actual LOGIN/CAS cases prove a fixed service principal and producer fence.
They supply synthetic test authority; they do not prove current actor/resource
ACL through COMMIT, select a runtime factory, or activate an operational service.
Missing new APIs are readiness failures, never behavioral RED evidence.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from importlib import import_module
import re
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
import y_py as Y

from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_contracts import (
    COVERED_SOURCE_TABLES,
    SUITE_SCOPE,
    WRITER_TRANSPORT_TABLES,
)
from miy_api.domains.official_apps.writer_roles import (
    LEGACY_GUARD,
    ROLE_GUARD,
    RuntimePrincipal,
    install_role_guard,
    revoke_principal,
)
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument
from miy_api.domains.whiteboard.scene_state import _persistence_sql_deadline
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
    world as world,  # noqa: F401
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


def test_pure_fixed_two_table_service_profile_and_frozen_original_identity():
    api = _api()
    assert api.roles.PROFILE == "whiteboard_source_service_admission_v1"
    assert api.roles.CAPABILITY == CAPABILITY
    assert api.roles.SOURCE_READ_COLUMNS == READ_COLUMNS
    assert api.roles.SOURCE_UPDATE_COLUMNS == UPDATE_COLUMNS
    assert sum(map(len, READ_COLUMNS.values())) == 8
    assert sum(map(len, UPDATE_COLUMNS.values())) == 4
    writer = api.roles.WhiteboardSourceWriterProfile(101, "synthetic_writer", ACTIVE, 102, 103, 104)
    assert writer.identity is ACTIVE
    with pytest.raises(FrozenInstanceError):
        writer.role_oid = 999


@pytest.mark.parametrize(
    "change",
    [
        {"role_oid": True},
        {"role_oid": 0},
        {"role_name": "bad-role"},
        {"capability_owner_oid": False},
        {"producer_owner_oid": -1},
        {"source_guard_owner_oid": 0},
        {"identity": BASE},
        {
            "identity": SimpleNamespace(
                scope=SUITE_SCOPE, owner="legacy", generation=3, artifact=ACTIVE.artifact
            )
        },
    ],
)
def test_pure_invalid_profile_refuses_without_sql(change):
    api = _api()
    values = dict(
        role_oid=101,
        role_name="synthetic_writer",
        identity=ACTIVE,
        capability_owner_oid=102,
        producer_owner_oid=103,
        source_guard_owner_oid=104,
    )
    values.update(change)
    with pytest.raises(ValueError):
        api.roles.WhiteboardSourceWriterProfile(**values)


def test_pure_unprepared_descriptor_and_non_session_refuse_before_connection():
    api = _api()
    writer = api.roles.WhiteboardSourceWriterProfile(101, "synthetic_writer", ACTIVE, 102, 103, 104)
    for db, descriptor in ((object(), writer), (object(), SimpleNamespace(identity=ACTIVE))):
        with pytest.raises(api.runtime.WhiteboardSourceWriterRefused) as caught:
            api.runtime.admit_whiteboard_source_writer(db, descriptor)
        assert str(caught.value) == "whiteboard_source_writer_refused"


def test_genuine_full_migration_installs_private_inactive_capability_with_legacy_guard(world):
    _api()
    with world.connect() as conn:
        assert conn.execute("SHOW server_version_num").fetchone()[0].startswith("18")
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "wb_source_writer_20261009"
        )
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert conn.execute(
            "SELECT active_owner,state,generation,artifact FROM official_runtime_ownership WHERE scope='official.suite'"
        ).fetchone() == ("legacy", "active", 1, None)
        guards = conn.execute(
            "SELECT c.relname,p.proname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer'"
        ).fetchall()
        assert {row[0] for row in guards} == set((*COVERED_SOURCE_TABLES, *WRITER_TRANSPORT_TABLES))
        assert {row[1] for row in guards} == {LEGACY_GUARD}
        assert conn.execute(
            "SELECT prosecdef,proconfig,pg_get_function_result(oid) FROM pg_proc WHERE oid=%s::regprocedure",
            (CAPABILITY,),
        ).fetchone() == (True, ["search_path=pg_catalog, pg_temp"], "void")
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_proc p,LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=%s::regprocedure AND a.grantee=0 AND a.privilege_type='EXECUTE')",
            (CAPABILITY,),
        ).fetchone()[0]
        conn.execute("UPDATE whiteboard_collab_documents SET writer_scope=writer_scope WHERE false")


def test_genuine_legacy_guard_never_becomes_preparation_readiness(world):
    api = _api()
    source, owner = world.role(), world.role(login=False)
    with world.connect() as conn:
        migration_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (CAPABILITY,)
        ).fetchone()[0]
        producer_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (PRODUCER,)
        ).fetchone()[0]
        guard_oid = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid='public.miy_guard_official_source_writer_by_role()'::regprocedure"
        ).fetchone()[0]
        owner_oid = _oid(conn, owner)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            api.roles.prepare_whiteboard_source_writer_principal(
                db,
                world.actor,
                role_name=source,
                identity=ACTIVE,
                expected=BASE,
                expected_state="active",
                capability_owner_oid=owner_oid,
                producer_owner_oid=producer_oid,
                source_guard_owner_oid=guard_oid,
            )
        db.rollback()
    assert move(world, BASE, "active", state="draining") == DRAIN
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            api.roles.install_whiteboard_source_writer_guard(
                db,
                world.actor,
                guard_owner=owner,
                expected=DRAIN,
                expected_migration_owner_oid=migration_oid,
                expected_producer_owner_oid=producer_oid,
                expected_source_guard_owner_oid=guard_oid,
            )
        db.rollback()
        assert (
            db.scalar(select(RuntimePrincipal).where(RuntimePrincipal.role_name == source)) is None
        )


def test_genuine_exact_effective_columns_and_owned_capability_chain(writer_prepared):
    c = writer_prepared
    with Session(c.world.engine) as db:
        assert _contract(c, db) is None
    with c.world.connect(c.source) as conn:
        assert conn.execute("SELECT session_user,current_user").fetchone() == (c.source, c.source)
        rows = conn.execute(
            "SELECT n.nspname,c.relname,a.attname,has_column_privilege(current_user,c.oid,a.attnum,'SELECT'),"
            "has_column_privilege(current_user,c.oid,a.attnum,'UPDATE'),has_column_privilege(current_user,c.oid,a.attnum,'INSERT,REFERENCES'),"
            "has_column_privilege(current_user,c.oid,a.attnum,'SELECT WITH GRANT OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION,REFERENCES WITH GRANT OPTION') "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid "
            "WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','m','f') AND "
            + USER_NAMESPACE
        ).fetchall()
        actual_read = {
            (table, column)
            for schema, table, column, read, *_ in rows
            if read and schema == "public"
        }
        actual_update = {
            (table, column)
            for schema, table, column, _, update, *_ in rows
            if update and schema == "public"
        }
        assert actual_read == {
            (table, column) for table, columns in READ_COLUMNS.items() for column in columns
        }
        assert actual_update == {
            (table, column) for table, columns in UPDATE_COLUMNS.items() for column in columns
        }
        assert not any(
            other or delegation or (schema != "public" and (read or update))
            for schema, _, _, read, update, other, delegation in rows
        )
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m','f') AND "
            + USER_NAMESPACE
            + " AND has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN'))"
        ).fetchone()[0]
        assert conn.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE'),has_function_privilege(current_user,%s,'EXECUTE'),has_function_privilege(current_user,%s,'EXECUTE WITH GRANT OPTION')",
            (CAPABILITY, PRODUCER, CAPABILITY),
        ).fetchone() == (True, False, False)
        assert not conn.execute(
            "SELECT has_database_privilege(current_user,current_database(),'CREATE')"
        ).fetchone()[0]
    with c.world.connect() as conn:
        assert (
            conn.execute(
                "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (CAPABILITY,)
            ).fetchone()[0]
            == c.capability_owner_oid
        )
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (c.capability_owner, PRODUCER)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m','f') AND "
            + USER_NAMESPACE
            + " AND (has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))",
            (c.capability_owner, c.capability_owner),
        ).fetchone()[0]


def test_genuine_source_business_acl_and_core_privileges_are_denied(writer_prepared):
    with writer_prepared.world.connect(writer_prepared.source) as conn:
        for statement in (
            "SELECT owner_id FROM whiteboards",
            "SELECT company_visible FROM whiteboards",
            "SELECT scene FROM whiteboards",
            "SELECT writer_scope FROM whiteboards",
            "SELECT snapshot_scene FROM whiteboard_collab_documents",
            "SELECT last_snapshot_at FROM whiteboard_collab_documents",
            "UPDATE whiteboards SET title='forbidden' WHERE false",
            "UPDATE whiteboard_collab_documents SET room_key='forbidden' WHERE false",
            "INSERT INTO whiteboard_collab_documents(id) VALUES ('forbidden')",
            "DELETE FROM whiteboard_collab_documents WHERE false",
            "SELECT id FROM users",
            "SELECT id FROM auth_sessions",
            "SELECT id FROM whiteboard_user_shares",
            "SELECT scope FROM official_runtime_ownership",
            "SELECT role_oid FROM official_writer_principals",
        ):
            denied(conn, statement)


def test_genuine_restricted_board_share_and_captured_cas_preserve_noop_timestamp(writer_prepared):
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


def test_genuine_exact_replay_is_grant0_audit0_and_fresh_preparation_rollback_is_atomic(
    writer_prepared,
):
    c = writer_prepared
    before = _catalog_snapshot(c)
    with _mutation_capture(c.world.engine) as mutations, Session(c.world.engine) as db:
        replay = _prepare(c, db, c.source)
        assert replay.profile_prepared is True and replay.writer == c.writer
        assert db.in_transaction() and mutations == []
        db.commit()
    assert _catalog_snapshot(c) == before
    fresh = c.world.role()
    with Session(c.world.engine) as db:
        prepared = _prepare(c, db, fresh)
        assert prepared.principal.role_name == fresh and db.in_transaction()
        db.rollback()
    assert _catalog_snapshot(c) == before
    with c.world.connect(fresh) as conn:
        assert not conn.execute(
            "SELECT has_column_privilege(current_user,'whiteboard_collab_documents','yjs_state','UPDATE')"
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (CAPABILITY,)
        ).fetchone()[0]


def test_genuine_owner_install_rollback_and_same_owner_exact_replay(writer_boundary):
    c = writer_boundary
    before = _catalog_snapshot(c)
    with Session(c.world.engine) as db:
        assert _install(c, db) is None and db.in_transaction()
        db.rollback()
    assert _catalog_snapshot(c) == before
    with Session(c.world.engine) as db:
        _install(c, db)
        db.commit()
    installed = _catalog_snapshot(c)
    with _mutation_capture(c.world.engine) as mutations, Session(c.world.engine) as db:
        _install(c, db)
        assert mutations == []
        db.commit()
    assert _catalog_snapshot(c) == installed


@pytest.mark.parametrize("change", ["partial", "broad", "revoked"])
def test_genuine_existing_profile_is_never_expanded_or_restored(writer_prepared, change):
    c = writer_prepared
    with c.world.connect() as conn:
        if change == "partial":
            conn.execute(
                sql.SQL("REVOKE UPDATE(yjs_state) ON whiteboard_collab_documents FROM {}").format(
                    sql.Identifier(c.source)
                )
            )
        elif change == "broad":
            conn.execute(
                sql.SQL("GRANT SELECT ON whiteboard_collab_documents TO {}").format(
                    sql.Identifier(c.source)
                )
            )
    if change == "revoked":
        with Session(c.world.engine) as db:
            revoke_principal(
                db, c.world.actor, role_oid=c.source_oid, expected=ACTIVE, expected_state="active"
            )
            db.commit()
    before = _catalog_snapshot(c)
    with _mutation_capture(c.world.engine) as mutations, Session(c.world.engine) as db:
        with pytest.raises(WriterControlError):
            _prepare(c, db, c.source)
        db.rollback()
        assert mutations == []
    assert _catalog_snapshot(c) == before
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
            _admit(c, db)
        assert str(caught.value) == "whiteboard_source_writer_refused"
        db.rollback()


@pytest.mark.parametrize(
    "hazard",
    [
        "pgx_column",
        "public_column",
        "pgx_owner",
        "schema_create",
        "sequence",
        "membership",
        "grant_option",
        "security_definer",
        "owner_relation",
        "maintain",
        "database_create",
    ],
)
def test_genuine_fresh_roles_refuse_all_user_namespace_and_ambient_authority(
    writer_prepared, hazard
):
    c = writer_prepared
    source = c.world.role()
    with c.world.connect() as conn:
        conn.execute("CREATE SCHEMA pgx_whiteboard_profile")
        conn.execute("CREATE TABLE pgx_whiteboard_profile.hidden(secret text)")
        if hazard == "pgx_column":
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA pgx_whiteboard_profile TO {}").format(
                    sql.Identifier(source)
                )
            )
            conn.execute(
                sql.SQL("GRANT SELECT(secret) ON pgx_whiteboard_profile.hidden TO {}").format(
                    sql.Identifier(source)
                )
            )
        elif hazard == "public_column":
            conn.execute("GRANT SELECT(secret) ON pgx_whiteboard_profile.hidden TO PUBLIC")
        elif hazard == "pgx_owner":
            conn.execute(
                sql.SQL("ALTER TABLE pgx_whiteboard_profile.hidden OWNER TO {}").format(
                    sql.Identifier(source)
                )
            )
        elif hazard == "schema_create":
            conn.execute(
                sql.SQL("GRANT CREATE ON SCHEMA pgx_whiteboard_profile TO {}").format(
                    sql.Identifier(source)
                )
            )
        elif hazard == "sequence":
            conn.execute("CREATE SEQUENCE pgx_whiteboard_profile.hidden_sequence")
            conn.execute(
                sql.SQL(
                    "GRANT USAGE ON SEQUENCE pgx_whiteboard_profile.hidden_sequence TO {}"
                ).format(sql.Identifier(source))
            )
        elif hazard == "membership":
            parent = c.world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(parent), sql.Identifier(source))
            )
        elif hazard == "grant_option":
            conn.execute(
                sql.SQL("GRANT SELECT(id) ON whiteboards TO {} WITH GRANT OPTION").format(
                    sql.Identifier(source)
                )
            )
        elif hazard == "security_definer":
            conn.execute(
                "CREATE FUNCTION pgx_whiteboard_profile.escape() RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$BEGIN RETURN; END$$"
            )
        elif hazard == "owner_relation":
            conn.execute(
                sql.SQL("GRANT SELECT(secret) ON pgx_whiteboard_profile.hidden TO {}").format(
                    sql.Identifier(c.capability_owner)
                )
            )
        elif hazard == "maintain":
            conn.execute(
                sql.SQL("GRANT MAINTAIN ON whiteboards TO {}").format(sql.Identifier(source))
            )
        else:
            database = conn.execute("SELECT current_database()").fetchone()[0]
            conn.execute(
                sql.SQL("GRANT CREATE ON DATABASE {} TO {}").format(
                    sql.Identifier(database), sql.Identifier(source)
                )
            )
    before = _catalog_snapshot(c)
    with Session(c.world.engine) as db:
        with pytest.raises(WriterControlError):
            _prepare(c, db, source)
        db.rollback()
    assert _catalog_snapshot(c) == before


@pytest.mark.parametrize(
    "tamper",
    [
        "body",
        "search_path",
        "owner",
        "overload",
        "public_exec",
        "producer_body",
        "producer_owner",
        "producer_overload",
        "guard_owner",
    ],
)
def test_genuine_catalog_tamper_never_installs_or_adopts_an_unexpected_capability(
    writer_boundary, tamper
):
    c = writer_boundary
    other = c.world.role(login=False)
    with c.world.connect() as conn:
        if tamper == "body":
            _replace_body(conn, CAPABILITY)
        elif tamper == "search_path":
            conn.execute(
                "ALTER FUNCTION public.miy_whiteboard_lock_source_writer(integer,text) SET search_path=public"
            )
        elif tamper == "owner":
            conn.execute(
                sql.SQL(
                    "ALTER FUNCTION public.miy_whiteboard_lock_source_writer(integer,text) OWNER TO {}"
                ).format(sql.Identifier(other))
            )
        elif tamper == "overload":
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_source_writer(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_source_writer(text) FROM PUBLIC"
            )
        elif tamper == "public_exec":
            conn.execute(
                "GRANT EXECUTE ON FUNCTION public.miy_whiteboard_lock_source_writer(integer,text) TO PUBLIC"
            )
        elif tamper == "producer_body":
            _replace_body(conn, PRODUCER)
        elif tamper == "producer_owner":
            conn.execute(
                sql.SQL(
                    "ALTER FUNCTION public.miy_recording_lock_producer(bigint,text,integer,text) OWNER TO {}"
                ).format(sql.Identifier(other))
            )
        elif tamper == "producer_overload":
            conn.execute(
                "CREATE FUNCTION public.miy_recording_lock_producer(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_recording_lock_producer(text) FROM PUBLIC"
            )
        else:
            conn.execute(
                sql.SQL(
                    "ALTER FUNCTION public.miy_guard_official_source_writer_by_role() OWNER TO {}"
                ).format(sql.Identifier(other))
            )
    before = _catalog_snapshot(c)
    with _mutation_capture(c.world.engine) as mutations, Session(c.world.engine) as db:
        with pytest.raises(WriterControlError):
            _install(c, db)
        db.rollback()
        assert mutations == []
    assert _catalog_snapshot(c) == before


@pytest.mark.parametrize(
    "change",
    [
        {"role_oid": 999999999},
        {"role_name": "different_writer"},
        {"identity": WriterIdentity(SUITE_SCOPE, "legacy", 2, ACTIVE.artifact)},
        {"identity": WriterIdentity(SUITE_SCOPE, "legacy", 3, "sha256:" + "b" * 64)},
        {"capability_owner_oid": 999999998},
        {"producer_owner_oid": 999999997},
        {"source_guard_owner_oid": 999999996},
    ],
)
def test_genuine_original_descriptor_mismatch_is_private_refusal(writer_prepared, change):
    c = writer_prepared
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
            _admit(c, db, replace(c.writer, **change))
        assert str(caught.value) == "whiteboard_source_writer_refused"
        assert isinstance(caught.value.reason, str) and caught.value.reason
        db.rollback()
    with c.world.connect() as conn:
        assert (
            bytes(
                conn.execute(
                    "SELECT yjs_state FROM whiteboard_collab_documents WHERE id=%s", (c.collab_id,)
                ).fetchone()[0]
            )
            == c.initial_state
        )


@pytest.mark.parametrize("spoof", ["set_role", "guc", "old_generation", "wrong_artifact"])
def test_genuine_sql_wrapper_uses_actual_session_user_and_original_expected_identity(
    writer_prepared, spoof
):
    c = writer_prepared
    role = c.source if spoof in {"old_generation", "wrong_artifact"} else None
    with c.world.connect(role) as conn:
        if spoof == "set_role":
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(c.source)))
            assert conn.execute("SELECT session_user,current_user").fetchone() == (
                "postgres",
                c.source,
            )
        elif spoof == "guc":
            conn.execute(
                "SELECT set_config('miy.official_writer',%s,true)",
                ('{"generation":3,"owner":"legacy"}',),
            )
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(c.source)))
        expected = (
            WriterIdentity(SUITE_SCOPE, "legacy", 2, ACTIVE.artifact)
            if spoof == "old_generation"
            else WriterIdentity(SUITE_SCOPE, "legacy", 3, "sha256:" + "b" * 64)
            if spoof == "wrong_artifact"
            else ACTIVE
        )
        with pytest.raises(psycopg.Error) as caught:
            _direct_lock(conn, expected)
        assert caught.value.sqlstate == "55000"
        conn.rollback()
    with c.world.connect(c.source) as conn:
        _direct_lock(conn)
        conn.commit()


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


@pytest.mark.parametrize("target", ["ownership", "principal"])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
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


@pytest.mark.parametrize("change", ["revoked", "draining", "generation", "artifact", "role_name"])
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


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_genuine_caller_decreasing_sql_deadline_and_pool_local_settings_reset(
    writer_prepared, finish
):
    c = writer_prepared
    with Session(c.source_engine) as db:
        baseline = tuple(
            db.execute(
                text(
                    "SELECT current_setting('statement_timeout'),current_setting('lock_timeout'),current_setting('search_path'),pg_backend_pid()"
                )
            ).one()
        )
        db.rollback()
        with _persistence_sql_deadline(db.connection(), 5):
            assert _admit(c, db) is None
            first = db.scalar(text("SELECT current_setting('statement_timeout')::interval"))
            db.execute(text("SELECT pg_sleep(0.06)"))
            second = db.scalar(text("SELECT current_setting('statement_timeout')::interval"))
            assert timedelta(0) < second < first <= timedelta(seconds=5)
            getattr(db, finish)()
    with Session(c.source_engine) as db:
        actual = tuple(
            db.execute(
                text(
                    "SELECT current_setting('statement_timeout'),current_setting('lock_timeout'),current_setting('search_path'),pg_backend_pid()"
                )
            ).one()
        )
        assert actual == baseline
        assert _admit(c, db) is None
        db.rollback()


def test_genuine_caller_sql_deadline_bounds_real_statement_and_failed_pool_reuse(writer_prepared):
    c = writer_prepared
    with Session(c.source_engine) as db:
        baseline_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        with _persistence_sql_deadline(db.connection(), 2):
            assert _admit(c, db) is None
            started = time.monotonic()
            with pytest.raises(DBAPIError) as caught:
                db.execute(text("SELECT pg_sleep(4)"))
            assert caught.value.orig.sqlstate == "57014"
            assert time.monotonic() - started < 3
            db.rollback()
    with Session(c.source_engine) as db:
        assert db.scalar(text("SELECT pg_backend_pid()")) == baseline_pid
        assert db.scalar(text("SHOW statement_timeout")) == "0"
        assert db.scalar(text("SHOW lock_timeout")) == "0"
        assert _admit(c, db) is None
        db.rollback()


@pytest.mark.parametrize(
    "hazard", ["source_nologin", "source_inherit", "owner_login", "owner_membership"]
)
def test_genuine_supplied_login_and_nologin_attributes_are_never_repaired(writer_boundary, hazard):
    c = writer_boundary
    source = c.world.role(login=hazard != "source_nologin")
    with c.world.connect() as conn:
        if hazard == "source_inherit":
            conn.execute(sql.SQL("ALTER ROLE {} INHERIT").format(sql.Identifier(source)))
        elif hazard == "owner_login":
            conn.execute(sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(c.capability_owner)))
        elif hazard == "owner_membership":
            parent = c.world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(parent), sql.Identifier(c.capability_owner)
                )
            )
    before = _catalog_snapshot(c)
    with Session(c.world.engine) as db:
        if hazard.startswith("owner_"):
            with pytest.raises(WriterControlError):
                _install(c, db)
        else:
            _install(c, db)
            db.commit()
            before = _catalog_snapshot(c)
            with pytest.raises(WriterControlError):
                _prepare(c, db, source)
        db.rollback()
    assert _catalog_snapshot(c) == before


def test_genuine_admin_revoked_after_native_grants_rolls_back_entire_preparation(writer_boundary):
    c = writer_boundary
    with Session(c.world.engine) as db:
        _install(c, db)
        db.commit()
    source = c.world.role()
    before = _catalog_snapshot(c)
    with c.world.connect() as revoker:
        # Preconnect before ownership locks; the native mutation never uses a pool startup.
        revoker.execute("SELECT pg_backend_pid()")
        revoker.rollback()
        revoked = []

        def after_grant(_conn, _cursor, statement, *_):
            if (
                not revoked
                and statement.lstrip().upper().startswith("GRANT ")
                and source in statement
            ):
                revoker.execute(
                    "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
                    (c.world.session_id,),
                )
                revoker.commit()
                revoked.append(True)

        event.listen(c.world.engine, "after_cursor_execute", after_grant)
        try:
            with Session(c.world.engine) as db:
                with pytest.raises((WriterControlError, HTTPException)):
                    _prepare(c, db, source)
                assert revoked == [True]
                db.rollback()
        finally:
            event.remove(c.world.engine, "after_cursor_execute", after_grant)
    assert _catalog_snapshot(c) == before
    with c.world.connect(source) as conn:
        assert not conn.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')", (CAPABILITY,)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_column_privilege(current_user,'whiteboard_collab_documents','yjs_state','UPDATE')"
        ).fetchone()[0]


def test_genuine_generic_producer_substitution_is_only_synthetic_observation(writer_prepared):
    """Test-only EXEC observes the old generic seam; no active vulnerability claim."""
    c = writer_prepared
    other = c.world.role()
    with Session(c.world.engine) as db:
        other_writer = _prepare(c, db, other).writer
        db.commit()
    with c.world.connect() as conn:
        conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_recording_lock_producer(bigint,text,integer,text) TO {}"
            ).format(sql.Identifier(c.source))
        )
    with c.world.connect(c.source) as conn:
        assert conn.execute("SELECT session_user").fetchone()[0] == c.source
        conn.execute(
            "SELECT public.miy_recording_lock_producer(%s::bigint,%s::text,%s::integer,%s::text)",
            (other_writer.role_oid, other_writer.role_name, ACTIVE.generation, ACTIVE.artifact),
        )
        conn.rollback()
    # The new service profile refuses that additional generic EXEC authority.
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused):
            _admit(c, db)
        db.rollback()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "AUTOCOMMIT"])
def test_genuine_runtime_requires_caller_read_committed_transaction(writer_prepared, isolation):
    c = writer_prepared
    with c.source_engine.connect().execution_options(isolation_level=isolation) as connection:
        with Session(bind=connection) as db:
            with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
                _admit(c, db)
            assert str(caught.value) == "whiteboard_source_writer_refused"
            db.rollback()
    with Session(c.source_engine) as db:
        assert _admit(c, db) is None
        db.rollback()


@pytest.mark.parametrize("grant_option", [False, True])
def test_genuine_source_guard_owner_excess_maintain_is_refused_without_repair(
    writer_prepared, grant_option
):
    c = writer_prepared
    with c.world.connect() as conn:
        conn.execute(
            sql.SQL("GRANT MAINTAIN ON public.users TO {}{}").format(
                sql.Identifier(c.guard_owner),
                sql.SQL(" WITH GRANT OPTION" if grant_option else ""),
            )
        )
        assert conn.execute(
            "SELECT has_table_privilege(%s,'public.users','MAINTAIN'),"
            "has_table_privilege(%s,'public.users','MAINTAIN WITH GRANT OPTION')",
            (c.guard_owner, c.guard_owner),
        ).fetchone() == (True, grant_option)
    before = _catalog_snapshot(c)
    with _mutation_capture(c.world.engine) as mutations, Session(c.world.engine) as db:
        with pytest.raises(WriterControlError):
            _contract(c, db)
        db.rollback()
        assert mutations == []
    with Session(c.source_engine) as db:
        with pytest.raises(c.api.runtime.WhiteboardSourceWriterRefused) as caught:
            _admit(c, db)
        assert str(caught.value) == "whiteboard_source_writer_refused"
        db.rollback()
    assert _catalog_snapshot(c) == before
    with c.world.connect() as conn:
        assert conn.execute(
            "SELECT has_table_privilege(%s,'public.users','MAINTAIN'),"
            "has_table_privilege(%s,'public.users','MAINTAIN WITH GRANT OPTION')",
            (c.guard_owner, c.guard_owner),
        ).fetchone() == (True, grant_option)
        assert (
            bytes(
                conn.execute(
                    "SELECT yjs_state FROM whiteboard_collab_documents WHERE id=%s",
                    (c.collab_id,),
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


def test_genuine_legacy_migration_roundtrip_preserves_existing_whiteboard_boundary(world):
    from alembic import command
    from test_alembic_migrations import _migration_config

    board_id, collab_id = str(uuid4()), str(uuid4())
    state = _native_state("legacy-roundtrip-preserved")
    with Session(world.engine) as db:
        db.add(
            Whiteboard(
                id=board_id,
                owner_id=world.user_id,
                title="Legacy roundtrip",
                scene={"elements": [], "appState": {}, "files": {}},
            )
        )
        db.flush()
        db.add(
            WhiteboardCollabDocument(
                id=collab_id,
                whiteboard_id=board_id,
                room_key="legacy-roundtrip:" + board_id,
                yjs_state=state,
                snapshot_scene={"elements": []},
            )
        )
        db.commit()
    before = _migration_boundary_snapshot(world)
    assert before["version"] == "wb_source_writer_20261009"
    assert len(before["capabilities"]) == 1
    config = _migration_config(sa_dsn(world.dsn))
    command.downgrade(config, "file_effect_20261007")
    removed = _migration_boundary_snapshot(world)
    assert removed["version"] == "file_effect_20261007" and removed["capabilities"] == []
    assert removed["existing"] == before["existing"]
    command.upgrade(config, "head")
    assert _migration_boundary_snapshot(world) == before


def test_genuine_hardened_active_migration_rollback_refuses_without_changes(writer_prepared):
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


def test_genuine_hardened_draining_migration_removes_only_inactive_capability(writer_prepared):
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


@pytest.mark.parametrize("tamper", ["body", "overload"])
def test_genuine_migration_rollback_refuses_tampered_capability_without_changes(
    writer_boundary, tamper
):
    from alembic import command
    from test_alembic_migrations import _migration_config

    world = writer_boundary.world
    with world.connect() as conn:
        if tamper == "body":
            _replace_body(conn, CAPABILITY)
        else:
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_source_writer(text) "
                "RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_source_writer(text) FROM PUBLIC"
            )
    before = _migration_boundary_snapshot(world)
    with pytest.raises(RuntimeError, match="whiteboard_source_writer_capability_contract_invalid"):
        command.downgrade(_migration_config(sa_dsn(world.dsn)), "file_effect_20261007")
    assert _migration_boundary_snapshot(world) == before
