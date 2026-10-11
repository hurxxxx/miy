"""Allow newly issued miy keys while preserving existing platform API keys."""

from alembic import op
import sqlalchemy as sa

revision = "miy_api_keys_20261001"
down_revision = "decision_defaults_20260927"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_platform_api_keys_prefix", "platform_api_keys", type_="check")
    op.create_check_constraint(
        "ck_platform_api_keys_prefix",
        "platform_api_keys",
        "substr(key_prefix, 1, 7) IN ('miy_pk_', 'mty_pk_')",
    )


def downgrade() -> None:
    # A prefix cannot be rewritten: it is part of the caller's secret and hash.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM platform_api_keys WHERE key_prefix LIKE 'miy_pk_%'")
    ):
        raise RuntimeError("Remove miy platform API keys before downgrading this release.")
    op.drop_constraint("ck_platform_api_keys_prefix", "platform_api_keys", type_="check")
    op.create_check_constraint(
        "ck_platform_api_keys_prefix", "platform_api_keys", "substr(key_prefix, 1, 7) = 'mty_pk_'"
    )
