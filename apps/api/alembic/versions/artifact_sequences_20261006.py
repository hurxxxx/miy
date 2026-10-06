"""Restore artifact number sequences omitted from the deployment baseline."""

from alembic import op
import sqlalchemy as sa

revision = "artifact_sequences_20261006"
down_revision = "miy_api_keys_20261001"
branch_labels = None
depends_on = None

_SEQUENCES = (
    ("report", "AIR", "ai_report_artifact_number_seq"),
    ("analysis", "AIA", "ai_analysis_artifact_number_seq"),
)


def upgrade() -> None:
    for _, _, sequence in _SEQUENCES:
        op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {sequence} AS bigint"))
        # Hold sequence DDL locks until commit, before locking artifact writers.
        # Existing installations may already have allocated numbers; never rewind them.
        op.execute(sa.text(f"ALTER SEQUENCE {sequence} INCREMENT BY 1 NO CYCLE"))
    op.execute(sa.text("LOCK TABLE ai_artifacts IN SHARE ROW EXCLUSIVE MODE"))
    for artifact_type, prefix, sequence in _SEQUENCES:
        op.execute(
            sa.text(f"""
            DO $migration$
            DECLARE
                artifact_next bigint;
                sequence_next bigint;
            BEGIN
                SELECT COALESCE(MAX(split_part(artifact_number, '-', 3)::bigint), 0) + 1
                INTO artifact_next
                FROM ai_artifacts
                WHERE artifact_type = '{artifact_type}'
                  AND artifact_number ~ '^{prefix}-[0-9]{{8}}-[0-9]+$';

                SELECT last_value + CASE WHEN is_called THEN 1 ELSE 0 END
                INTO sequence_next FROM {sequence};

                EXECUTE format('ALTER SEQUENCE {sequence} RESTART WITH %s',
                               GREATEST(artifact_next, sequence_next));
            END
            $migration$;
        """)
        )


def downgrade() -> None:
    # The preceding application already requires these sequences. Retain the
    # compatible repair and its allocation positions when rolling back code.
    pass
