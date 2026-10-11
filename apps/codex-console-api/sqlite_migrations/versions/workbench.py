"""Workbench owner records and bounded external projections; existing work is untouched."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0003"
down_revision = "console_sqlite_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(80), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("reuse_decision", sa.String(24), nullable=False),
        sa.Column("reuse_notes", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "console_maintenance",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("app_id", sa.String(80), nullable=False, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("due_on", sa.String(10)),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("target_revision", sa.String(40)),
        sa.Column("verification", sa.JSON),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("console_tasks.id")),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "console_app_budgets",
        sa.Column("app_id", sa.String(80), primary_key=True),
        sa.Column("development_tokens", sa.Integer),
        sa.Column("runtime_tokens", sa.Integer),
        sa.Column("amount_minor", sa.Integer),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
    )
    op.create_table(
        "console_development_usage",
        sa.Column("thread_id", sa.String(160), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("console_tasks.id"), nullable=False, index=True
        ),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("observed_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "console_development_usage_months",
        sa.Column("thread_id", sa.String(160), primary_key=True),
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("console_tasks.id"), nullable=False, index=True
        ),
        sa.Column("total_tokens", sa.Integer, nullable=False),
    )
    op.create_table(
        "console_workbench_observations",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("checked_at", sa.DateTime, nullable=False),
    )


def downgrade():
    for name in (
        "workbench_observations",
        "development_usage_months",
        "development_usage",
        "app_budgets",
        "maintenance",
        "projects",
    ):
        op.drop_table("console_" + name)
