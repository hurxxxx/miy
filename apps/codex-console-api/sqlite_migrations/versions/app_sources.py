"""Explicit owner app checkout bindings; never retarget existing tasks."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0005"
down_revision = "console_sqlite_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_app_sources",
        sa.Column("app_id", sa.String(80), primary_key=True),
        sa.Column("repository_root", sa.Text, nullable=False),
        sa.Column("manifest", sa.JSON, nullable=False),
        sa.Column("manifest_digest", sa.String(71), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade():
    op.drop_table("console_app_sources")
