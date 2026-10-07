"""The complete official source inventory is a fixed DB boundary, not app features."""

import ast
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg import sql
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps import writer_roles
from miy_api.domains.official_apps.source_guard import lock_source_writer
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.projection_contracts import WRITER_TRANSPORT_TABLES
from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES, SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
from test_alembic_migrations import _migration_config

from test_official_writer_roles import (
    BASE,
    ACTIVE,
    activate,
    denied,
    move,
    prepare,
    sa_dsn,
    wait_for_blocker,
)
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster

ROOT = Path(__file__).resolve().parents[3]


def owned_sources():
    sources = []
    owner = json.loads((ROOT / "apps/official-suite/ownership.json").read_text())
    for module in owner["model_modules"]:
        tree = ast.parse(
            (ROOT / "apps/api/src" / Path(*module.split(".")).with_suffix(".py")).read_text()
        )
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef):
                for item in cls.body:
                    if isinstance(item, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "__tablename__" for t in item.targets
                    ):
                        sources.append(ast.literal_eval(item.value))
    assert len(sources) == len(set(sources)) == 88
    return tuple(sources)


SOURCES = owned_sources()
REVISION = "official_source_writer_20261007"
PREVIOUS = "official_dm_writer_20261007"
MIGRATION = ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module
OLD = tuple(MIGRATION._EXISTING_SOURCES)
NEW = tuple(MIGRATION._SOURCES)


def test_fixed_inventory_matches_owned_models_and_frozen_chain():
    import_all_models()
    assert len(OLD) == 19 and len(NEW) == 69
    assert set(OLD).isdisjoint(NEW)
    assert set(SOURCES) == set(COVERED_SOURCE_TABLES) == set((*OLD, *NEW))
    assert {t.name for t in Base.metadata.tables.values() if "writer_scope" in t.c} == set(
        (*SOURCES, *WRITER_TRANSPORT_TABLES)
    )
    for name in SOURCES:
        column = Base.metadata.tables[name].c.writer_scope
        assert not column.nullable and str(column.server_default.arg) == SUITE_SCOPE
        assert {f.target_fullname for f in column.foreign_keys} == {
            "official_runtime_ownership.scope"
        }


def sql_sources(conn, *, denied_state=None):
    """Real statements on every table, including zero-row DML and empty COPY."""
    for table in SOURCES:
        identifier = sql.Identifier(table)
        statements = [
            sql.SQL("INSERT INTO {} (writer_scope) SELECT 'official.suite' WHERE false").format(
                identifier
            ),
            sql.SQL("UPDATE {} SET writer_scope=writer_scope WHERE false").format(identifier),
            sql.SQL("DELETE FROM {} WHERE false").format(identifier),
        ]
        for statement in statements:
            if denied_state:
                with pytest.raises(psycopg.Error) as error:
                    conn.execute(statement)
                assert error.value.sqlstate == denied_state, table
                conn.rollback()
            else:
                conn.execute(statement)
                conn.commit()
        if denied_state:
            with pytest.raises(psycopg.Error) as error:
                with conn.cursor().copy(
                    sql.SQL("COPY {} (writer_scope) FROM STDIN").format(identifier)
                ):
                    pass
            assert error.value.sqlstate == denied_state, table
            conn.rollback()
        else:
            with conn.cursor().copy(
                sql.SQL("COPY {} (writer_scope) FROM STDIN").format(identifier)
            ):
                pass
            conn.commit()


def all_rows(conn):
    return {
        name: conn.execute(
            sql.SQL("SELECT (to_jsonb(t)-'writer_scope')::text FROM {} t ORDER BY 1").format(
                sql.Identifier(name)
            )
        ).fetchall()
        for name in SOURCES
    }


def seed_representative_sources(world):
    from miy_api.domains.bento.models import BentoDocument
    from miy_api.domains.community.models import CommunityChannel
    from miy_api.domains.diagrams.models import Diagram
    from miy_api.domains.files.models import FileManagerFolder
    from miy_api.domains.mail.models import MailAccount
    from miy_api.domains.meeting.models import Meeting
    from miy_api.domains.pms.space_models import Team
    from miy_api.domains.recording.models import Recording
    from miy_api.domains.video_chat.models import VideoChatSession
    from miy_api.domains.whiteboard.models import Whiteboard

    user = world.user_id
    now = utcnow_naive()
    with Session(world.engine) as db:
        db.add_all(
            [
                BentoDocument(id="all-bento", owner_id=user, title="Original", document_json="{}"),
                CommunityChannel(id="all-community", key="synthetic", name="Original"),
                Diagram(
                    id="all-diagram",
                    owner_id=user,
                    title="Original",
                    source_storage_key="synthetic/original",
                ),
                FileManagerFolder(id="all-folder", owner_id=user, name="Original"),
                MailAccount(
                    id="all-mail",
                    user_id=user,
                    email_address="synthetic@example.test",
                    incoming_host="synthetic.invalid",
                    incoming_port=993,
                    incoming_username="synthetic",
                    incoming_password_encrypted="synthetic",
                    smtp_host="synthetic.invalid",
                    smtp_port=587,
                    smtp_username="synthetic",
                    smtp_password_encrypted="synthetic",
                ),
                Meeting(
                    id="all-meeting", organizer_id=user, title="Original", start_at=now, end_at=now
                ),
                Team(id="all-space", key="all-space", name="Original"),
                Recording(id="all-recording", owner_id=user, title="Original", started_at=now),
                VideoChatSession(
                    id="all-video", started_by_id=user, room_name="synthetic", title="Original"
                ),
                Whiteboard(id="all-board", owner_id=user, title="Original"),
            ]
        )
        db.commit()


