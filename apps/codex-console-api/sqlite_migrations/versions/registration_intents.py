"""Explicit first-registration operations, without credentials in SQLite."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0008"
down_revision = "console_sqlite_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_registration_intents",
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("console_tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("operation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("web_session_hash", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(36), unique=True),
        sa.Column("issuer", sa.Text),
        sa.Column("audience", sa.Text),
        sa.Column("actor_user_id", sa.String(36)),
        sa.Column("policy", sa.JSON),
        sa.Column("authorization_state", sa.String(24), nullable=False),
        sa.Column("grant_id", sa.String(36)),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("request_body", sa.JSON),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("receipt", sa.JSON),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade():
    op.drop_table("console_registration_intents")
