"""Native agent projections and resource-scoped admission."""

import sqlalchemy as sa
from alembic import op

revision = "console_0009"
down_revision = "console_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("console_tasks", sa.Column("context", sa.JSON(), nullable=True))
    op.add_column(
        "console_tasks",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("console_requests", sa.Column("thread_id", sa.String(160), nullable=True))
    op.execute(
        "UPDATE console_requests r SET thread_id=t.thread_id "
        "FROM console_tasks t WHERE t.id=r.task_id"
    )
    op.create_table(
        "console_resource_leases",
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("resource", sa.Text(), primary_key=True),
        sa.Column("exclusive", sa.Boolean(), nullable=False),
    )
    op.execute(
        "INSERT INTO console_resource_leases SELECT t.id, 'workspace:' || t.root, true "
        "FROM console_tasks t JOIN console_workspace_lease l ON l.task_id=t.id"
    )
    op.create_table(
        "console_agents",
        sa.Column("thread_id", sa.String(160), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_thread_id", sa.String(160)),
        sa.Column("session_id", sa.String(160)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(100)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("turn_id", sa.String(160)),
        sa.Column("activity", sa.String(500)),
        sa.Column("progress", sa.JSON()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_console_agents_task_id", "console_agents", ["task_id"])
    op.create_table(
        "console_service_observations",
        sa.Column("service_id", sa.String(100), primary_key=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("version", sa.String(160)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError("Management schema rollback requires the documented paired DB backup")
