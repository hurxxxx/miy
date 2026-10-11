"""Personal Widgets keep their API/ACL while joining the official source boundary."""

from alembic.script import ScriptDirectory
from sqlalchemy import inspect
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
