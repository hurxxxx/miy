"""Atomic, immutable initial personal-app registration receipts."""

from alembic import op
import sqlalchemy as sa

revision = "independent_bootstrap_20261006"
down_revision = "official_writer_roles_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "independent_app_bootstrap_operations",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            nullable=False,
        ),
        sa.Column("payload_digest", sa.String(71), nullable=False),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("app_id"),
        sa.UniqueConstraint("installation_id"),
    )
    op.create_index(
        "ix_independent_app_bootstrap_operations_owner_user_id",
        "independent_app_bootstrap_operations",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_table("independent_app_bootstrap_operations")
