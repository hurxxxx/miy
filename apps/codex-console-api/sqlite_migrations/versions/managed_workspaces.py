"""Durable managed workspaces and operations independent of native Task lifetime."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0009"
down_revision = "console_sqlite_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("console_projects.id"), nullable=False
        ),
        sa.Column("app_id", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("profile", sa.String(24), nullable=False),
        sa.Column("repository_root", sa.Text, nullable=False),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("source_directory", sa.Text, nullable=False),
        sa.Column("worktree_root", sa.Text, nullable=False, unique=True),
        sa.Column("git_dir", sa.Text),
        sa.Column("common_dir", sa.Text, nullable=False),
        sa.Column("branch", sa.String(200), nullable=False, unique=True),
        sa.Column("base_revision", sa.String(40)),
        sa.Column("source_revision", sa.String(40)),
        sa.Column("source_manifest", sa.JSON),
        sa.Column("source_digest", sa.String(71)),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("admission_open", sa.Boolean, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("auto_refresh", sa.Boolean, nullable=False),
        sa.Column("environment", sa.JSON, nullable=False),
        sa.Column("preview", sa.JSON, nullable=False),
        sa.Column("integration", sa.JSON, nullable=False),
        sa.Column("cleanup", sa.JSON, nullable=False),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_console_workspaces_project_id", "console_workspaces", ["project_id"])
    op.create_table(
        "console_workspace_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("console_workspaces.id"), nullable=False
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("source_revision", sa.String(40)),
        sa.Column("receipt", sa.JSON, nullable=False),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_console_workspace_operations_workspace_id",
        "console_workspace_operations",
        ["workspace_id"],
    )
    # Rebuilding this parent table would cascade-delete existing native history.
    # SQLite permits a nullable REFERENCES column to be added without recreating it.
    op.execute(
        "ALTER TABLE console_tasks ADD COLUMN workspace_id VARCHAR(36) "
        "CONSTRAINT fk_console_task_workspace REFERENCES console_workspaces(id)"
    )
    op.create_index("ix_console_tasks_workspace_id", "console_tasks", ["workspace_id"])


def downgrade():
    # Native DROP COLUMN also preserves the parent and its existing dependents.
    op.drop_index("ix_console_tasks_workspace_id", table_name="console_tasks")
    op.execute("ALTER TABLE console_tasks DROP COLUMN workspace_id")
    op.drop_table("console_workspace_operations")
    op.drop_table("console_workspaces")
