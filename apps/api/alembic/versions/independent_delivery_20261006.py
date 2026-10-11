"""Durable local app build, preview admission and deployment reconciliation."""

from alembic import op
import sqlalchemy as sa

revision = "independent_delivery_20261006"
down_revision = "independent_apps_20261006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "independent_app_installations", sa.Column("runtime_ref", sa.String(36), nullable=True)
    )
    op.create_table(
        "independent_app_build_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("executor_id", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column(
            "release_id", sa.String(36), sa.ForeignKey("independent_app_releases.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("executor_id", "active_slot", name="uq_independent_app_heavy_build"),
        sa.CheckConstraint(
            "active_slot IS NULL OR active_slot = 1", name="ck_independent_app_build_slot"
        ),
    )
    op.create_index(
        "ix_independent_app_build_jobs_app_id", "independent_app_build_jobs", ["app_id"]
    )
    op.create_table(
        "independent_app_build_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "build_job_id",
            sa.String(36),
            sa.ForeignKey("independent_app_build_jobs.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "app_id",
            sa.String(64),
            sa.ForeignKey("independent_app_definitions.app_id"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("definition_digest", sa.String(71), nullable=False),
        sa.Column("source_archive_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_digest", sa.String(71), nullable=False),
        sa.Column("builder_profile_digest", sa.String(71), nullable=False),
        sa.Column("target_environment", sa.String(16), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_independent_app_build_verifications_app_id",
        "independent_app_build_verifications",
        ["app_id"],
    )
    op.create_table(
        "independent_app_runtime_slots",
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            primary_key=True,
        ),
        sa.Column("executor_id", sa.String(80), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.UniqueConstraint("executor_id", "slot", name="uq_independent_app_preview_slot"),
        sa.CheckConstraint("slot >= 0 AND slot < 4", name="ck_independent_app_preview_slot"),
    )
    op.create_table(
        "independent_app_deployment_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id"), nullable=False
        ),
        sa.Column(
            "installation_id",
            sa.String(36),
            sa.ForeignKey("independent_app_installations.id"),
            nullable=False,
        ),
        sa.Column(
            "release_id",
            sa.String(36),
            sa.ForeignKey("independent_app_releases.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("expected_release_id", sa.String(36), nullable=True),
        sa.Column("previous_release_id", sa.String(36), nullable=True),
        sa.Column("previous_runtime_ref", sa.String(36), nullable=True),
        sa.Column("executor_id", sa.String(80), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("observed_image_id", sa.String(71), nullable=True),
        sa.Column("runtime_config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("executor_id", "active_slot", name="uq_independent_app_active_deploy"),
        sa.CheckConstraint(
            "active_slot IS NULL OR active_slot = 1", name="ck_independent_app_deploy_slot"
        ),
    )
    op.create_index(
        "ix_independent_app_deployment_requests_installation_id",
        "independent_app_deployment_requests",
        ["installation_id"],
    )
    op.create_index(
        "ix_independent_app_deployment_requests_state",
        "independent_app_deployment_requests",
        ["state"],
    )
    op.create_index(
        "uq_independent_app_pending_deployment",
        "independent_app_deployment_requests",
        ["installation_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running', 'unknown', 'cleanup')"),
    )


def downgrade() -> None:
    for table in (
        "independent_app_deployment_requests",
        "independent_app_runtime_slots",
        "independent_app_build_verifications",
        "independent_app_build_jobs",
    ):
        op.drop_table(table)
    op.drop_column("independent_app_installations", "runtime_ref")
