"""Real LOGIN principals in a disposable cluster; never grant on the dev DB."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster  # noqa: F401

from alembic import command
from miy_api.domains.auth.dependencies import resolve_auth_context_from_session_id
from miy_api.domains.auth.models import AuthSession, User, UserSystemRole, utcnow_naive
from miy_api.domains.official_apps.projection_contracts import WRITER_TRANSPORT_TABLES
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, transition
from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES, SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import (
    LEGACY_GUARD,
    ROLE_GUARD,
    install_role_guard,
    prepare_principal,
)

PASSWORD = "synthetic-role-test-only"
BASE = WriterIdentity(SUITE_SCOPE, "legacy", 1)
DRAIN = WriterIdentity(SUITE_SCOPE, "legacy", 2)
ACTIVE = WriterIdentity(SUITE_SCOPE, "legacy", 3, "sha256:" + "a" * 64)


def sa_dsn(dsn):
    fields = conninfo_to_dict(dsn)
    from sqlalchemy import URL

    return URL.create(
        "postgresql+psycopg",
        username=fields["user"],
        password=fields["password"],
        host=fields["host"],
        port=int(fields["port"]),
        database=fields["dbname"],
    ).render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def role_template(isolated_data_cluster):  # noqa: F811
    name = "miy_test_role_template_" + uuid4().hex[:12]
    with psycopg.connect(isolated_data_cluster, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(isolated_data_cluster, dbname=name)
    command.upgrade(_migration_config(sa_dsn(dsn)), "head")
    yield isolated_data_cluster, name
    with psycopg.connect(isolated_data_cluster, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def world(role_template):
    cluster, template = role_template
    name = "miy_test_roles_" + uuid4().hex[:12]
    roles = []
    with psycopg.connect(cluster, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        )
    dsn = make_conninfo(cluster, dbname=name)
    engine = create_engine(sa_dsn(dsn))
    user_id, session_id = str(uuid4()), str(uuid4())
    with Session(engine) as db:
        db.add(
            User(
                id=user_id,
                login_id=user_id,
                email="role@example.test",
                full_name="Role fixture",
                password_hash="synthetic",
            )
        )
        db.flush()
        db.add_all(
            [
                UserSystemRole(id=str(uuid4()), user_id=user_id, role="platform_admin"),
                AuthSession(
                    id=session_id,
                    user_id=user_id,
                    token_hash=uuid4().hex + uuid4().hex,
                    expires_at=utcnow_naive() + timedelta(hours=1),
                ),
            ]
        )
        db.commit()
        actor = resolve_auth_context_from_session_id(db, session_id)
        db.expunge_all()

    def role(*, login=True):
        role_name = "writer_fixture_" + uuid4().hex[:20]
        with psycopg.connect(dsn) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(
                    sql.Identifier(role_name),
                    sql.SQL("LOGIN" if login else "NOLOGIN"),
                    sql.Literal(PASSWORD),
                )
            )
        roles.append(role_name)
        return role_name

    def connect(role_name=None, **kwargs):
        return psycopg.connect(
            make_conninfo(
                dsn,
                user=role_name or "postgres",
                password=PASSWORD if role_name else conninfo_to_dict(dsn)["password"],
            ),
            **kwargs,
        )

    result = SimpleNamespace(
        dsn=dsn,
        engine=engine,
        actor=actor,
        user_id=user_id,
        session_id=session_id,
        role=role,
        connect=connect,
        roles=roles,
    )
    yield result
    engine.dispose()
    with psycopg.connect(cluster, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        for role_name in roles:
            conn.execute(
                sql.SQL("REVOKE ALL ON PARAMETER session_replication_role FROM {}").format(
                    sql.Identifier(role_name)
                )
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


def move(world, expected, expected_state, *, state, artifact=None):
    with Session(world.engine) as db:
        result = transition(
            db,
            world.actor,
            request_id=uuid4(),
            expected=expected,
            expected_state=expected_state,
            owner="legacy",
            state=state,
            artifact=artifact,
            reason="Disposable role boundary verification",
        )
        db.commit()
        return WriterIdentity(
            SUITE_SCOPE, result["owner"], result["generation"], result["artifact"]
        )


def prepare(world, name, identity=ACTIVE, expected=BASE, state="active"):
    with Session(world.engine) as db:
        result = prepare_principal(
            db,
            world.actor,
            role_name=name,
            identity=identity,
            expected=expected,
            expected_state=state,
        )
        oid = result.role_oid
        db.commit()
        return oid


def activate(world):
    runtime, owner = world.role(), world.role(login=False)
    oid = prepare(world, runtime)
    move(world, BASE, "active", state="draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
        db.commit()
    move(world, DRAIN, "draining", state="active", artifact=ACTIVE.artifact)
    return runtime, owner, oid


def source_write(conn):
    conn.execute("UPDATE public.announcements SET title=title WHERE false")


def denied(conn, statement, state="42501"):
    with pytest.raises(psycopg.Error) as caught:
        with conn.transaction():
            conn.execute(statement)
    assert caught.value.sqlstate == state


def test_renamed_and_recreated_role_cannot_reuse_a_mapping(world):
    runtime, _, _ = activate(world)
    renamed = "writer_renamed_" + uuid4().hex[:20]
    with world.connect() as conn:
        conn.execute(
            sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                sql.Identifier(runtime), sql.Identifier(renamed)
            )
        )
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}").format(
                sql.Identifier(runtime), sql.Literal(PASSWORD)
            )
        )
        # Even an incorrect later source grant does not make the replacement OID valid.
        conn.execute(
            sql.SQL("GRANT UPDATE,SELECT ON announcements TO {}").format(sql.Identifier(runtime))
        )
    world.roles.append(renamed)
    for name in (runtime, renamed):
        with world.connect(name) as conn:
            denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
    with pytest.raises(WriterControlError, match="immutable"):
        prepare(world, runtime, ACTIVE, ACTIVE)


def test_guard_owner_preflight_exact_cas_and_transaction_rollback(world):
    runtime, owner = world.role(), world.role(login=False)
    prepare(world, runtime)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="compare_and_swap"):
            install_role_guard(db, world.actor, guard_owner=owner, expected=BASE)
    move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        conn.execute(sql.SQL("GRANT SELECT ON users TO {}").format(sql.Identifier(owner)))
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="existing_privilege"):
            install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
    with world.connect() as conn:
        conn.execute(sql.SQL("REVOKE SELECT ON users FROM {}").format(sql.Identifier(owner)))
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
        db.rollback()
    with world.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer' AND p.proname=%s",
            [LEGACY_GUARD],
        ).fetchone()[0] == len(COVERED_SOURCE_TABLES) + len(WRITER_TRANSPORT_TABLES)
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_runtime_ownership','UPDATE')", [owner]
        ).fetchone()[0]
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
        db.commit()
        install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
        db.commit()
    with pytest.raises(Exception, match="requires_explicit_retirement"):
        command.downgrade(_migration_config(sa_dsn(world.dsn)), "official_writer_fence_20261006")


def wait_for_blocker(world, blocker):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with world.connect() as conn:
            if conn.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid)))",
                [blocker],
            ).fetchone()[0]:
                return
        time.sleep(0.02)
    pytest.fail("Expected a real PostgreSQL row-lock waiter")


def test_admin_revoked_during_trigger_ddl_wait_rolls_back_guard_and_grants(world):
    owner = world.role(login=False)
    move(world, BASE, "active", state="draining")

    def install():
        with Session(world.engine) as db:
            install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
            db.commit()

    with ThreadPoolExecutor(max_workers=1) as pool, world.connect() as lock:
        lock.execute("LOCK TABLE announcements IN ACCESS SHARE MODE")
        pending = pool.submit(install)
        try:
            wait_for_blocker(world, lock.info.backend_pid)
            with world.connect() as admin:
                admin.execute(
                    "UPDATE auth_sessions SET revoked_at=now() WHERE id=%s", [world.session_id]
                )
        finally:
            lock.commit()
        with pytest.raises(HTTPException):
            pending.result(timeout=8)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer' AND p.proname=%s",
                [ROLE_GUARD],
            ).fetchone()[0]
            == 0
        )
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_runtime_ownership','UPDATE')", [owner]
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='official_writer.role_guard.install'"
            ).fetchone()[0]
            == 0
        )
