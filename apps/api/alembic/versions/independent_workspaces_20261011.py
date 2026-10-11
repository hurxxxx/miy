"""Durable app development candidates and search ownership, preserving releases."""

from alembic import op
import sqlalchemy as sa

revision = "independent_workspaces_20261011"
down_revision = "wb_checked_cas_20261009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "independent_app_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "parent_installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            nullable=False,
        ),
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(64), nullable=False),
        sa.Column("profile_digest", sa.String(64), nullable=False),
        sa.Column("creation_digest", sa.String(64), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("integration_revision", sa.String(40), nullable=True),
        sa.Column("resources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("profile_id", "slot", name="uq_app_workspace_slot"),
    )
    op.create_table(
        "independent_app_workspace_candidates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("independent_app_workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_independent_app_workspace_candidates_workspace_id",
        "independent_app_workspace_candidates",
        ["workspace_id"],
    )
    op.create_table(
        "independent_app_search_bindings",
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("search_spec_sha256", sa.String(64), nullable=False),
        sa.Column(
            "candidate_release_id",
            sa.String(36),
            sa.ForeignKey("independent_app_releases.id"),
            nullable=False,
        ),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("opensearch_index", sa.String(120), nullable=False),
        sa.Column("opensearch_uuid", sa.String(100), nullable=True),
        sa.Column("qdrant_collection", sa.String(120), nullable=False),
        sa.Column("embedding_profile", sa.String(100), nullable=False),
        sa.Column("embedding_config_sha256", sa.String(64), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("cleanup_phase", sa.String(20), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_app_search_keyword_index", "independent_app_search_bindings", ["opensearch_index"]
    )
    op.create_unique_constraint(
        "uq_app_search_vector_collection", "independent_app_search_bindings", ["qdrant_collection"]
    )
    op.create_index(
        "ix_independent_app_search_bindings_workspace_id",
        "independent_app_search_bindings",
        ["workspace_id"],
    )


def downgrade():
    op.drop_table("independent_app_search_bindings")
    op.drop_table("independent_app_workspace_candidates")
    op.drop_table("independent_app_workspaces")
