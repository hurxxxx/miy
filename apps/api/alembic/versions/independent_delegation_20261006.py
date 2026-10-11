"""Owner-bound, revocable Workbench delivery delegation and durable build intents."""

from alembic import op
import sqlalchemy as sa

revision = "independent_delegation_20261006"
down_revision = "independent_delivery_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "independent_app_delivery_delegations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id"), nullable=False
        ),
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
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("definition_policy", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, target in (
        ("actor_user_id", "users.id"),
        ("source_session_id", "auth_sessions.id"),
        ("delegation_id", "independent_app_delivery_delegations.id"),
        ("installation_id", "independent_app_installations.id"),
    ):
        op.add_column(
            "independent_app_build_jobs",
            sa.Column(name, sa.String(36), sa.ForeignKey(target), nullable=True),
        )
    op.add_column(
        "independent_app_deployment_requests",
        sa.Column(
            "delegation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_delivery_delegations.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("independent_app_deployment_requests", "delegation_id")
    for name in ("installation_id", "delegation_id", "source_session_id", "actor_user_id"):
        op.drop_column("independent_app_build_jobs", name)
    op.drop_table("independent_app_delivery_delegations")
