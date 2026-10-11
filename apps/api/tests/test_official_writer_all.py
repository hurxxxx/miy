"""The complete official source inventory is a fixed DB boundary, not app features."""

import ast
import json
from pathlib import Path

import psycopg
import pytest
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    BASE,
    denied,
    move,
    sa_dsn,
)
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import world as world

from alembic import command
from miy_api.domains.auth.models import utcnow_naive

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
