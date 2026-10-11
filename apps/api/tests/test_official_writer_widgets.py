"""Personal Widgets keep their API/ACL while joining the official source boundary."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import psycopg
import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import User
from miy_api.domains.official_apps import writer_roles
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_fence import change, writer as writer
from test_official_writer_roles import (
    ACTIVE,
    BASE,
    activate,
    denied,
    move,
    prepare,
    role_template as role_template,
    sa_dsn,
    wait_for_blocker,
    world as world,
)

REVISION = "official_widget_writer_20261006"
PREVIOUS = "independent_bootstrap_20261006"
WIDGETS = ("personal_todo_items", "personal_memos")
LEGACY_SOURCES = tuple(
    ScriptDirectory.from_config(_migration_config())
    .get_revision("official_writer_fence_20261006")
    .module._SOURCES
)


def old_schema(world):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)


def assert_revision(world, revision, *, fenced):
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
    for table in WIDGETS:
        assert (
            "writer_scope" in {c["name"] for c in inspect(world.engine).get_columns(table)}
        ) is fenced


def seed(conn, user_id):
    conn.execute(
        "INSERT INTO personal_todo_items(id,user_id,title,completed,sort_order,created_at,updated_at) "
        "VALUES ('widget-todo',%s,'Original todo',false,7,now(),now())",
        [user_id],
    )
    conn.execute(
        "INSERT INTO personal_memos(id,user_id,body,created_at,updated_at) "
        "VALUES ('widget-memo',%s,'Original memo',now(),now())",
        [user_id],
    )


def contents(conn):
    return (
        conn.execute(
            "SELECT id,user_id,title,completed,sort_order,created_at,updated_at FROM personal_todo_items ORDER BY id"
        ).fetchall(),
        conn.execute(
            "SELECT id,user_id,body,created_at,updated_at FROM personal_memos ORDER BY id"
        ).fetchall(),
    )


def test_widget_upgrade_downgrade_preserves_rows_and_constraints(world):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    assert_revision(world, REVISION, fenced=True)
    with world.connect() as conn:
        assert contents(conn) == before
        for table in WIDGETS:
            assert conn.execute(f"SELECT writer_scope FROM {table}").fetchone()[0] == SUITE_SCOPE
            denied(conn, f"UPDATE {table} SET writer_scope='other'", "23514")
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before
    command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    with world.connect() as conn:
        assert contents(conn) == before


@pytest.mark.parametrize(
    "operation", ["create_todo", "update_todo", "delete_todo", "create_memo", "update_memo"]
)
def test_widget_http_drain_preserves_content_and_read_access(client, writer, operation):
    factory, admin, _ = writer
    headers = {"Authorization": "Bearer " + admin["token"]}
    base = "/api/v1/personal-widgets"
    created = client.post(base + "/todos", headers=headers, json={"title": "Original todo"})
    assert created.status_code == 201
    if operation != "create_memo":
        assert (
            client.put(base + "/memo", headers=headers, json={"body": "Original memo"}).status_code
            == 200
        )
    before = [client.get(base + path, headers=headers).json() for path in ("/todos", "/memo")]
    with factory.begin() as db:
        change(db, admin)
    method, path, body = {
        "create_todo": ("POST", "/todos", {"title": "Blocked"}),
        "update_todo": ("PATCH", "/todos/" + created.json()["id"], {"completed": True}),
        "delete_todo": ("DELETE", "/todos/" + created.json()["id"], None),
        "create_memo": ("PUT", "/memo", {"body": "Blocked"}),
        "update_memo": ("PUT", "/memo", {"body": "Blocked"}),
    }[operation]
    response = client.request(
        method, base + path, headers=headers, **({"json": body} if body else {})
    )
    assert response.status_code == 503
    assert response.json()["code"] == "official_apps.writer_unavailable"
    assert response.headers["Retry-After"] == "5"
    after = [client.get(base + path, headers=headers) for path in ("/todos", "/memo")]
    assert all(response.status_code == 200 for response in after)
    assert [response.json() for response in after] == before


@pytest.mark.parametrize("table", WIDGETS)
def test_raw_copy_truncate_and_parent_cascade_are_fenced(world, table):
    user_id = str(uuid4())
    with Session(world.engine) as db:
        db.add(
            User(
                id=user_id,
                login_id=user_id,
                email="widget-cascade@example.test",
                full_name="Cascade fixture",
                password_hash="synthetic",
            )
        )
        db.commit()
    with world.connect() as conn:
        seed(conn, user_id)
        before = contents(conn)
    move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        for query in (
            f"INSERT INTO {table} DEFAULT VALUES",
            f"UPDATE {table} SET writer_scope=writer_scope WHERE false",
            f"DELETE FROM {table} WHERE false",
            f"TRUNCATE {table}",
            f"DELETE FROM users WHERE id='{user_id}'",
        ):
            denied(conn, query, "55000")
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction(), conn.cursor().copy(f"COPY {table} (id) FROM STDIN") as copy:
                copy.write_row(("blocked-copy",))
        assert caught.value.sqlstate == "55000"
        assert contents(conn) == before
        assert conn.execute("SELECT id FROM users WHERE id=%s", [user_id]).fetchone()


@pytest.mark.parametrize("table", WIDGETS)
def test_widget_transaction_holds_writer_cas_until_commit(world, table):
    with ThreadPoolExecutor(max_workers=1) as pool, world.connect() as conn:
        conn.execute(f"UPDATE {table} SET writer_scope=writer_scope WHERE false")
        pending = pool.submit(move, world, BASE, "active", state="draining")
        try:
            wait_for_blocker(world, conn.info.backend_pid)
            assert not pending.done()
        finally:
            conn.commit()
        draining = pending.result(timeout=8)
        denied(conn, f"UPDATE {table} SET writer_scope=writer_scope WHERE false", "55000")
    active = move(world, draining, "draining", state="active")
    with world.connect() as conn:
        # Old clients cannot adopt generation three merely by reconnecting.
        denied(conn, f"UPDATE {table} SET writer_scope=writer_scope WHERE false", "55000")
        conn.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            [
                '{"scope":"official.suite","owner":"legacy","generation":%d,"artifact":null}'
                % active.generation
            ],
        )
        conn.execute(f"UPDATE {table} SET writer_scope=writer_scope WHERE false")


def test_hardened_upgrade_requires_drain_and_explicit_new_principal(world, monkeypatch):
    # This historical schema predates the append-only projection transport.
    monkeypatch.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
    old_schema(world)
    # This historical upgrade stops at the 14-table revision; simulate its
    # helper inventory while the current helper is tested at the current head.
    monkeypatch.setattr(writer_roles, "COVERED_SOURCE_TABLES", (*LEGACY_SOURCES, *WIDGETS))
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    # Simulate the previous released helper's frozen 12-table inventory only in
    # this disposable test. The current helper never grants against an old schema.
    with monkeypatch.context() as previous:
        previous.setattr(writer_roles, "COVERED_SOURCE_TABLES", LEGACY_SOURCES)
        old_role, guard_owner, old_oid = activate(world)
    config = _migration_config(sa_dsn(world.dsn))
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, REVISION)
    assert_revision(world, REVISION, fenced=True)
    # Retrying the original immutable principal preparation does not add grants.
    assert prepare(world, old_role, ACTIVE, draining, "draining") == old_oid
    with world.connect() as conn:
        assert contents(conn) == before
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
                "WHERE t.tgname='miy_official_source_writer' AND p.proname='miy_guard_official_source_writer_by_role'"
            ).fetchone()[0]
            == 14
        )
        for table in WIDGETS:
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'UPDATE')", [old_role, table]
            ).fetchone()[0]
    next_identity = WriterIdentity(SUITE_SCOPE, "legacy", 5, "sha256:" + "b" * 64)
    new_role = world.role()
    prepare(world, new_role, next_identity, draining, "draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=guard_owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=old_oid, expected=draining, expected_state="draining"
        )
        db.commit()
    move(world, draining, "draining", state="active", artifact=next_identity.artifact)
    with world.connect(old_role) as conn:
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
        for table in WIDGETS:
            denied(conn, f"UPDATE {table} SET writer_scope=writer_scope WHERE false")
    with world.connect(new_role) as conn:
        assert contents(conn) == before
        conn.execute("UPDATE personal_todo_items SET title='Updated'")
        conn.execute("UPDATE personal_memos SET body='Updated'")
        for table in WIDGETS:
            denied(conn, f"TRUNCATE {table}")
        denied(conn, "UPDATE official_runtime_ownership SET state='active'")
        conn.execute("DELETE FROM personal_todo_items")
        conn.execute("DELETE FROM personal_memos")
        seed(conn, world.user_id)
    with pytest.raises(RuntimeError, match="requires_explicit_retirement"):
        command.downgrade(config, PREVIOUS)
    assert_revision(world, REVISION, fenced=True)


@pytest.mark.parametrize("hazard", ["disabled", "mixed", "arguments"])
def test_migration_rejects_tampered_guard_inventory_without_changes(world, hazard):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
        if hazard == "disabled":
            conn.execute("ALTER TABLE announcements DISABLE TRIGGER miy_official_source_writer")
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON announcements")
            function = (
                "miy_guard_official_source_writer_by_role"
                if hazard == "mixed"
                else "miy_guard_official_source_writer"
            )
            scope = "official.suite" if hazard == "mixed" else "other"
            conn.execute(
                f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON announcements FOR EACH STATEMENT EXECUTE FUNCTION {function}('{scope}')"
            )
    with pytest.raises(RuntimeError, match="guard_inventory_invalid"):
        command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before


def test_migration_refuses_autocommit_before_ddl_or_head_change(world):
    old_schema(world)
    module = ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module
    with world.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="requires_transaction"):
                module.upgrade()
    assert_revision(world, PREVIOUS, fenced=False)
