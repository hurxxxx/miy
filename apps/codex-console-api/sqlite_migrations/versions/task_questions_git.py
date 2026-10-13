"""Durable asynchronous questions and explicit task Git links."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0011"
down_revision = "console_sqlite_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_async_questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(160), nullable=False),
        sa.Column("turn_id", sa.String(160), nullable=False),
        sa.Column("item_id", sa.String(200), nullable=False),
        sa.Column("questions", sa.JSON, nullable=False),
        sa.Column("execution", sa.JSON, nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("answers", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("task_id", "item_id"),
    )
    op.create_index("ix_console_async_questions_task_id", "console_async_questions", ["task_id"])
    op.create_table(
        "console_task_git_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("root", sa.Text, nullable=False),
        sa.Column("common_dir", sa.Text, nullable=False),
        sa.Column("git_dir", sa.Text, nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("task_id", "root"),
    )
    op.create_index("ix_console_task_git_links_task_id", "console_task_git_links", ["task_id"])


def downgrade():
    op.drop_table("console_task_git_links")
    op.drop_table("console_async_questions")
