"""Task work segments, summaries and verified development integration receipts."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0012"
down_revision = "console_sqlite_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_task_milestones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("phases", sa.JSON, nullable=False),
        sa.Column("merge", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("task_id", "key"),
    )
    op.create_index("ix_console_task_milestones_task_id", "console_task_milestones", ["task_id"])


def downgrade():
    op.drop_table("console_task_milestones")
