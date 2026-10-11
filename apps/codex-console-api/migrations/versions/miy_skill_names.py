"""Rename repository-owned skill references without rewriting execution history."""

import sqlalchemy as sa
from alembic import op

revision = "console_0011"
down_revision = "console_0010"
branch_labels = None
depends_on = None

_SKILLS = (
    "agent-harness",
    "ai-capabilities",
    "app-delivery",
    "design-review",
    "dev-environment",
    "docs-reader",
    "env-contracts",
    "issues",
    "mr-review",
    "production",
    "release",
    "worktrees",
)


def _rename(before, after):
    table = sa.table(
        "console_templates",
        sa.column("id", sa.String),
        sa.column("definition", sa.JSON),
        sa.column("version", sa.Integer),
    )
    names = {f"{before}-{name}": f"{after}-{name}" for name in _SKILLS}
    connection = op.get_bind()
    for row in connection.execute(sa.select(table)).mappings().all():
        definition = dict(row["definition"])
        skills = [names.get(skill, skill) for skill in definition.get("skills", [])]
        references = [
            next(
                (
                    reference.replace(
                        f".agents/skills/{old}/", f".agents/skills/{new}/", 1
                    ).replace(f"/read_{before}_doc.py", f"/read_{after}_doc.py")
                    for old, new in names.items()
                    if reference.startswith(f".agents/skills/{old}/")
                ),
                reference,
            )
            for reference in definition.get("references", [])
        ]
        if skills == definition.get("skills", []) and references == definition.get(
            "references", []
        ):
            continue
        definition.update(skills=skills, references=references)
        connection.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(definition=definition, version=row["version"] + 1)
        )


def upgrade():
    _rename("mty", "miy")


def downgrade():
    _rename("miy", "mty")
