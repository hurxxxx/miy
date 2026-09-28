"""Separate generation and decision defaults without changing existing routes."""

from alembic import op
import sqlalchemy as sa

revision = "decision_defaults_20260927"
down_revision = "llm_cap_defaults_20260918"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_model_policy_defaults",
        sa.Column("model_family", sa.String(16), nullable=False, server_default="generation"),
    )
    op.drop_constraint("ai_model_policy_defaults_pkey", "ai_model_policy_defaults", type_="primary")
    op.create_primary_key(
        "ai_model_policy_defaults_pkey",
        "ai_model_policy_defaults",
        ["model_family", "app_id", "route_mode"],
    )
    op.create_check_constraint(
        "ck_ai_model_policy_family",
        "ai_model_policy_defaults",
        "model_family IN ('generation', 'decision')",
    )
    op.create_check_constraint(
        "ck_ai_model_decision_cap",
        "ai_model_policy_defaults",
        "model_family != 'decision' OR max_output_tokens IS NULL",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM ai_model_policy_defaults WHERE model_family = 'decision'"))
    op.drop_constraint("ck_ai_model_decision_cap", "ai_model_policy_defaults", type_="check")
    op.drop_constraint("ck_ai_model_policy_family", "ai_model_policy_defaults", type_="check")
    op.drop_constraint("ai_model_policy_defaults_pkey", "ai_model_policy_defaults", type_="primary")
    op.create_primary_key(
        "ai_model_policy_defaults_pkey", "ai_model_policy_defaults", ["app_id", "route_mode"]
    )
    op.drop_column("ai_model_policy_defaults", "model_family")
