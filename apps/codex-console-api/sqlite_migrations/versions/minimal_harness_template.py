"""Remove the retired review skill only from the unchanged built-in template."""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "console_sqlite_0004"
down_revision = "console_sqlite_0003"
branch_labels = None
depends_on = None

# Frozen historical seed. A customized definition, including an extra field,
# is not ours to rewrite. Execution snapshots are intentionally never updated.
PREVIOUS_DEFINITION = {
    "name": "MR 리뷰",
    "description": "MR을 검토하고 우선순위별 개선점을 보고합니다.",
    "directory": ".",
    "context": "",
    "references": ["AGENTS.md"],
    "skills": ["miy-mr-review"],
    "prompt": (
        "Read AGENTS.md and the applicable repository instructions. Preserve unrelated work. "
        "Review {{mr}}. Report findings here; do not publish comments or merge."
    ),
    "variables": [{"name": "mr", "label": "MR 번호 또는 URL", "default": "", "required": True}],
    "stage": "implement",
    "permissions": "ask",
    "isolate": False,
    "shared_resources": True,
    "model": None,
    "effort": None,
}


def upgrade():
    table = sa.table(
        "console_templates",
        sa.column("id", sa.String),
        sa.column("definition", sa.JSON),
        sa.column("version", sa.Integer),
        sa.column("updated_at", sa.DateTime),
    )
    ident = str(uuid5(NAMESPACE_URL, "mty-codex-template:MR 리뷰"))
    connection = op.get_bind()
    row = connection.execute(sa.select(table).where(table.c.id == ident)).mappings().first()
    if row and row["definition"] == PREVIOUS_DEFINITION:
        connection.execute(
            table.update()
            .where(table.c.id == ident)
            .values(
                definition={**PREVIOUS_DEFINITION, "skills": []},
                version=row["version"] + 1,
                updated_at=sa.func.current_timestamp(),
            )
        )


def downgrade():
    # Reinstalling a retired skill reference would make valid templates unusable.
    # Data backups preserve the previous state if a full release rollback needs it.
    pass
