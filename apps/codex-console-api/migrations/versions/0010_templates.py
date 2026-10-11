"""Versioned task templates and independently owned executions."""

import sqlalchemy as sa
from alembic import op

revision = "console_0010"
down_revision = "console_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "console_tasks",
        sa.Column("executor", sa.String(24), nullable=False, server_default="session"),
    )
    op.add_column("console_tasks", sa.Column("template_snapshot", sa.JSON()))
    op.add_column("console_tasks", sa.Column("launch_id", sa.String(36)))
    op.create_unique_constraint("uq_console_tasks_launch_id", "console_tasks", ["launch_id"])
    op.create_table(
        "console_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "console_host_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Template rollback requires the paired database backup")
