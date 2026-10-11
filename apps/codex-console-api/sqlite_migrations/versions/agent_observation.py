"""Separate native observation evidence from stored execution results."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0007"
down_revision = "console_sqlite_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("console_agents", sa.Column("observation", sa.JSON, nullable=True))


def downgrade():
    op.drop_column("console_agents", "observation")
