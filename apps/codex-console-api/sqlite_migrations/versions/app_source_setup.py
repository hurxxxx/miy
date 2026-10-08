"""Explicit, idempotent preparation of new independent app source repositories."""

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0006"
down_revision = "console_sqlite_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_app_source_setups",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("console_projects.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("app_id", sa.String(80), nullable=False, unique=True),
        sa.Column("root_id", sa.String(64), nullable=False),
        sa.Column("root_path", sa.Text, nullable=False),
        sa.Column("template_id", sa.String(32), nullable=False),
        sa.Column("repository", sa.Text, nullable=False),
        sa.Column("bundle_digest", sa.String(71), nullable=False),
        sa.Column("input_digest", sa.String(71), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("stage_device", sa.String(32)),
        sa.Column("stage_inode", sa.String(32)),
        sa.Column("source_root", sa.Text),
        sa.Column("source_revision", sa.String(40)),
        sa.Column("source_version", sa.Integer),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade():
    op.drop_table("console_app_source_setups")
