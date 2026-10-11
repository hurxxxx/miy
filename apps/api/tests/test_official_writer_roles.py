"""Real LOGIN principals in a disposable cluster; never grant on the dev DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import time
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from fastapi import HTTPException
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest
from sqlalchemy import inspect, create_engine, text
from sqlalchemy.orm import Session

from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster  # noqa: F401
from miy_api.domains.auth.dependencies import resolve_auth_context_from_session_id
from miy_api.domains.auth.models import AuthSession, User, UserSystemRole, utcnow_naive
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity, transition
from miy_api.domains.official_apps.projection_contracts import WRITER_TRANSPORT_TABLES
from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES, SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import (
    RuntimePrincipal,
    LEGACY_GUARD,
    ROLE_GUARD,
    install_role_guard,
    prepare_principal,
    revoke_principal,
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


def test_migration_is_inactive_and_function_is_private(world):
    schema = inspect(world.engine)
    actual_columns = {
        column["name"]: column["nullable"]
        for column in schema.get_columns("official_writer_principals")
    }
    assert actual_columns == {
        column.name: column.nullable for column in RuntimePrincipal.__table__.columns
    }
    actual_checks = {
        constraint["name"]
        for constraint in schema.get_check_constraints("official_writer_principals")
    }
    assert "ck_official_principal_artifact" in actual_checks
    assert actual_checks == {
        constraint.name
        for constraint in RuntimePrincipal.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    with world.connect() as conn:
        source_write(conn)
        assert conn.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer' AND p.proname=%s",
            [LEGACY_GUARD],
        ).fetchone()[0] == len(COVERED_SOURCE_TABLES) + len(WRITER_TRANSPORT_TABLES)
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert conn.execute(
            "SELECT prosecdef, proconfig FROM pg_proc WHERE oid='public.miy_guard_official_source_writer_by_role()'::regprocedure"
        ).fetchone() == (True, ["search_path=pg_catalog, pg_temp"])
    runtime = world.role()
    with world.connect(runtime) as conn:
        assert not conn.execute(
            "SELECT has_function_privilege(current_user,'public.miy_guard_official_source_writer_by_role()','EXECUTE')"
        ).fetchone()[0]
    command.downgrade(_migration_config(sa_dsn(world.dsn)), "official_writer_fence_20261006")
    with world.connect() as conn:
        source_write(conn)
        assert (
            conn.execute("SELECT to_regclass('official_writer_principals')").fetchone()[0] is None
        )


def test_actual_login_session_identity_and_restricted_grants(world):
    runtime, owner, _ = activate(world)
    outsider = world.role()
    with world.connect(runtime) as conn:
        assert conn.execute("SELECT session_user,current_user").fetchone() == (runtime, runtime)
        for table in COVERED_SOURCE_TABLES:
            conn.execute(
                sql.SQL("UPDATE public.{} SET writer_scope=writer_scope WHERE false").format(
                    sql.Identifier(table)
                )
            )
        conn.execute(
            "SELECT set_config('miy.official_writer', %s, true)",
            [json.dumps({"owner": "official-suite", "generation": 999})],
        )
        source_write(conn)  # GUC does not replace the real LOGIN principal.
        for statement in [
            "SELECT * FROM official_runtime_ownership",
            "UPDATE official_runtime_ownership SET state='active'",
            "DELETE FROM official_writer_principals",
            "INSERT INTO audit_logs(id) VALUES ('forged')",
            "UPDATE users SET status='active'",
            "TRUNCATE announcements",
            "ALTER TABLE announcements DISABLE TRIGGER ALL",
            "CREATE TABLE public.forbidden(id int)",
            f'SET ROLE "{owner}"',
            "SET SESSION AUTHORIZATION postgres",
            "SET session_replication_role=replica",
        ]:
            denied(conn, statement)
    with world.connect(outsider) as conn:
        denied(conn, "UPDATE announcements SET title=title WHERE false")
    with world.connect() as conn:
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
        assert not conn.execute(
            "SELECT has_schema_privilege(%s,'public','CREATE')", [owner]
        ).fetchone()[0]


def test_temp_shadow_search_path_and_guc_cannot_adopt_a_new_generation(world):
    runtime, _, _ = activate(world)
    with world.connect(runtime) as old:
        source_write(old)
        old.commit()
        old.execute("CREATE TEMP TABLE official_runtime_ownership(scope text,state text)")
        old.execute("CREATE TEMP TABLE official_writer_principals(role_name text)")
        old.execute("SET search_path=pg_temp,public,pg_catalog")
        source_write(old)
        old.commit()
        draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
        next_identity = WriterIdentity(SUITE_SCOPE, "legacy", 5, "sha256:" + "b" * 64)
        new_role = world.role()
        prepare(world, new_role, next_identity, draining, "draining")
        move(world, draining, "draining", state="active", artifact=next_identity.artifact)
        old.execute(
            "SELECT set_config('miy.official_writer', %s, true)",
            [
                json.dumps(
                    {
                        "scope": SUITE_SCOPE,
                        "owner": "legacy",
                        "generation": 5,
                        "artifact": next_identity.artifact,
                    }
                )
            ],
        )
        denied(old, "UPDATE public.announcements SET title=title WHERE false", "55000")
        with world.connect(new_role) as conn:
            source_write(conn)
            denied(old, f'SET ROLE "{new_role}"')


def test_principal_identity_is_immutable_and_revocation_is_final(world):
    runtime, _, oid = activate(world)
    with world.connect() as conn:
        denied(conn, "UPDATE official_writer_principals SET generation=100", "55000")
        denied(conn, "DELETE FROM official_writer_principals", "55000")
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="immutable"):
            prepare_principal(
                db,
                world.actor,
                role_name=runtime,
                identity=WriterIdentity(SUITE_SCOPE, "legacy", 4, ACTIVE.artifact),
                expected=ACTIVE,
                expected_state="active",
            )
    with world.connect(runtime) as old:
        source_write(old)
        old.commit()
        with Session(world.engine) as db:
            revoke_principal(
                db, world.actor, role_oid=oid, expected=ACTIVE, expected_state="active"
            )
            db.commit()
        denied(old, "UPDATE announcements SET title=title WHERE false", "55000")
    with world.connect() as conn:
        denied(conn, "UPDATE official_writer_principals SET revoked_at=NULL", "55000")
    with pytest.raises(WriterControlError, match="immutable"):
        prepare(world, runtime, ACTIVE, ACTIVE)


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


@pytest.mark.parametrize(
    "hazard",
    [
        "public_schema",
        "public_control",
        "membership",
        "ownership",
        "security_definer",
        "superuser",
        "sequence",
        "sequence_select",
        "column_update",
        "column_select",
        "grant_option",
        "parameter_set",
    ],
)
def test_preflight_rejects_ambient_privilege_without_repair(world, hazard):
    runtime = world.role()
    with world.connect() as conn:
        if hazard == "public_schema":
            conn.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
        elif hazard == "public_control":
            conn.execute("GRANT UPDATE ON official_runtime_ownership TO PUBLIC")
        elif hazard == "membership":
            member = world.role(login=False)
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(member), sql.Identifier(runtime))
            )
        elif hazard == "ownership":
            conn.execute("CREATE TABLE public.foreign_owned(id int)")
            conn.execute(
                sql.SQL("ALTER TABLE foreign_owned OWNER TO {}").format(sql.Identifier(runtime))
            )
        elif hazard == "security_definer":
            conn.execute(
                "CREATE FUNCTION public.ambient_authority() RETURNS int LANGUAGE SQL SECURITY DEFINER AS 'SELECT 1'"
            )
        elif hazard == "superuser":
            conn.execute(sql.SQL("ALTER ROLE {} SUPERUSER").format(sql.Identifier(runtime)))
        elif hazard == "parameter_set":
            conn.execute(
                sql.SQL("GRANT SET ON PARAMETER session_replication_role TO {}").format(
                    sql.Identifier(runtime)
                )
            )
        elif hazard == "column_update":
            conn.execute("GRANT UPDATE(state) ON official_runtime_ownership TO PUBLIC")
        elif hazard == "column_select":
            conn.execute("GRANT SELECT(payload) ON audit_logs TO PUBLIC")
        elif hazard == "grant_option":
            conn.execute(
                sql.SQL("GRANT UPDATE ON announcements TO {} WITH GRANT OPTION").format(
                    sql.Identifier(runtime)
                )
            )
        elif hazard == "sequence_select":
            conn.execute("CREATE SEQUENCE public.foreign_sequence")
            conn.execute("GRANT SELECT ON SEQUENCE public.foreign_sequence TO PUBLIC")
        elif hazard == "sequence":
            conn.execute("CREATE SEQUENCE public.foreign_sequence")
            conn.execute("GRANT USAGE ON SEQUENCE public.foreign_sequence TO PUBLIC")
    with pytest.raises(WriterControlError, match="writer_role_"):
        prepare(world, runtime)
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        if hazard == "public_control":
            assert conn.execute(
                "SELECT has_table_privilege(%s,'official_runtime_ownership','UPDATE')", [runtime]
            ).fetchone()[0]


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


def test_source_transaction_locks_delay_cas_until_commit(world):
    runtime, _, _ = activate(world)
    with ThreadPoolExecutor(max_workers=1) as pool, world.connect(runtime) as conn:
        source_write(conn)
        pending = pool.submit(
            move, world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact
        )
        try:
            wait_for_blocker(world, conn.info.backend_pid)
            assert not pending.done()
        finally:
            conn.commit()
        assert pending.result(timeout=8).generation == 4
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")


@pytest.mark.parametrize("revocation", ["session", "role"])
def test_guard_install_rechecks_admin_after_control_lock_wait(world, revocation):
    owner = world.role(login=False)
    move(world, BASE, "active", state="draining")

    def install():
        with Session(world.engine) as db:
            install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)
            db.commit()

    with ThreadPoolExecutor(max_workers=1) as pool, world.connect() as lock:
        lock.execute("SELECT * FROM official_runtime_ownership FOR UPDATE")
        pending = pool.submit(install)
        try:
            wait_for_blocker(world, lock.info.backend_pid)
            with world.connect() as admin:
                if revocation == "session":
                    admin.execute(
                        "UPDATE auth_sessions SET revoked_at=now() WHERE id=%s", [world.session_id]
                    )
                else:
                    admin.execute("DELETE FROM user_system_roles WHERE user_id=%s", [world.user_id])
        finally:
            lock.commit()
        with pytest.raises((HTTPException, WriterControlError)):
            pending.result(timeout=8)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer' AND p.proname=%s",
                [ROLE_GUARD],
            ).fetchone()[0]
            == 0
        )


def test_actual_record_dml_copy_and_rollback_preserve_data(world):
    runtime, _, _ = activate(world)
    with world.connect(runtime) as conn:
        conn.execute(
            "INSERT INTO announcements(id,author_id,scope,title,body,is_pinned,created_at,updated_at) VALUES ('role-record',%s,'company','Initial','Body',false,now(),now())",
            [world.user_id],
        )
        conn.commit()
        with conn.cursor().copy(
            "COPY announcements (id,author_id,scope,title,body,is_pinned,created_at,updated_at) FROM STDIN"
        ) as copy:
            copy.write_row(
                (
                    "role-copy",
                    world.user_id,
                    "company",
                    "Copied",
                    "Body",
                    False,
                    utcnow_naive(),
                    utcnow_naive(),
                )
            )
        conn.execute("UPDATE announcements SET title='Changed' WHERE id='role-record'")
        conn.commit()
        conn.execute("DELETE FROM announcements WHERE id='role-record'")
        conn.rollback()
        assert conn.execute("SELECT id,title FROM announcements ORDER BY id").fetchall() == [
            ("role-copy", "Copied"),
            ("role-record", "Changed"),
        ]
        conn.commit()
        move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
        with pytest.raises(psycopg.Error) as caught:
            with (
                conn.transaction(),
                conn.cursor().copy("COPY announcements (id) FROM STDIN") as copy,
            ):
                copy.write_row(("late-copy",))
        assert caught.value.sqlstate == "55000"
        assert conn.execute("SELECT count(*) FROM announcements").fetchone()[0] == 2


def test_prepare_rollback_removes_mapping_grants_and_audit(world):
    runtime = world.role()
    with Session(world.engine) as db:
        prepare_principal(
            db,
            world.actor,
            role_name=runtime,
            identity=ACTIVE,
            expected=BASE,
            expected_state="active",
        )
        db.rollback()
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'announcements','UPDATE')", [runtime]
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='official_writer.principal.prepare'"
            ).fetchone()[0]
            == 0
        )


def test_revocation_waits_for_inflight_source_transaction(world):
    runtime, _, oid = activate(world)

    def revoke():
        with Session(world.engine) as db:
            revoke_principal(
                db, world.actor, role_oid=oid, expected=ACTIVE, expected_state="active"
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=1) as pool, world.connect(runtime) as conn:
        source_write(conn)
        pending = pool.submit(revoke)
        try:
            wait_for_blocker(world, conn.info.backend_pid)
            assert not pending.done()
        finally:
            conn.commit()
        pending.result(timeout=8)
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")


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


@pytest.mark.parametrize("mutation", ["public_execute", "search_path", "security_invoker"])
def test_guard_contract_tamper_is_not_silently_repaired(world, mutation):
    owner = world.role(login=False)
    move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        if mutation == "public_execute":
            conn.execute(
                "GRANT EXECUTE ON FUNCTION public.miy_guard_official_source_writer_by_role() TO PUBLIC"
            )
        elif mutation == "search_path":
            conn.execute(
                "ALTER FUNCTION public.miy_guard_official_source_writer_by_role() SET search_path=public,pg_catalog"
            )
        else:
            conn.execute(
                "ALTER FUNCTION public.miy_guard_official_source_writer_by_role() SECURITY INVOKER"
            )
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError, match="guard_contract"):
            install_role_guard(db, world.actor, guard_owner=owner, expected=DRAIN)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_core_role_preparation_refuses_stale_snapshot_isolation(world, isolation):
    runtime = world.role()
    with Session(world.engine) as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL " + isolation))
        with pytest.raises(WriterControlError, match="requires_read_committed"):
            prepare_principal(
                db,
                world.actor,
                role_name=runtime,
                identity=ACTIVE,
                expected=BASE,
                expected_state="active",
            )


def test_role_preparation_refuses_autocommit(world):
    runtime = world.role()
    engine = world.engine.execution_options(isolation_level="AUTOCOMMIT")
    with engine.connect() as connection, Session(bind=connection) as db:
        with pytest.raises(WriterControlError, match="requires_read_committed"):
            prepare_principal(
                db,
                world.actor,
                role_name=runtime,
                identity=ACTIVE,
                expected=BASE,
                expected_state="active",
            )
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'announcements','UPDATE')", [runtime]
        ).fetchone()[0]
