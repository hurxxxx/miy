"""One-use owner-approved Workbench registration, independent of identity-only SSO."""

from alembic import op
import sqlalchemy as sa

revision = "registration_auth_20261007"
down_revision = "official_planner_writer_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "independent_app_registration_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id"), nullable=False
        ),
        sa.Column("audience", sa.String(500), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("code_challenge", sa.String(43), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_expires_at", sa.DateTime(), nullable=False),
        sa.Column("exchanged_at", sa.DateTime(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("payload_digest", sa.String(71), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operation_id", "actor_user_id", "source_session_id"):
        op.create_index(
            f"ix_app_registration_{column}",
            "independent_app_registration_authorizations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("independent_app_registration_authorizations")