def test_all_sources_real_statements_copy_truncate_and_late_rollback(world):
    seed_representative_sources(world)
    with world.connect() as conn:
        before = all_rows(conn)
        sql_sources(conn)
        for table in SOURCES:
            conn.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))
            conn.rollback()
        assert all_rows(conn) == before
        conn.execute("UPDATE bento_documents SET title='uncommitted'")
        conn.execute("UPDATE diagrams SET title='uncommitted'")
        conn.execute("UPDATE meetings SET title='uncommitted'")
        conn.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            ['{"scope":"official.suite","owner":"legacy","generation":99,"artifact":null}'],
        )
        with pytest.raises(psycopg.Error) as error:
            conn.execute("UPDATE whiteboards SET title='uncommitted'")
        assert error.value.sqlstate == "55000"
        conn.rollback()
        assert all_rows(conn) == before
    move(world, BASE, "active", state="draining")
    with world.connect() as conn:
        sql_sources(conn, denied_state="55000")
        for table in SOURCES:
            denied(conn, sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)), "55000")
        assert all_rows(conn) == before


def test_complete_migration_preserves_data_and_schema_roundtrip(world):
    seed_representative_sources(world)
    config = _migration_config(sa_dsn(world.dsn))
    with world.connect() as conn:
        before = all_rows(conn)
    for revision, operation in [
        (PREVIOUS, command.downgrade),
        (REVISION, command.upgrade),
        (PREVIOUS, command.downgrade),
        (REVISION, command.upgrade),
    ]:
        operation(config, revision)
        with world.connect() as conn:
            assert all_rows(conn) == before
            assert conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0] == (19 if revision == PREVIOUS else 88)
    schema = inspect(world.engine)
    for name in SOURCES:
        column = next(c for c in schema.get_columns(name) if c["name"] == "writer_scope")
        assert not column["nullable"]
        assert any(
            c["constrained_columns"] == ["writer_scope"]
            and c["referred_table"] == "official_runtime_ownership"
            for c in schema.get_foreign_keys(name)
        )
        assert any(
            c["name"] == f"ck_{name}_writer_scope" for c in schema.get_check_constraints(name)
        )


def test_complete_role_upgrade_preserves_old_grants_and_rejects_stale_sessions(world, monkeypatch):
    # This historical schema predates the append-only projection transport.
    monkeypatch.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
    config = _migration_config(sa_dsn(world.dsn))
    command.downgrade(config, PREVIOUS)
    with monkeypatch.context() as old:
        old.setattr(writer_roles, "COVERED_SOURCE_TABLES", OLD)
        role, guard_owner, oid = activate(world)
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, REVISION)
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, REVISION)
    assert prepare(world, role, ACTIVE, draining, "draining") == oid
    with world.connect() as conn:
        for table in NEW:
            assert not conn.execute(
                "SELECT has_table_privilege(%s,%s,'UPDATE')", [role, table]
            ).fetchone()[0]
    identity = WriterIdentity(SUITE_SCOPE, "legacy", 5, "sha256:" + "c" * 64)
    new_role = world.role()
    new_oid = prepare(world, new_role, identity, draining, "draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=guard_owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=oid, expected=draining, expected_state="draining"
        )
        db.commit()
    with world.connect(new_role) as conn:
        denied(conn, "UPDATE diagrams SET title=title WHERE false", "55000")
        move(world, draining, "draining", state="active", artifact=identity.artifact)
        sql_sources(conn)
        for table in SOURCES:
            denied(conn, sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))
        for forbidden in [
            "SELECT * FROM users",
            "SELECT * FROM official_runtime_ownership",
            "UPDATE audit_logs SET id=id WHERE false",
            "SELECT * FROM media_files",
        ]:
            denied(conn, forbidden)
        next_drain = move(world, identity, "active", state="draining", artifact=identity.artifact)
        sql_sources(conn, denied_state="55000")
        with Session(world.engine) as db:
            revoke_principal(
                db, world.actor, role_oid=new_oid, expected=next_drain, expected_state="draining"
            )
            db.commit()
        denied(conn, "UPDATE diagrams SET title=title WHERE false", "55000")
    with world.connect(role) as conn:
        denied(conn, "UPDATE announcements SET title=title WHERE false", "55000")
        denied(conn, "UPDATE diagrams SET title=title WHERE false")
    with pytest.raises(RuntimeError, match="requires_explicit_retirement"):
        command.downgrade(config, PREVIOUS)


