"""Planner source writes share the suite fence, without expanding AI or DB authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from dev_accounts import configure_company_app_access
from fastapi import HTTPException
import psycopg
import pytest
from sqlalchemy import func, select, inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from miy_api.core.principal import user_principal, system_principal
from miy_api.domains.auth.models import User
from miy_api.domains.official_apps import writer_roles
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE, COVERED_SOURCE_TABLES
from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
from miy_api.domains.planner import service
from miy_api.domains.planner.event_application import PlannerEventUpdateCommand
from miy_api.domains.planner.models import PlannerEvent
from miy_api.domains.retrieval.models import RetrievalPartition
from test_official_writer_fence import change, writer as writer
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
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

BODY = {"title": "Original event", "start": "2026-10-07T01:00:00Z", "end": "2026-10-07T02:00:00Z"}


@pytest.fixture
def planner_context(client, writer):
    factory, admin, _ = writer
    with factory() as db:
        configure_company_app_access(db, app_ids=["planner"])
    return factory, admin, {"Authorization": "Bearer " + admin["token"]}


def counts(factory):
    with factory() as db:
        return (
            db.scalar(select(func.count()).select_from(PlannerEvent)),
            db.scalar(select(func.count()).select_from(RetrievalPartition)),
        )


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_planner_http_drain_blocks_write_and_preserves_partition(
    client, planner_context, operation
):
    factory, admin, headers = planner_context
    path = "/api/v1/planner/events"
    original = None
    if operation != "create":
        response = client.post(path, headers=headers, json=BODY)
        assert response.status_code == 201
        original = response.json()
        path += "/" + original["id"]
    before = counts(factory)
    with factory.begin() as db:
        change(db, admin)
    method, body = {
        "create": ("POST", BODY),
        "update": ("PATCH", {"title": "Blocked"}),
        "delete": ("DELETE", None),
    }[operation]
    response = client.request(method, path, headers=headers, **({"json": body} if body else {}))
    assert response.status_code == 503
    assert response.json()["code"] == "official_apps.writer_unavailable"
    assert response.headers["Retry-After"] == "5"
    assert counts(factory) == before
    if original:
        assert client.get(path, headers=headers).json() == original
    else:
        assert client.get(path, headers=headers).status_code == 200


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_preapproved_ai_service_cannot_bypass_drain(client, planner_context, operation):
    factory, admin, headers = planner_context
    original = None
    if operation != "create":
        response = client.post("/api/v1/planner/events", headers=headers, json=BODY)
        assert response.status_code == 201
        original = response.json()
    before = counts(factory)
    with factory.begin() as db:
        change(db, admin)
    with factory() as db:
        user = db.get(User, admin["user"]["id"])
        principal = user_principal(user_id=user.id, source="approved-planner-fixture")
        with pytest.raises(DBAPIError) as denied:
            if operation == "create":
                service.create_event_for_ai(
                    db,
                    principal=principal,
                    user=user,
                    title="Blocked",
                    start_at=datetime(2026, 10, 7, 1),
                    end_at=datetime(2026, 10, 7, 2),
                    approved_call_id=str(uuid4()),
                )
            elif operation == "update":
                service.update_event_for_ai(
                    db,
                    principal=principal,
                    user=user,
                    event_id=original["id"],
                    title="Blocked",
                    approved_call_id=str(uuid4()),
                )
            else:
                service.delete_event_for_ai(
                    db,
                    principal=principal,
                    user=user,
                    event_id=original["id"],
                    approved_call_id=str(uuid4()),
                )
        assert denied.value.orig.sqlstate == "55000"
        db.rollback()
    assert counts(factory) == before
    if original:
        assert (
            client.get("/api/v1/planner/events/" + original["id"], headers=headers).json()
            == original
        )


REVISION = "official_planner_writer_20261006"
PREVIOUS = "official_widget_writer_20261006"
PREVIOUS_SOURCES = tuple(
    ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module._EXISTING_SOURCES
)


def test_partition_repair_rolls_back_with_fenced_source(planner_context):
    factory, admin, _ = planner_context
    event_id = str(uuid4())
    with factory.begin() as db:
        db.add(
            PlannerEvent(
                id=event_id,
                owner_id=admin["user"]["id"],
                title="Unpartitioned",
                start_at=datetime(2026, 10, 7, 1),
                end_at=datetime(2026, 10, 7, 2),
            )
        )
    before = counts(factory)
    with factory.begin() as db:
        change(db, admin)
    with factory() as db:
        user = db.get(User, admin["user"]["id"])
        with pytest.raises(DBAPIError) as refused:
            service.update_event(
                db, user=user, event_id=event_id, command=PlannerEventUpdateCommand(title="Blocked")
            )
        assert refused.value.orig.sqlstate == "55000"
        db.rollback()
    assert counts(factory) == before
    with factory() as db:
        event = db.get(PlannerEvent, event_id)
        assert event.title == "Unpartitioned" and event.retrieval_partition_id is None


def test_approved_create_replay_remains_read_only_during_drain(planner_context):
    factory, admin, _ = planner_context
    operation = str(uuid4())
    with factory() as db:
        user = db.get(User, admin["user"]["id"])
        principal = user_principal(user_id=user.id, source="approved-planner-fixture")
        before = service.create_event_for_ai(
            db,
            principal=principal,
            user=user,
            title="One operation",
            start_at=datetime(2026, 10, 7, 1),
            end_at=datetime(2026, 10, 7, 2),
            approved_call_id=operation,
        )
    original_counts = counts(factory)
    with factory.begin() as db:
        change(db, admin)
    with factory() as db:
        user = db.get(User, admin["user"]["id"])
        after = service.create_event_for_ai(
            db,
            principal=principal,
            user=user,
            title="One operation",
            start_at=datetime(2026, 10, 7, 1),
            end_at=datetime(2026, 10, 7, 2),
            approved_call_id=operation,
        )
        assert after == before
    assert counts(factory) == original_counts


@pytest.mark.parametrize("invalid_principal", ["system", "other_user"])
def test_fence_does_not_relax_ai_user_authority(planner_context, invalid_principal):
    factory, admin, _ = planner_context
    with factory.begin() as db:
        change(db, admin)
    with factory() as db:
        user = db.get(User, admin["user"]["id"])
        principal = (
            system_principal(source="invalid-fixture")
            if invalid_principal == "system"
            else user_principal(user_id=str(uuid4()), source="invalid-fixture")
        )
        with pytest.raises(HTTPException) as refused:
            service.create_event_for_ai(
                db,
                principal=principal,
                user=user,
                title="Not authorized",
                start_at=datetime(2026, 10, 7, 1),
                end_at=datetime(2026, 10, 7, 2),
                approved_call_id=str(uuid4()),
            )
        assert refused.value.status_code == 403


def old_schema(world):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)


def assert_revision(world, revision, *, fenced):
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
    assert (
        "writer_scope" in {c["name"] for c in inspect(world.engine).get_columns("planner_events")}
    ) is fenced


def seed(conn, user_id):
    conn.execute(
        "INSERT INTO planner_events(id,owner_id,title,description,location,time_zone,all_day,start_has_time,end_has_time,start_at,end_at,created_at,updated_at) "
        "VALUES ('planner-row',%s,'Original event','Original description','Original location','Asia/Seoul',false,true,true,'2026-10-07 01:00','2026-10-07 02:00',now(),now())",
        [user_id],
    )


def contents(conn):
    return conn.execute(
        "SELECT id,owner_id,title,description,location,time_zone,all_day,start_has_time,end_has_time,start_at,end_at,created_at,updated_at,retrieval_partition_id,visibility FROM planner_events ORDER BY id"
    ).fetchall()


def test_planner_migration_preserves_data_and_schema_rollback(world):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    assert_revision(world, REVISION, fenced=True)
    with world.connect() as conn:
        assert contents(conn) == before
        assert conn.execute("SELECT writer_scope FROM planner_events").fetchone()[0] == SUITE_SCOPE
        denied(conn, "UPDATE planner_events SET writer_scope='other'", "23514")
    schema = inspect(world.engine)
    assert any(
        fk["constrained_columns"] == ["writer_scope"]
        and fk["referred_table"] == "official_runtime_ownership"
        for fk in schema.get_foreign_keys("planner_events")
    )
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before
    command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    with world.connect() as conn:
        assert contents(conn) == before


def test_planner_raw_copy_truncate_and_stale_generation_fail_closed(world):
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    draining = move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        for query in (
            "INSERT INTO planner_events DEFAULT VALUES",
            "UPDATE planner_events SET writer_scope=writer_scope WHERE false",
            "DELETE FROM planner_events",
            "TRUNCATE planner_events",
        ):
            denied(conn, query, "55000")
        with pytest.raises(psycopg.Error) as caught:
            with (
                conn.transaction(),
                conn.cursor().copy("COPY planner_events (id) FROM STDIN") as copy,
            ):
                copy.write_row(("blocked-copy",))
        assert caught.value.sqlstate == "55000"
        assert contents(conn) == before
    active = move(world, draining, "draining", state="active")
    with world.connect() as conn:
        denied(conn, "UPDATE planner_events SET title=title WHERE false", "55000")
        conn.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            [
                '{"scope":"official.suite","owner":"legacy","generation":%d,"artifact":null}'
                % active.generation
            ],
        )
        conn.execute("UPDATE planner_events SET title=title WHERE false")


def test_planner_source_transaction_blocks_drain_until_commit(world):
    with ThreadPoolExecutor(max_workers=1) as pool, world.connect() as conn:
        conn.execute("UPDATE planner_events SET title=title WHERE false")
        pending = pool.submit(move, world, BASE, "active", state="draining")
        try:
            wait_for_blocker(world, conn.info.backend_pid)
            assert not pending.done()
        finally:
            conn.commit()
        assert pending.result(timeout=8).generation == 2
        denied(conn, "UPDATE planner_events SET title=title WHERE false", "55000")


def test_hardened_fourteen_to_fifteen_requires_explicit_principal(world, monkeypatch):
    # This historical schema predates the append-only projection transport.
    monkeypatch.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
    old_schema(world)
    # Historical 14→15 transition must retain its own helper inventory even
    # when today's runtime protects later sources as well.
    monkeypatch.setattr(
        writer_roles, "COVERED_SOURCE_TABLES", (*PREVIOUS_SOURCES, "planner_events")
    )
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
    with monkeypatch.context() as previous:
        previous.setattr(writer_roles, "COVERED_SOURCE_TABLES", PREVIOUS_SOURCES)
        old_role, guard_owner, old_oid = activate(world)
    config = _migration_config(sa_dsn(world.dsn))
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, REVISION)
    assert_revision(world, REVISION, fenced=True)
    assert prepare(world, old_role, ACTIVE, draining, "draining") == old_oid
    with world.connect() as conn:
        assert contents(conn) == before
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'planner_events','UPDATE')", [old_role]
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid WHERE t.tgname='miy_official_source_writer' AND p.proname='miy_guard_official_source_writer_by_role'"
            ).fetchone()[0]
            == 15
        )
    identity = WriterIdentity(SUITE_SCOPE, "legacy", 5, "sha256:" + "b" * 64)
    new_role = world.role()
    prepare(world, new_role, identity, draining, "draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=guard_owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=old_oid, expected=draining, expected_state="draining"
        )
        db.commit()
    move(world, draining, "draining", state="active", artifact=identity.artifact)
    with world.connect(old_role) as conn:
        denied(conn, "UPDATE planner_events SET title=title WHERE false")
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
    with world.connect(new_role) as conn:
        assert contents(conn) == before
        conn.execute("UPDATE planner_events SET title='Updated'")
        conn.execute("DELETE FROM planner_events")
        seed(conn, world.user_id)
        for statement in (
            "TRUNCATE planner_events",
            "UPDATE official_runtime_ownership SET state='active'",
            "UPDATE retrieval_partitions SET metadata_version=metadata_version WHERE false",
        ):
            denied(conn, statement)
    with pytest.raises(RuntimeError, match="requires_explicit_retirement"):
        command.downgrade(config, PREVIOUS)
    assert_revision(world, REVISION, fenced=True)


@pytest.mark.parametrize("hazard", ["disabled", "mixed", "arguments"])
def test_planner_upgrade_rejects_guard_tamper_without_partial_ddl(world, hazard):
    old_schema(world)
    with world.connect() as conn:
        seed(conn, world.user_id)
        before = contents(conn)
        if hazard == "disabled":
            conn.execute("ALTER TABLE personal_memos DISABLE TRIGGER miy_official_source_writer")
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON personal_memos")
            function = (
                "miy_guard_official_source_writer_by_role"
                if hazard == "mixed"
                else "miy_guard_official_source_writer"
            )
            scope = "official.suite" if hazard == "mixed" else "other"
            conn.execute(
                f"CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON personal_memos FOR EACH STATEMENT EXECUTE FUNCTION {function}('{scope}')"
            )
    with pytest.raises(RuntimeError, match="guard_inventory_invalid"):
        command.upgrade(_migration_config(sa_dsn(world.dsn)), REVISION)
    assert_revision(world, PREVIOUS, fenced=False)
    with world.connect() as conn:
        assert contents(conn) == before


@pytest.mark.parametrize("isolation", ["AUTOCOMMIT", "REPEATABLE READ"])
def test_planner_migration_requires_lock_preserving_transaction(world, isolation):
    old_schema(world)
    module = ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module
    with world.engine.connect().execution_options(isolation_level=isolation) as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="requires_transaction|requires_read_committed"):
                module.upgrade()
    assert_revision(world, PREVIOUS, fenced=False)


def test_new_principal_cannot_receive_unfenced_current_source_grants(world):
    from miy_api.domains.official_apps.writer import WriterControlError

    old_schema(world)
    role = world.role()
    refusal = None
    try:
        prepare(world, role)
    except WriterControlError as error:
        refusal = error
    with world.connect() as conn:
        granted = conn.execute(
            "SELECT has_table_privilege(%s,'planner_events','UPDATE')", [role]
        ).fetchone()[0]
        principals = conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0]
        audit = conn.execute(
            "SELECT count(*) FROM audit_logs WHERE action='official_writer.principal.prepare'"
        ).fetchone()[0]
    if granted:
        # Failure-first proof: the newly granted LOGIN can actually write the
        # unfenced source even though the complete guard was never installed.
        with world.connect(role) as conn:
            conn.execute("UPDATE planner_events SET title=title WHERE false")
    assert not granted and principals == audit == 0
    assert refusal is not None and str(refusal) == "writer_role_trigger_inventory_invalid"


def test_existing_exact_principal_replay_does_not_expand_historical_grants(world, monkeypatch):
    old_schema(world)
    role = world.role()
    with monkeypatch.context() as previous:
        previous.setattr(writer_roles, "COVERED_SOURCE_TABLES", PREVIOUS_SOURCES)
        previous.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
        oid = prepare(world, role)
    assert prepare(world, role) == oid
    with world.connect() as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'planner_events','UPDATE')", [role]
        ).fetchone()[0]
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='official_writer.principal.prepare'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "hazard", ["missing", "disabled", "scope", "nargs", "events", "function_schema", "mixed"]
)
def test_new_principal_checks_exact_full_guard_before_any_grant(world, hazard):
    from miy_api.domains.official_apps.writer import WriterControlError

    role = world.role()
    with world.connect() as conn:
        if hazard == "disabled":
            conn.execute("ALTER TABLE planner_events DISABLE TRIGGER miy_official_source_writer")
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON planner_events")
            if hazard != "missing":
                function = "public.miy_guard_official_source_writer"
                arguments = "'official.suite'"
                events = "INSERT OR UPDATE OR DELETE OR TRUNCATE"
                if hazard == "scope":
                    arguments = "'other'"
                elif hazard == "nargs":
                    arguments += ", 'extra'"
                elif hazard == "events":
                    events = "INSERT"
                elif hazard == "function_schema":
                    conn.execute("CREATE SCHEMA writer_probe")
                    conn.execute(
                        "CREATE FUNCTION writer_probe.miy_guard_official_source_writer() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$"
                    )
                    function = "writer_probe.miy_guard_official_source_writer"
                elif hazard == "mixed":
                    function = "public.miy_guard_official_source_writer_by_role"
                conn.execute(
                    f"CREATE TRIGGER miy_official_source_writer BEFORE {events} ON planner_events FOR EACH STATEMENT EXECUTE FUNCTION {function}({arguments})"
                )
    with pytest.raises(WriterControlError, match="writer_role_trigger_inventory_invalid"):
        prepare(world, role)
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='official_writer.principal.prepare'"
            ).fetchone()[0]
            == 0
        )
        for table in COVERED_SOURCE_TABLES:
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')", [role, table]
            ).fetchone()[0]
