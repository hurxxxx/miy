"""Preserve bounded task activity snapshots without changing native transcripts."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0010"
down_revision = "console_sqlite_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("console_events", sa.Column("details", sa.JSON, nullable=True))


def downgrade():
    op.drop_column("console_events", "details")