def test_new_principal_against_old_schema_grants_nothing(world):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)
    role = world.role()
    with world.connect() as conn:
        counts = conn.execute(
            "SELECT (SELECT count(*) FROM official_writer_principals),(SELECT count(*) FROM audit_logs)"
        ).fetchone()
    with pytest.raises(WriterControlError, match="writer_role_trigger_inventory_invalid"):
        prepare(world, role, ACTIVE, BASE, "active")
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT (SELECT count(*) FROM official_writer_principals),(SELECT count(*) FROM audit_logs)"
            ).fetchone()
            == counts
        )
        assert all(
            not conn.execute("SELECT has_table_privilege(%s,%s,'UPDATE')", [role, t]).fetchone()[0]
            for t in SOURCES
        )


def test_external_effect_helper_uses_transaction_guard_and_blocks_drain(world):
    with Session(world.engine) as db, ThreadPoolExecutor(max_workers=1) as pool:
        pid = db.scalar(text("SELECT pg_backend_pid()"))
        lock_source_writer(db, "diagrams")
        pending = pool.submit(move, world, BASE, "active", state="draining")
        try:
            wait_for_blocker(world, pid)
            assert not pending.done()
        finally:
            db.rollback()
        pending.result(timeout=8)
        with pytest.raises(Exception) as error:
            lock_source_writer(db, "diagrams")
        assert error.value.orig.sqlstate == "55000"


@pytest.mark.parametrize("hazard", ["disabled", "arguments", "mixed"])
def test_complete_migration_rejects_old_guard_drift_atomically(world, hazard):
    config = _migration_config(sa_dsn(world.dsn))
    command.downgrade(config, PREVIOUS)
    with world.connect() as conn:
        if hazard == "disabled":
            conn.execute("ALTER TABLE announcements DISABLE TRIGGER miy_official_source_writer")
        else:
            conn.execute("DROP TRIGGER miy_official_source_writer ON announcements")
            function = (
                "miy_guard_official_source_writer_by_role"
                if hazard == "mixed"
                else "miy_guard_official_source_writer"
            )
            argument = "official.suite" if hazard == "mixed" else "wrong"
            conn.execute(
                sql.SQL(
                    "CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON announcements FOR EACH STATEMENT EXECUTE FUNCTION {}({})"
                ).format(sql.Identifier(function), sql.Literal(argument))
            )
    with pytest.raises(RuntimeError, match="guard_inventory_invalid"):
        command.upgrade(config, REVISION)
    with world.connect() as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS
        for name in NEW:
            assert not conn.execute(
                "SELECT 1 FROM pg_attribute WHERE attrelid=%s::regclass AND attname='writer_scope' AND NOT attisdropped",
                [name],
            ).fetchone()


@pytest.mark.parametrize("isolation", ["AUTOCOMMIT", "REPEATABLE READ", "SERIALIZABLE"])
def test_new_migration_and_external_effect_lock_require_real_current_transaction(world, isolation):
    command.downgrade(_migration_config(sa_dsn(world.dsn)), PREVIOUS)
    engine = world.engine.execution_options(isolation_level=isolation)
    with engine.connect() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            with pytest.raises(RuntimeError, match="requires_"):
                MIGRATION.upgrade()
    with Session(engine) as db:
        with pytest.raises(HTTPException) as error:
            lock_source_writer(db, "announcements")
        assert error.value.status_code == 503


def test_all_owned_sources_refuse_actual_dml_during_drain(world):
    move(world, BASE, "active", state="draining")
    unfenced = []
    for table in SOURCES:
        with world.connect() as conn:
            column = conn.execute(
                "SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass "
                "AND attnum>0 AND NOT attisdropped ORDER BY attnum LIMIT 1",
                [table],
            ).fetchone()[0]
            try:
                conn.execute(
                    sql.SQL("UPDATE {} SET {}={} WHERE false").format(
                        sql.Identifier(table), sql.Identifier(column), sql.Identifier(column)
                    )
                )
            except psycopg.Error as error:
                assert error.sqlstate == "55000"
                conn.rollback()
            else:
                unfenced.append(table)
    assert not unfenced, unfenced
