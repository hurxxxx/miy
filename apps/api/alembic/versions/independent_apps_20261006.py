"""Separate app definitions, release evidence, installations and app-scoped sessions."""

from alembic import op
import sqlalchemy as sa

revision = "independent_apps_20261006"
down_revision = "artifact_sequences_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "independent_app_definitions",
        sa.Column("app_id", sa.String(64), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_independent_app_definitions_owner_user_id",
        "independent_app_definitions",
        ["owner_user_id"],
    )
    op.create_table(
        "independent_app_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("artifact", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("verification_id", sa.String(100), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("app_id", "artifact", name="uq_independent_app_release_artifact"),
    )
    op.create_index("ix_independent_app_releases_app_id", "independent_app_releases", ["app_id"])
    op.create_table(
        "independent_app_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(300), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("user_ids", sa.JSON(), nullable=False),
        sa.Column("group_ids", sa.JSON(), nullable=False),
        sa.Column("granted_permissions", sa.JSON(), nullable=False),
        sa.Column(
            "release_id", sa.String(36), sa.ForeignKey("independent_app_releases.id"), nullable=True
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "app_id", "environment", "origin", name="uq_independent_app_installation"
        ),
        sa.UniqueConstraint("origin", name="uq_independent_app_origin"),
    )
    op.create_index(
        "ix_independent_app_installations_app_id", "independent_app_installations", ["app_id"]
    )
    op.create_index(
        "uq_independent_app_production",
        "independent_app_installations",
        ["app_id"],
        unique=True,
        postgresql_where=sa.text("environment = 'production'"),
    )
    for table, hash_column in (
        ("independent_app_launch_codes", "code_hash"),
        ("independent_app_sessions", "token_hash"),
    ):
        extra = (
            [
                sa.Column("code_challenge", sa.String(43), nullable=False),
                sa.Column("consumed_at", sa.DateTime(), nullable=True),
            ]
            if table == "independent_app_launch_codes"
            else [
                sa.Column("permissions", sa.JSON(), nullable=False),
                sa.Column("revoked_at", sa.DateTime(), nullable=True),
            ]
        )
        op.create_table(
            table,
            sa.Column(hash_column, sa.String(64), primary_key=True),
            sa.Column(
                "installation_id",
                sa.String(36),
                sa.ForeignKey("independent_app_installations.id"),
                nullable=False,
            ),
            sa.Column(
                "source_session_id",
                sa.String(36),
                sa.ForeignKey("auth_sessions.id"),
                nullable=False,
            ),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            *extra,
        )
        op.create_index(f"ix_{table}_installation_id", table, ["installation_id"])
        op.create_index(f"ix_{table}_source_session_id", table, ["source_session_id"])


def downgrade() -> None:
    # Application rollback does not call this destructive schema downgrade.
    for table in (
        "independent_app_sessions",
        "independent_app_launch_codes",
        "independent_app_installations",
        "independent_app_releases",
        "independent_app_definitions",
    ):
        op.drop_table(table)
