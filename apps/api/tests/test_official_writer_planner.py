"""Planner source writes share the suite fence, without expanding AI or DB authority."""

import pytest
from alembic.script import ScriptDirectory
from dev_accounts import configure_company_app_access
from sqlalchemy import func, inspect, select
from test_alembic_migrations import _migration_config
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_fence import writer as writer
from test_official_writer_roles import (
    role_template as role_template,
)
from test_official_writer_roles import (
    sa_dsn,
)
from test_official_writer_roles import (
    world as world,
)

from alembic import command
from miy_api.domains.planner.models import PlannerEvent
from miy_api.domains.retrieval.models import RetrievalPartition

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


REVISION = "official_planner_writer_20261006"
PREVIOUS = "official_widget_writer_20261006"
PREVIOUS_SOURCES = tuple(
    ScriptDirectory.from_config(_migration_config()).get_revision(REVISION).module._EXISTING_SOURCES
)


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
