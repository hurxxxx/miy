"""Inactive owner-only actor admission in disposable, migrated PostgreSQL.

Core auth uses its original restricted 14-table/87-column LOGIN. The distinct
actor LOGIN has no business/Core SELECT or DML; its private capability holds
current positive witnesses until caller COMMIT/rollback. A synthetic, explicitly
registered privileged Core fixture may mutate metadata through the unchanged
Source trigger. This is fixture authority, not operational role provisioning.

No runtime factory, Yjs save, full resource ACL or physical-COMMIT expiry fence
is activated. Database locators detect known different databases, not a
cryptographic cluster identity. Missing APIs are readiness failures, never RED.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from importlib import import_module
import json
import re
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from fastapi import HTTPException
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.models import User
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
from miy_api.domains.whiteboard.scene_state import _persistence_sql_deadline
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, BASE, DRAIN, PASSWORD, move
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
    bound_official as bound_official,  # noqa: F401
    client as client,  # noqa: F401
    http_world as http_world,  # noqa: F401
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
    role_template as role_template,  # noqa: F401
)

CAPABILITY = "public.miy_whiteboard_lock_owner_actor(integer,text,text,text,text,text,integer,text,text,text,text,text,text,text)"
SERVICE = "public.miy_whiteboard_lock_source_writer(integer,text)"
PRODUCER = "public.miy_recording_lock_producer(bigint,text,integer,text)"
ROLE_GUARD = "public.miy_guard_official_source_writer_by_role()"


def _api():
    try:
        return SimpleNamespace(
            roles=import_module("miy_api.domains.official_apps.whiteboard_actor_writer_roles"),
            runtime=import_module("miy_api.domains.official_apps.whiteboard_actor_writer"),
            service=import_module("miy_api.domains.official_apps.whiteboard_source_writer_roles"),
        )
    except ModuleNotFoundError:
        pytest.fail("Actor owner API readiness missing; no behavioral RED", pytrace=False)


def _oid(conn, name):
    return conn.execute("SELECT oid::bigint FROM pg_roles WHERE rolname=%s", (name,)).fetchone()[0]


@pytest.fixture
def actor_boundary(http_world):
    api, world = _api(), http_world
    with world.core() as db:
        engine = db.get_bind()
        admin = resolve_auth_context_from_token(
            db, world.state["admin"]["token"], update_last_seen=False
        )
        db.expunge_all()
    url = engine.url
    # Connection parameters stay private; all credential values are synthetic.
    dsn = make_conninfo(
        host=url.host, port=url.port, dbname=url.database, user=url.username, password=url.password
    )
    roles = []

    def connect(role_name=None, **kwargs):
        return psycopg.connect(
            make_conninfo(
                dsn,
                user=role_name or url.username,
                password=PASSWORD if role_name else url.password,
            ),
            **kwargs,
        )

    def role(*, login=True):
        name = "actor_fixture_" + uuid4().hex[:20]
        with connect() as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(
                    sql.Identifier(name),
                    sql.SQL("LOGIN" if login else "NOLOGIN"),
                    sql.Literal(PASSWORD),
                )
            )
        roles.append(name)
        return name

    control = SimpleNamespace(engine=engine, actor=admin)
    with connect() as conn:
        migration_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (CAPABILITY,)
        ).fetchone()[0]
        service_migration_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (SERVICE,)
        ).fetchone()[0]
        producer_owner = conn.execute(
            "SELECT proowner::bigint FROM pg_proc WHERE oid=%s::regprocedure", (PRODUCER,)
        ).fetchone()[0]
    guard, service_owner, owner = role(login=False), role(login=False), role(login=False)
    source = role()
    assert move(control, BASE, "active", state="draining") == DRAIN
    with Session(engine) as db:
        install_role_guard(db, admin, guard_owner=guard, expected=DRAIN)
        db.commit()
    with connect() as conn:
        guard_oid, service_oid, owner_oid = (
            _oid(conn, name) for name in (guard, service_owner, owner)
        )
    with Session(engine) as db:
        api.service.install_whiteboard_source_writer_guard(
            db,
            admin,
            guard_owner=service_owner,
            expected=DRAIN,
            expected_migration_owner_oid=service_migration_owner,
            expected_producer_owner_oid=producer_owner,
            expected_source_guard_owner_oid=guard_oid,
        )
        db.commit()
    c = SimpleNamespace(
        api=api,
        world=world,
        engine=engine,
        actor=admin,
        control=control,
        connect=connect,
        role=role,
        roles=roles,
        dsn=dsn,
        guard=guard,
        source_guard_owner_oid=guard_oid,
        service_owner=service_owner,
        service_capability_owner_oid=service_oid,
        capability_owner=owner,
        capability_owner_oid=owner_oid,
        migration_owner_oid=migration_owner,
        producer_owner_oid=producer_owner,
        source=source,
        expected=DRAIN,
        expected_state="draining",
        board_id=world.ids["board"],
    )
    try:
        yield c
    finally:
        # Only this disposable database and locally owned synthetic roles.
        with connect(autocommit=True) as conn:
            for name in reversed(roles):
                conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(name)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def _install(c, db):
    return c.api.roles.install_whiteboard_actor_owner_guard(
        db,
        c.actor,
        guard_owner=c.capability_owner,
        expected=DRAIN,
        expected_migration_owner_oid=c.migration_owner_oid,
        expected_service_capability_owner_oid=c.service_capability_owner_oid,
        expected_producer_owner_oid=c.producer_owner_oid,
        expected_source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _prepare(c, db, name=None, *, identity=None):
    return c.api.roles.prepare_whiteboard_actor_owner_principal(
        db,
        c.actor,
        role_name=c.source if name is None else name,
        identity=identity or ACTIVE,
        expected=c.expected,
        expected_state=c.expected_state,
        capability_owner_oid=c.capability_owner_oid,
        service_capability_owner_oid=c.service_capability_owner_oid,
        producer_owner_oid=c.producer_owner_oid,
        source_guard_owner_oid=c.source_guard_owner_oid,
    )


def _capture(c, **kwargs):
    return c.api.runtime.capture_whiteboard_write_execution(
        c.world.factory,
        token=kwargs.get("token", c.world.token),
        original_user_id=kwargs.get("user", c.world.state["member_id"]),
        original_source_session_id=kwargs.get("session", c.world.state["source_id"]),
    )


def _lock(c, db, *, execution=None, writer=None, board=None):
    return c.api.runtime.lock_whiteboard_owner_actor_write(
        db,
        writer=c.writer if writer is None else writer,
        execution=c.execution if execution is None else execution,
        whiteboard_id=c.board_id if board is None else board,
    )


@pytest.fixture
def actor_prepared(actor_boundary):
    c = actor_boundary
    with Session(c.engine) as db:
        assert _install(c, db) is None
        result = _prepare(c, db)
        c.writer = result.writer
        assert result.profile_prepared is True
        db.commit()
    assert move(c.control, DRAIN, "draining", state="active", artifact=ACTIVE.artifact) == ACTIVE
    c.expected, c.expected_state = ACTIVE, "active"
    # A test-only original privileged Core identity lets the real hardened
    # Source trigger run for metadata changes. Actor privileges remain DML0.
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO official_writer_principals "
            "(role_oid,role_name,scope,owner,generation,artifact,approved_by_user_id,approved_by_session_id,created_at) "
            "SELECT oid::bigint,rolname,%s,%s,%s,%s,%s,%s,timezone('UTC',clock_timestamp()) FROM pg_roles WHERE rolname=session_user",
            (
                ACTIVE.scope,
                ACTIVE.owner,
                ACTIVE.generation,
                ACTIVE.artifact,
                c.actor.user.id,
                c.actor.session.id,
            ),
        )
    c.source_engine = create_engine(
        c.engine.url.set(username=c.source, password=PASSWORD), pool_size=1, max_overflow=0
    )
    c.execution = _capture(c)
    try:
        yield c
    finally:
        c.source_engine.dispose()


def _params(c):
    return {
        "user": c.execution.actor_user_id,
        "session": c.execution.source_session_id,
        "digest": c.execution.delegated_token_digest,
        "installation": c.execution.installation_id,
        "binding": c.execution.binding_id,
        "release": c.execution.release_id,
        "verification": c.execution.verification_id,
        "board": c.board_id,
        "group": c.world.state["group_id"],
        "other": c.actor.user.id,
        "role": c.writer.role_oid,
    }


def _collab_snapshot(c):
    with c.connect() as conn:
        return conn.execute(
            "SELECT id,whiteboard_id,room_key,yjs_state,updated_at,writer_scope "
            "FROM whiteboard_collab_documents ORDER BY id"
        ).fetchall()


@contextmanager
def _commands(engine):
    commands = []

    def observe(_conn, _cursor, statement, *_):
        commands.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield commands
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def _refused(c, db, **kwargs):
    with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
        _lock(c, db, **kwargs)
    assert str(caught.value) == "whiteboard_actor_writer_refused"
    db.rollback()


def _wait_for_blocker(observer, waiter, holder):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if observer.execute("SELECT %s=ANY(pg_blocking_pids(%s))", (holder, waiter)).fetchone()[0]:
            return
        time.sleep(0.01)
    pytest.fail("Actual captured row holder did not block native admission")


def _replace_body(conn, signature):
    definition = conn.execute(
        "SELECT pg_get_functiondef(%s::regprocedure)", (signature,)
    ).fetchone()[0]
    marker = re.search(r"\bAS (\$[A-Za-z0-9_]*\$)", definition)
    assert marker is not None
    end = definition.index(marker.group(1), marker.end())
    conn.execute(definition[: marker.end()] + "\nBEGIN RETURN; END;\n" + definition[end:])


def test_pure_routed_session_is_refused_before_sql_without_adopting_caller_work(monkeypatch):
    api = _api()
    monkeypatch.setattr(
        api.runtime,
        "get_settings",
        lambda: SimpleNamespace(independent_app_platform_origins=["https://portal.example.test"]),
    )
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    calls = []

    class Routed(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            calls.append("route")
            return second if clause is not None else first

    writer = api.roles.WhiteboardActorOwnerProfile(1, "synthetic_actor", ACTIVE, 2, 3, 4, 5)
    execution = api.runtime.CapturedWhiteboardWriteExecution(
        "a" * 64,
        "user",
        "session",
        "install",
        1,
        "binding",
        "release",
        "proof",
        "sha256:" + "a" * 64,
        "https://standalone.example.test",
        "dev",
        "synthetic_db",
        123,
        None,
        None,
    )
    with Routed(bind=first) as db:
        marker = User(
            id="unrelated",
            login_id="unrelated",
            email="unused@example.test",
            full_name="Synthetic",
            password_hash="synthetic",
        )
        db.add(marker)
        with pytest.raises(api.runtime.WhiteboardActorWriterRefused):
            api.runtime.lock_whiteboard_owner_actor_write(
                db, writer=writer, execution=execution, whiteboard_id="board"
            )
        assert marker in db.new and db.in_transaction()
        assert calls == []
        db.expunge(marker)
        with pytest.raises(api.runtime.WhiteboardActorWriterRefused) as caught:
            api.runtime.lock_whiteboard_owner_actor_write(
                db, writer=writer, execution=execution, whiteboard_id="board"
            )
        assert calls == []
        assert caught.value.reason == "standard_caller_binding_required"
    first.dispose()
    second.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_oid", True),
        ("installation_generation", True),
        ("delegated_token_digest", "secret\n"),
        ("server_port", 0),
    ],
)
def test_pure_invalid_original_execution_never_becomes_a_serializable_credential(field, value):
    api = _api()
    original = api.runtime.CapturedWhiteboardWriteExecution(
        "a" * 64,
        "user",
        "session",
        "install",
        1,
        "binding",
        "release",
        "proof",
        "sha256:" + "a" * 64,
        "https://standalone.example.test",
        "dev",
        "synthetic_db",
        123,
        None,
        None,
    )
    assert "a" * 64 not in repr(original)
    with pytest.raises(FrozenInstanceError):
        original.actor_user_id = "other"
    with pytest.raises(api.runtime.WhiteboardActorWriterRefused) as caught:
        replace(original, **{field: value})
    assert str(caught.value) == "whiteboard_actor_writer_refused"


@pytest.mark.parametrize("binding", ["multiple_engines", "connection_bind"])
def test_pure_noncanonical_caller_binding_is_refused_before_any_sql(binding, monkeypatch):
    api = _api()
    monkeypatch.setattr(
        api.runtime,
        "get_settings",
        lambda: SimpleNamespace(independent_app_platform_origins=["https://portal.example.test"]),
    )
    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    calls = []
    writer = api.roles.WhiteboardActorOwnerProfile(1, "synthetic_actor", ACTIVE, 2, 3, 4, 5)
    execution = api.runtime.CapturedWhiteboardWriteExecution(
        "a" * 64,
        "user",
        "session",
        "install",
        1,
        "binding",
        "release",
        "proof",
        "sha256:" + "a" * 64,
        "https://standalone.example.test",
        "dev",
        "synthetic_db",
        123,
        None,
        None,
    )

    def observe(*args):
        calls.append(1)

    with first.connect() as connection:
        for engine in (first, second):
            event.listen(engine, "before_cursor_execute", observe)
        try:
            db = (
                Session(bind=first, binds={User: second})
                if binding == "multiple_engines"
                else Session(bind=connection)
            )
            with db:
                with pytest.raises(api.runtime.WhiteboardActorWriterRefused) as caught:
                    api.runtime.lock_whiteboard_owner_actor_write(
                        db, writer=writer, execution=execution, whiteboard_id="board"
                    )
                assert not db.in_transaction()
                assert caught.value.reason == (
                    "single_caller_engine_required"
                    if binding == "multiple_engines"
                    else "engine_caller_binding_required"
                )
            assert calls == []
        finally:
            for engine in (first, second):
                event.remove(engine, "before_cursor_execute", observe)
    first.dispose()
    second.dispose()


def test_genuine_actor_owner_installation_and_dml0_profile(actor_prepared):
    c = actor_prepared
    assert c.writer.role_name == c.source and c.writer.identity == ACTIVE
    assert c.writer.role_oid not in {
        c.writer.capability_owner_oid,
        c.writer.service_capability_owner_oid,
        c.writer.source_guard_owner_oid,
    }
    with c.connect() as conn:
        assert conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE oid=%s", (c.capability_owner_oid,)
        ).fetchone() == (False,)
        assert conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE'),has_function_privilege(%s,%s,'EXECUTE')",
            (c.source, CAPABILITY, c.source, SERVICE, c.source, PRODUCER),
        ).fetchone() == (True, False, False)
        granted = conn.execute(
            "SELECT c.relname,a.attname,has_column_privilege(%s,c.oid,a.attnum,'SELECT'),"
            "has_column_privilege(%s,c.oid,a.attnum,'UPDATE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p')",
            (c.capability_owner, c.capability_owner),
        ).fetchall()
        assert {(t, col) for t, col, r, _ in granted if r} == {
            (t, col) for t, cols in c.api.roles.OWNER_READ_COLUMNS.items() for col in cols
        }
        assert {(t, col) for t, col, _, u in granted if u} == {
            (t, col) for t, cols in c.api.roles.OWNER_LOCK_COLUMNS.items() for col in cols
        }
        assert sum(len(cols) for cols in c.api.roles.OWNER_READ_COLUMNS.values()) == 74
    original = _collab_snapshot(c)
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        assert _lock(c, db) is None
        assert db.in_transaction()
        db.commit()
    assert set(commands) <= {"SELECT", "SET", "SHOW"}
    assert _collab_snapshot(c) == original
    assert c.world.engine.pool.checkedout() == 0 and c.source_engine.pool.checkedout() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT id FROM users",
        "SELECT id FROM whiteboards",
        "UPDATE whiteboards SET owner_id=owner_id WHERE false",
        "UPDATE whiteboard_collab_documents SET yjs_state=yjs_state WHERE false",
        "SELECT public.miy_whiteboard_lock_source_writer(3,'sha256:'||repeat('a',64))",
        "SELECT role_oid FROM official_writer_principals",
    ],
)
def test_genuine_actor_login_has_no_direct_business_core_or_service_access(
    actor_prepared, statement
):
    c = actor_prepared
    with Session(c.source_engine) as db:
        with pytest.raises(DBAPIError) as caught:
            db.execute(text(statement))
        assert getattr(caught.value.orig, "sqlstate", None) == "42501"
        db.rollback()


def test_genuine_exact_prepare_replay_is_observation_only_and_partial_profile_is_not_repaired(
    actor_prepared,
):
    c = actor_prepared
    with c.connect() as conn:
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        replay = _prepare(c, db)
        assert replay.writer == c.writer
        db.commit()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before
        conn.execute(
            sql.SQL("REVOKE EXECUTE ON FUNCTION {} FROM {}").format(
                sql.SQL(CAPABILITY), sql.Identifier(c.source)
            )
        )
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with Session(c.source_engine) as db:
        _refused(c, db)


def test_genuine_owner_install_replay_is_observation_only_under_original_drain(actor_boundary):
    c = actor_boundary
    with Session(c.engine) as db:
        _install(c, db)
        db.commit()
    with c.connect() as conn:
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(c.engine) as db, _commands(c.engine) as commands:
        assert _install(c, db) is None
        db.commit()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before


@pytest.mark.parametrize(
    "tamper",
    [
        "login_read",
        "login_update",
        "login_maintain",
        "service_exec",
        "generic_exec",
        "grant_option",
        "membership",
        "inherit",
        "bypassrls",
        "parameter",
        "namespace_column",
        "namespace_sequence",
        "namespace_create",
        "public_read",
        "public_definer",
    ],
)
def test_genuine_effective_login_authority_is_refused_without_repair(actor_prepared, tamper):
    c = actor_prepared
    with c.connect() as conn:
        role = sql.Identifier(c.source)
        statements = {
            "login_read": sql.SQL("GRANT SELECT (id) ON users TO {}"),
            "login_update": sql.SQL("GRANT UPDATE (id) ON whiteboards TO {}"),
            "login_maintain": sql.SQL("GRANT MAINTAIN ON users TO {}"),
            "service_exec": sql.SQL("GRANT EXECUTE ON FUNCTION " + SERVICE + " TO {}"),
            "generic_exec": sql.SQL("GRANT EXECUTE ON FUNCTION " + PRODUCER + " TO {}"),
            "grant_option": sql.SQL(
                "GRANT EXECUTE ON FUNCTION " + CAPABILITY + " TO {} WITH GRANT OPTION"
            ),
            "inherit": sql.SQL("ALTER ROLE {} INHERIT"),
            "bypassrls": sql.SQL("ALTER ROLE {} BYPASSRLS"),
            "parameter": sql.SQL("GRANT SET ON PARAMETER session_replication_role TO {}"),
            "namespace_column": sql.SQL(
                "GRANT SELECT (marker) ON pgx_actor.private_metadata TO {}"
            ),
            "namespace_sequence": sql.SQL(
                "GRANT USAGE ON SEQUENCE pgx_actor.private_sequence TO {}"
            ),
            "namespace_create": sql.SQL("GRANT CREATE ON SCHEMA pgx_actor TO {}"),
        }
        if tamper.startswith("namespace"):
            conn.execute("CREATE SCHEMA pgx_actor")
            conn.execute("CREATE TABLE pgx_actor.private_metadata(marker integer)")
            conn.execute("CREATE SEQUENCE pgx_actor.private_sequence")
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA pgx_actor TO {}").format(role))
        if tamper == "membership":
            donor = c.role(login=False)
            conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(donor), role))
        elif tamper == "public_read":
            conn.execute("GRANT SELECT (id) ON public.users TO PUBLIC")
        elif tamper == "public_definer":
            conn.execute("CREATE SCHEMA pgx_extra_actor")
            conn.execute(
                "CREATE FUNCTION pgx_extra_actor.private_cap() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
            )
        else:
            conn.execute(statements[tamper].format(role))
    original = _collab_snapshot(c)
    with Session(c.source_engine) as db:
        _refused(c, db)
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    assert _collab_snapshot(c) == original


@pytest.mark.parametrize(
    "tamper",
    [
        "body",
        "owner",
        "overload",
        "public_execute",
        "owner_extra_read",
        "owner_extra_update",
        "owner_maintain",
        "owner_grant_option",
        "owner_generic_exec",
        "owner_namespace_ownership",
    ],
)
def test_genuine_capability_and_nologin_owner_contract_tampering_is_refused(actor_prepared, tamper):
    c = actor_prepared
    with c.connect() as conn:
        owner = sql.Identifier(c.capability_owner)
        if tamper == "body":
            _replace_body(conn, CAPABILITY)
        elif tamper == "owner":
            changed = c.role(login=False)
            conn.execute(
                sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(changed))
            )
            conn.execute(
                sql.SQL("ALTER FUNCTION {} OWNER TO {}").format(
                    sql.SQL(CAPABILITY), sql.Identifier(changed)
                )
            )
            conn.execute(
                sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(changed))
            )
        elif tamper == "overload":
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_owner_actor(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_owner_actor(text) FROM PUBLIC"
            )
        elif tamper == "public_execute":
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO PUBLIC").format(sql.SQL(CAPABILITY))
            )
        elif tamper == "owner_namespace_ownership":
            conn.execute(sql.SQL("CREATE SCHEMA pgx_actor AUTHORIZATION {}").format(owner))
        else:
            statements = {
                "owner_extra_read": "GRANT SELECT (password_hash) ON users TO {}",
                "owner_extra_update": "GRANT UPDATE (status) ON users TO {}",
                "owner_maintain": "GRANT MAINTAIN ON users TO {}",
                "owner_grant_option": "GRANT SELECT (id) ON users TO {} WITH GRANT OPTION",
                "owner_generic_exec": "GRANT EXECUTE ON FUNCTION " + PRODUCER + " TO {}",
            }
            conn.execute(sql.SQL(statements[tamper]).format(owner))
    with Session(c.source_engine) as db:
        _refused(c, db)
    with Session(c.engine) as db:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()


@pytest.mark.parametrize("pregrant", ["execute", "broad_read", "nologin"])
def test_genuine_fresh_preparation_refuses_preexisting_authority_or_wrong_role_kind(
    actor_boundary, pregrant
):
    c = actor_boundary
    name = c.role(login=pregrant != "nologin")
    with Session(c.engine) as db:
        _install(c, db)
        db.commit()
    with c.connect() as conn:
        if pregrant == "execute":
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                    sql.SQL(CAPABILITY), sql.Identifier(name)
                )
            )
        elif pregrant == "broad_read":
            conn.execute(sql.SQL("GRANT SELECT ON users TO {}").format(sql.Identifier(name)))
    with Session(c.engine) as db, _commands(c.engine) as commands:
        with pytest.raises(WriterControlError):
            _prepare(c, db, name)
        db.rollback()
    assert not set(commands) & {"GRANT", "REVOKE", "ALTER", "INSERT", "UPDATE", "DELETE"}
    with c.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (name,)
        ).fetchone() == (0,)


def test_genuine_revoked_original_principal_cannot_be_reprepared_or_reused(actor_prepared):
    c = actor_prepared
    with Session(c.engine) as db:
        revoke_principal(
            db, c.actor, role_oid=c.writer.role_oid, expected=ACTIVE, expected_state="active"
        )
        db.commit()
    with Session(c.engine) as db:
        with pytest.raises(WriterControlError):
            _prepare(c, db)
        db.rollback()
    with Session(c.source_engine) as db:
        _refused(c, db)


@pytest.mark.parametrize(
    "change", ["generation", "artifact", "role_oid", "owner_oid", "session_user"]
)
def test_genuine_original_service_identity_is_required_despite_spoofed_guc(actor_prepared, change):
    c = actor_prepared
    writer = c.writer
    if change == "generation":
        writer = replace(
            writer, identity=WriterIdentity(ACTIVE.scope, ACTIVE.owner, 2, ACTIVE.artifact)
        )
    elif change == "artifact":
        writer = replace(
            writer, identity=WriterIdentity(ACTIVE.scope, ACTIVE.owner, 3, "sha256:" + "b" * 64)
        )
    elif change == "role_oid":
        writer = replace(writer, role_oid=c.writer.role_oid + 100000)
    elif change == "owner_oid":
        writer = replace(writer, capability_owner_oid=c.writer.service_capability_owner_oid)
    if change == "session_user":
        other = c.role()
        with c.connect() as conn:
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(other))
            )
            conn.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                    sql.SQL(CAPABILITY), sql.Identifier(other)
                )
            )
        engine = create_engine(c.engine.url.set(username=other, password=PASSWORD))
    else:
        engine = c.source_engine
    try:
        with Session(engine) as db:
            db.execute(
                text("SELECT set_config('miy.official_writer',:spoof,true)"),
                {
                    "spoof": json.dumps(
                        {
                            "scope": ACTIVE.scope,
                            "owner": ACTIVE.owner,
                            "generation": 3,
                            "artifact": ACTIVE.artifact,
                        }
                    )
                },
            )
            _refused(c, db, writer=writer)
    finally:
        if engine is not c.source_engine:
            engine.dispose()


METADATA_CHANGES = {
    "user_inactive": "UPDATE users SET status='inactive' WHERE id=:user",
    "user_blocked": "UPDATE users SET login_blocked=true WHERE id=:user",
    "user_reset": "UPDATE users SET must_change_password=true WHERE id=:user",
    "source_revoked": "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE id=:session",
    "source_expired": "UPDATE auth_sessions SET expires_at=timezone('UTC',clock_timestamp())-interval '1 second' WHERE id=:session",
    "source_impersonation": "UPDATE auth_sessions SET impersonator_user_id=:other WHERE id=:session",
    "delegated_revoked": "UPDATE independent_app_sessions SET revoked_at=clock_timestamp() WHERE token_hash=:digest",
    "delegated_permissions": "UPDATE independent_app_sessions SET permissions='[]'::json WHERE token_hash=:digest",
    "installation_disabled": "UPDATE independent_app_installations SET enabled=false WHERE id=:installation",
    "installation_generation": "UPDATE independent_app_installations SET generation=generation+1 WHERE id=:installation",
    "installation_release_null": "UPDATE independent_app_installations SET release_id=NULL WHERE id=:installation",
    "installation_permissions": "UPDATE independent_app_installations SET granted_permissions='[]'::json WHERE id=:installation",
    "installation_origin": "UPDATE independent_app_installations SET origin='https://changed.example.test' WHERE id=:installation",
    "verification_revoked": "UPDATE independent_app_build_verifications SET revoked_at=clock_timestamp() WHERE id=:verification",
    "release_verification_null": "UPDATE independent_app_releases SET verification_id=NULL WHERE id=:release",
    "binding_revoked": "UPDATE official_app_bindings SET revoked_at=clock_timestamp() WHERE id=:binding",
    "company_app_disabled": "UPDATE company_app_controls SET enabled=false WHERE app_id=(SELECT app_id FROM independent_app_installations WHERE id=:installation)",
    "whiteboard_app_disabled": "UPDATE company_app_controls SET enabled=false WHERE app_id='whiteboard'",
    "policy_missing": "DELETE FROM app_access_policies WHERE app_id='whiteboard'",
    "selected_witness_revoked": "DELETE FROM group_members WHERE group_id=:group AND user_id=:user",
    "board_owner": "UPDATE whiteboards SET owner_id=:other WHERE id=:board",
    "board_trashed": "UPDATE whiteboards SET trashed_at=clock_timestamp() WHERE id=:board",
}


@pytest.mark.parametrize("change", list(METADATA_CHANGES))
def test_genuine_current_metadata_denies_old_captured_execution_without_source_dml(
    actor_prepared, change
):
    c = actor_prepared
    original = _collab_snapshot(c)
    with Session(c.engine) as core:
        core.execute(text(METADATA_CHANGES[change]), _params(c))
        core.commit()
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        _refused(c, db)
    assert set(commands) <= {"SELECT", "SET", "SHOW"}
    assert _collab_snapshot(c) == original


@pytest.mark.parametrize("checks", ['{"test":false}', '{"test":0.0}', '{"test":0e0}', "{}"])
def test_genuine_native_json_proof_preserves_exact_integer_zero_semantics(actor_prepared, checks):
    c = actor_prepared
    with Session(c.engine) as db:
        db.execute(
            text(
                "UPDATE independent_app_build_verifications SET checks=CAST(:checks AS json) WHERE id=:proof"
            ),
            {"checks": checks, "proof": c.execution.verification_id},
        )
        db.commit()
    with Session(c.source_engine) as db:
        _refused(c, db)


@pytest.mark.parametrize(
    "field",
    [
        "actor_user_id",
        "source_session_id",
        "installation_id",
        "binding_id",
        "release_id",
        "verification_id",
        "execution_artifact",
        "database_name",
        "database_oid",
    ],
)
def test_genuine_capture_substitution_cannot_adopt_current_or_different_database_identity(
    actor_prepared, field
):
    c = actor_prepared
    value = (
        c.execution.database_oid + 1
        if field == "database_oid"
        else ("sha256:" + "b" * 64 if field == "execution_artifact" else "different-original")
    )
    forged = replace(c.execution, **{field: value})
    with Session(c.source_engine) as db:
        _refused(c, db, execution=forged)


def test_genuine_detached_auth_context_is_not_execution_and_capture_rechecks_credentials(
    actor_prepared,
):
    c = actor_prepared
    with c.world.core() as core:
        detached = resolve_auth_context_from_token(
            core, c.world.state["login_token"], update_last_seen=False
        )
        core.expunge_all()
    with Session(c.source_engine) as db, _commands(c.source_engine) as commands:
        _refused(c, db, execution=detached)
    assert commands == []
    with Session(c.engine) as core:
        core.execute(text(METADATA_CHANGES["source_revoked"]), _params(c))
        core.commit()
    with pytest.raises((HTTPException, c.api.runtime.WhiteboardActorWriterRefused)):
        _capture(c)
    with Session(c.source_engine) as db:
        _refused(c, db)
    assert c.world.engine.pool.checkedout() == 0


@pytest.mark.parametrize(
    "witness", ["company_all", "direct_user", "platform_admin", "local_group", "hr_group"]
)
def test_genuine_selected_company_witness_does_not_replace_whiteboard_ownership(
    actor_prepared, witness
):
    c = actor_prepared
    p = _params(c)
    with Session(c.engine) as core:
        if witness != "company_all":
            core.execute(
                text("UPDATE app_access_policies SET audience='selected' WHERE app_id='whiteboard'")
            )
        if witness == "direct_user":
            core.execute(
                text("INSERT INTO app_user_grants(app_id,user_id) VALUES ('whiteboard',:user)"), p
            )
        elif witness == "platform_admin":
            core.execute(
                text(
                    "INSERT INTO user_system_roles(id,user_id,role,created_at) VALUES (:id,:user,'platform_admin',timezone('UTC',clock_timestamp()))"
                ),
                dict(p, id=str(uuid4())),
            )
        elif witness in {"local_group", "hr_group"}:
            core.execute(
                text("INSERT INTO app_group_grants(app_id,group_id) VALUES ('whiteboard',:group)"),
                p,
            )
            if witness == "hr_group":
                core.execute(
                    text(
                        "UPDATE groups SET source='hr',slug='synthetic-hr-unit',unit_type='department' WHERE id=:group"
                    ),
                    p,
                )
                core.execute(
                    text("UPDATE users SET primary_organization_unit_id=:group WHERE id=:user"), p
                )
                core.execute(
                    text("DELETE FROM group_members WHERE group_id=:group AND user_id=:user"), p
                )
        core.commit()
    with Session(c.source_engine) as db:
        assert _lock(c, db) is None
        db.rollback()
    with Session(c.engine) as core:
        core.execute(text("UPDATE whiteboards SET owner_id=:other WHERE id=:board"), p)
        core.execute(
            text(
                "INSERT INTO whiteboard_user_shares(id,whiteboard_id,user_id,created_by_id,access_level,created_at,writer_scope) "
                "VALUES (:id,:board,:user,:other,'read',timezone('UTC',clock_timestamp()),'official.suite')"
            ),
            dict(p, id=str(uuid4())),
        )
        core.commit()
    with Session(c.source_engine) as db:
        _refused(c, db)


def test_genuine_known_different_caller_database_is_refused_before_capability_lookup(
    actor_prepared,
):
    c = actor_prepared
    name = "miy_test_actor_other_" + uuid4().hex[:12]
    with c.connect(autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    other = create_engine(c.engine.url.set(database=name, username=c.source, password=PASSWORD))
    try:
        with Session(other) as db, _commands(other) as commands:
            _refused(c, db)
        assert set(commands) <= {"SELECT", "SET", "SHOW"}
        with c.connect(autocommit=True) as conn:
            assert (
                conn.execute(
                    "SELECT oid::bigint FROM pg_database WHERE datname=%s", (name,)
                ).fetchone()[0]
                != c.execution.database_oid
            )
        with Session(c.source_engine) as db:
            assert _lock(c, db) is None
            db.rollback()
    finally:
        other.dispose()
        with c.connect(autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


LOCKED_MUTATIONS = {
    "runtime_ownership": (
        "SELECT 1 FROM official_runtime_ownership WHERE scope='official.suite' FOR UPDATE",
        "UPDATE official_runtime_ownership SET state='draining' WHERE scope='official.suite'",
    ),
    "writer_principal": (
        "SELECT 1 FROM official_writer_principals WHERE role_oid=%(role)s FOR UPDATE",
        "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_oid=:role",
    ),
    "source_session": (
        "SELECT 1 FROM auth_sessions WHERE id=%(session)s FOR UPDATE",
        METADATA_CHANGES["source_revoked"],
    ),
    "user": ("SELECT 1 FROM users WHERE id=%(user)s FOR UPDATE", METADATA_CHANGES["user_blocked"]),
    "delegated_session": (
        "SELECT 1 FROM independent_app_sessions WHERE token_hash=%(digest)s FOR UPDATE",
        METADATA_CHANGES["delegated_revoked"],
    ),
    "installation": (
        "SELECT 1 FROM independent_app_installations WHERE id=%(installation)s FOR UPDATE",
        METADATA_CHANGES["installation_disabled"],
    ),
    "binding": (
        "SELECT 1 FROM official_app_bindings WHERE id=%(binding)s FOR UPDATE",
        METADATA_CHANGES["binding_revoked"],
    ),
    "group_membership": (
        "SELECT 1 FROM group_members WHERE group_id=%(group)s AND user_id=%(user)s FOR UPDATE",
        METADATA_CHANGES["selected_witness_revoked"],
    ),
    "board_owner": (
        "SELECT 1 FROM whiteboards WHERE id=%(board)s FOR UPDATE",
        METADATA_CHANGES["board_owner"],
    ),
    "board_trash": (
        "SELECT 1 FROM whiteboards WHERE id=%(board)s FOR UPDATE",
        METADATA_CHANGES["board_trashed"],
    ),
    "company_control": (
        "SELECT 1 FROM company_app_controls WHERE app_id='whiteboard' FOR UPDATE",
        METADATA_CHANGES["whiteboard_app_disabled"],
    ),
    "installation_company_control": (
        "SELECT 1 FROM company_app_controls WHERE app_id=(SELECT app_id FROM independent_app_installations WHERE id=%(installation)s) FOR UPDATE",
        METADATA_CHANGES["company_app_disabled"],
    ),
    "verification": (
        "SELECT 1 FROM independent_app_build_verifications WHERE id=%(verification)s FOR UPDATE",
        "UPDATE independent_app_build_verifications SET checks=json_build_object('test',false) WHERE id=:verification",
    ),
    "release": (
        "SELECT 1 FROM independent_app_releases WHERE id=%(release)s FOR UPDATE",
        "UPDATE independent_app_releases SET artifact='sha256:'||repeat('b',64) WHERE id=:release",
    ),
    "policy": (
        "SELECT 1 FROM app_access_policies WHERE app_id='whiteboard' FOR UPDATE",
        "UPDATE app_access_policies SET audience='selected' WHERE app_id='whiteboard'",
    ),
    "group_active": (
        "SELECT 1 FROM groups WHERE id=%(group)s FOR UPDATE",
        "UPDATE groups SET active=false WHERE id=:group",
    ),
}


def _native_statement(statement):
    return re.sub(r"(?<!:):([a-z_]+)", r"%(\1)s", statement)


@pytest.mark.parametrize("target", ["source_session", "binding", "board_owner", "group_membership"])
def test_genuine_waited_current_row_is_rechecked_after_native_revocation(actor_prepared, target):
    c = actor_prepared
    p = _params(c)
    original = _collab_snapshot(c)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        revoker.execute(LOCKED_MUTATIONS[target][0], p)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder)
                assert not future.done()
                revoker.execute(_native_statement(LOCKED_MUTATIONS[target][1]), p)
                revoker.commit()
                with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()
    assert _collab_snapshot(c) == original


@pytest.mark.parametrize("target", list(LOCKED_MUTATIONS))
@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_genuine_positive_actor_witness_locks_survive_until_actual_caller_end(
    actor_prepared, target, finish
):
    c = actor_prepared
    p = _params(c)
    original = _collab_snapshot(c)
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        holder = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _lock(c, db) is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(revoker.execute, _native_statement(LOCKED_MUTATIONS[target][1]), p)
            try:
                _wait_for_blocker(observer, holder, source_pid)
                assert not future.done()
                getattr(db, finish)()
                future.result(timeout=5)
                revoker.commit()
            finally:
                db.rollback()
                revoker.rollback()
        _refused(c, db)
    assert _collab_snapshot(c) == original


@pytest.mark.parametrize("witness", ["direct_user", "platform_admin", "local_group"])
def test_genuine_chosen_selected_app_grant_is_held_through_caller_commit(actor_prepared, witness):
    c = actor_prepared
    p = _params(c)
    with Session(c.engine) as core:
        core.execute(
            text("UPDATE app_access_policies SET audience='selected' WHERE app_id='whiteboard'")
        )
        if witness == "direct_user":
            core.execute(
                text("INSERT INTO app_user_grants(app_id,user_id) VALUES ('whiteboard',:user)"), p
            )
            mutation = "DELETE FROM app_user_grants WHERE app_id='whiteboard' AND user_id=%(user)s"
        elif witness == "platform_admin":
            core.execute(
                text(
                    "INSERT INTO user_system_roles(id,user_id,role,created_at) VALUES (:id,:user,'platform_admin',timezone('UTC',clock_timestamp()))"
                ),
                dict(p, id=str(uuid4())),
            )
            mutation = (
                "DELETE FROM user_system_roles WHERE user_id=%(user)s AND role='platform_admin'"
            )
        else:
            core.execute(
                text("INSERT INTO app_group_grants(app_id,group_id) VALUES ('whiteboard',:group)"),
                p,
            )
            mutation = (
                "DELETE FROM app_group_grants WHERE app_id='whiteboard' AND group_id=%(group)s"
            )
        core.commit()
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _lock(c, db) is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(revoker.execute, mutation, p)
            try:
                _wait_for_blocker(observer, revoker_pid, source_pid)
                assert not future.done()
                db.commit()
                future.result(timeout=5)
                revoker.commit()
            finally:
                db.rollback()
                revoker.rollback()
        _refused(c, db)


@pytest.mark.parametrize("change", ["draining", "revoked", "role_rename"])
def test_genuine_service_control_wait_cannot_adopt_changed_original_identity(
    actor_prepared, change
):
    c = actor_prepared
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as revoker,
        Session(c.source_engine) as db,
    ):
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.rollback()
        revoker.execute(
            "SELECT 1 FROM official_runtime_ownership WHERE scope='official.suite' FOR UPDATE"
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder)
                if change == "draining":
                    revoker.execute(
                        "UPDATE official_runtime_ownership SET state='draining' WHERE scope='official.suite'"
                    )
                elif change == "revoked":
                    revoker.execute(
                        "UPDATE official_writer_principals SET revoked_at=clock_timestamp() WHERE role_oid=%s",
                        (c.writer.role_oid,),
                    )
                else:
                    renamed = "renamed_actor_" + uuid4().hex[:12]
                    revoker.execute(
                        sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                            sql.Identifier(c.source), sql.Identifier(renamed)
                        )
                    )
                revoker.commit()
                if change == "role_rename":
                    c.roles[c.roles.index(c.source)] = renamed
                with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_writer_refused"
            finally:
                revoker.rollback()
                db.rollback()


def test_genuine_expiry_after_actual_board_wait_is_checked_at_decision_time(actor_prepared):
    c = actor_prepared
    with c.connect() as core:
        core.execute(
            "UPDATE independent_app_sessions SET expires_at=timezone('UTC',clock_timestamp())+interval '1 second' WHERE token_hash=%s",
            (c.execution.delegated_token_digest,),
        )
    with (
        c.connect(autocommit=True) as observer,
        c.connect() as holder,
        Session(c.source_engine) as db,
    ):
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        db.rollback()
        holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        holder.rollback()
        holder.execute("SELECT 1 FROM whiteboards WHERE id=%s FOR UPDATE", (c.board_id,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_lock, c, db)
            try:
                _wait_for_blocker(observer, source_pid, holder_pid)
                deadline = time.monotonic() + 3
                while observer.execute(
                    "SELECT expires_at>timezone('UTC',clock_timestamp()) FROM independent_app_sessions WHERE token_hash=%s",
                    (c.execution.delegated_token_digest,),
                ).fetchone()[0]:
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
                assert not future.done()
                holder.rollback()
                with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                    future.result(timeout=5)
                assert str(caught.value) == "whiteboard_actor_writer_refused"
            finally:
                holder.rollback()
                db.rollback()


def test_genuine_synthetic_reverse_delete_order_deadlock_is_bounded_private_and_never_reuses_decision(
    actor_prepared,
):
    c = actor_prepared
    states = []

    def error(context):
        state = getattr(context.original_exception, "sqlstate", None)
        if state is not None:
            states.append(state)

    event.listen(c.source_engine, "handle_error", error)
    original = _collab_snapshot(c)
    try:
        with (
            c.connect(autocommit=True) as observer,
            c.connect() as deleter,
            Session(c.source_engine) as db,
        ):
            source_pid = db.scalar(text("SELECT pg_backend_pid()"))
            db.rollback()
            deleter_pid = deleter.execute("SELECT pg_backend_pid()").fetchone()[0]
            deleter.rollback()
            deleter.execute("SET LOCAL deadlock_timeout='5s'")
            deleter.execute(
                "SELECT 1 FROM auth_sessions WHERE id=%s FOR UPDATE",
                (c.execution.source_session_id,),
            )

            def admit():
                try:
                    with _persistence_sql_deadline(db.connection(), 4):
                        _lock(c, db)
                finally:
                    db.rollback()

            with ThreadPoolExecutor(max_workers=2) as pool:
                decision = pool.submit(admit)
                mutation = None
                try:
                    _wait_for_blocker(observer, source_pid, deleter_pid)
                    mutation = pool.submit(
                        deleter.execute,
                        "UPDATE users SET login_blocked=true WHERE id=%s",
                        (c.execution.actor_user_id,),
                    )
                    _wait_for_blocker(observer, deleter_pid, source_pid)
                    with pytest.raises(c.api.runtime.WhiteboardActorWriterRefused) as caught:
                        decision.result(timeout=5)
                    assert str(caught.value) == "whiteboard_actor_writer_refused"
                    assert "40P01" in states
                    mutation.result(timeout=5)
                    deleter.rollback()
                finally:
                    # The real caller rollback releases all prior actor locks.
                    db.rollback()
                    deleter.rollback()
            assert _lock(c, db) is None
            db.rollback()
        assert _collab_snapshot(c) == original
    finally:
        event.remove(c.source_engine, "handle_error", error)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_genuine_caller_decreasing_budget_and_connection_settings_reset(actor_prepared, finish):
    c = actor_prepared
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
            assert _lock(c, db) is None
            first = db.scalar(text("SELECT current_setting('statement_timeout')::interval"))
            db.execute(text("SELECT pg_sleep(.04)"))
            second = db.scalar(text("SELECT current_setting('statement_timeout')::interval"))
            assert timedelta(0) < second < first <= timedelta(seconds=5)
            getattr(db, finish)()
    with Session(c.source_engine) as db:
        assert (
            tuple(
                db.execute(
                    text(
                        "SELECT current_setting('statement_timeout'),current_setting('lock_timeout'),current_setting('search_path'),pg_backend_pid()"
                    )
                ).one()
            )
            == baseline
        )
        assert _lock(c, db) is None
        db.rollback()


def _migration_snapshot(c):
    with c.connect() as conn:
        return {
            "version": conn.execute("SELECT version_num FROM alembic_version").fetchone()[0],
            "actor": conn.execute(
                "SELECT pg_get_function_identity_arguments(p.oid),p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='public' AND p.proname='miy_whiteboard_lock_owner_actor' ORDER BY 1"
            ).fetchall(),
            "existing": (
                conn.execute(
                    "SELECT id,owner_id,trashed_at,scene,updated_at,writer_scope FROM whiteboards ORDER BY id"
                ).fetchall(),
                conn.execute(
                    "SELECT id,whiteboard_id,room_key,yjs_state,updated_at,writer_scope FROM whiteboard_collab_documents ORDER BY id"
                ).fetchall(),
                conn.execute("SELECT * FROM official_runtime_ownership ORDER BY scope").fetchall(),
                conn.execute(
                    "SELECT * FROM official_writer_principals ORDER BY role_oid"
                ).fetchall(),
                conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0],
                conn.execute(
                    "SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE t.tgname IN ('miy_official_source_writer','miy_official_principal_immutable') ORDER BY 1,2,3"
                ).fetchall(),
                conn.execute(
                    "SELECT p.proname,p.proowner::bigint,p.proacl::text,p.proconfig,p.prosrc "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN "
                    "('miy_guard_official_source_writer','miy_guard_official_source_writer_by_role','miy_recording_lock_producer','miy_whiteboard_lock_source_writer','miy_immutable_official_writer_principal') ORDER BY 1"
                ).fetchall(),
                conn.execute(
                    "SELECT oid::bigint,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconfig FROM pg_roles WHERE rolname=ANY(%s::text[]) ORDER BY oid",
                    (c.roles,),
                ).fetchall(),
                conn.execute(
                    "SELECT c.relname,c.relacl::text,a.attname,a.attacl::text FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname,a.attnum"
                ).fetchall(),
            ),
        }


def test_genuine_normal_legacy_actor_migration_roundtrip_preserves_source_data_and_guards(
    http_world,
):
    import y_py as Y
    from miy_api.domains.whiteboard.models import WhiteboardCollabDocument

    with http_world.core() as db:
        engine = db.get_bind()
        doc = Y.YDoc()
        with doc.begin_transaction() as txn:
            doc.get_map("scene").set(txn, "marker", "legacy-actor-migration")
        db.add(
            WhiteboardCollabDocument(
                id=str(uuid4()),
                whiteboard_id=http_world.ids["board"],
                room_key="legacy-actor:" + http_world.ids["board"],
                yjs_state=bytes(Y.encode_state_as_update(doc)),
            )
        )
        db.commit()
    url = engine.url
    dsn = make_conninfo(
        host=url.host, port=url.port, dbname=url.database, user=url.username, password=url.password
    )
    c = SimpleNamespace(connect=lambda **kwargs: psycopg.connect(dsn, **kwargs), roles=[])
    before = _migration_snapshot(c)
    assert before["version"] == "wb_actor_owner_20261009" and len(before["actor"]) == 1
    config = _migration_config(url.render_as_string(hide_password=False))
    command.downgrade(config, "wb_source_writer_20261009")
    removed = _migration_snapshot(c)
    assert removed["version"] == "wb_source_writer_20261009" and removed["actor"] == []
    assert removed["existing"] == before["existing"]
    command.upgrade(config, "head")
    assert _migration_snapshot(c) == before


def test_genuine_hardened_active_actor_migration_refuses_rollback_without_changes(actor_prepared):
    c = actor_prepared
    before = _migration_snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_requires_draining"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)),
            "wb_source_writer_20261009",
        )
    assert _migration_snapshot(c) == before
    with Session(c.source_engine) as db:
        assert _lock(c, db) is None
        db.rollback()


def test_genuine_hardened_draining_actor_migration_removes_only_inactive_capability(actor_prepared):
    c = actor_prepared
    drained = move(c.control, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    assert drained.generation == 4
    before = _migration_snapshot(c)
    command.downgrade(
        _migration_config(c.engine.url.render_as_string(hide_password=False)),
        "wb_source_writer_20261009",
    )
    removed = _migration_snapshot(c)
    assert removed["version"] == "wb_source_writer_20261009" and removed["actor"] == []
    assert removed["existing"] == before["existing"]
    with Session(c.source_engine) as db:
        _refused(c, db)
    assert _migration_snapshot(c) == removed


@pytest.mark.parametrize("tamper", ["body", "overload"])
def test_genuine_actor_migration_refuses_tampered_capability_without_version_or_data_changes(
    actor_boundary, tamper
):
    c = actor_boundary
    with c.connect() as conn:
        if tamper == "body":
            _replace_body(conn, CAPABILITY)
        else:
            conn.execute(
                "CREATE FUNCTION public.miy_whiteboard_lock_owner_actor(text) RETURNS void LANGUAGE plpgsql AS $$BEGIN RETURN; END$$"
            )
            conn.execute(
                "REVOKE ALL ON FUNCTION public.miy_whiteboard_lock_owner_actor(text) FROM PUBLIC"
            )
    before = _migration_snapshot(c)
    with pytest.raises(RuntimeError, match="whiteboard_actor_capability_contract_invalid"):
        command.downgrade(
            _migration_config(c.engine.url.render_as_string(hide_password=False)),
            "wb_source_writer_20261009",
        )
    assert _migration_snapshot(c) == before


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_genuine_original_admin_update_waits_for_actor_caller_end_then_revokes_current_session(
    actor_prepared, finish
):
    from miy_api.domains.admin.router import AdminUserUpdateRequest, update_user

    c = actor_prepared
    assert c.actor.user.id != c.execution.actor_user_id
    original = _collab_snapshot(c)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(app_realtime=None)))
    with (
        c.connect(autocommit=True) as observer,
        Session(c.engine, autoflush=False) as core,
        Session(c.source_engine) as db,
    ):
        core_pid = core.scalar(text("SELECT pg_backend_pid()"))
        # Keep this actual transaction/connection through the unmodified
        # function call: returning it to a multi-connection pool loses PID identity.
        source_pid = db.scalar(text("SELECT pg_backend_pid()"))
        assert _lock(c, db) is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                update_user,
                user_id=c.execution.actor_user_id,
                payload=AdminUserUpdateRequest(login_blocked=True),
                request=request,
                context=c.actor,
                db=core,
            )
            try:
                _wait_for_blocker(observer, core_pid, source_pid)
                assert not future.done()
                getattr(db, finish)()
                result = future.result(timeout=5)
                assert result.id == c.execution.actor_user_id and result.login_blocked is True
                assert observer.execute(
                    "SELECT login_blocked FROM users WHERE id=%s", (c.execution.actor_user_id,)
                ).fetchone() == (True,)
                assert observer.execute(
                    "SELECT revoked_at IS NOT NULL FROM auth_sessions WHERE id=%s",
                    (c.execution.source_session_id,),
                ).fetchone() == (True,)
                _refused(c, db)
            finally:
                db.rollback()
                core.rollback()
    assert _collab_snapshot(c) == original
