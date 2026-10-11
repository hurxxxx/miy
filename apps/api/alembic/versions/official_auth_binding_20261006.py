"""Core approval binding for official suite app-session authentication."""

from alembic import op
import sqlalchemy as sa

revision = "official_auth_binding_20261006"
down_revision = "independent_delegation_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_app_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "release_id",
            sa.String(36),
            sa.ForeignKey("independent_app_releases.id"),
            nullable=False,
        ),
        sa.Column(
            "verification_id",
            sa.String(36),
            sa.ForeignKey("independent_app_build_verifications.id"),
            nullable=False,
        ),
        sa.Column("artifact", sa.String(500), nullable=False),
        sa.Column("origin", sa.String(300), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("logical_app_ids", sa.JSON(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "approved_by_session_id",
            sa.String(36),
            sa.ForeignKey("auth_sessions.id"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("installation_id", "generation", name="uq_official_binding_generation"),
    )


def downgrade() -> None:
    op.drop_table("official_app_bindings")
