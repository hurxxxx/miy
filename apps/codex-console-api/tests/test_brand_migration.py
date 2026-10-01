from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text

from codex_console import templates
from codex_console.cli import migrate
from codex_console.models import Task, TaskTemplate, database


def test_renamed_skills_preserve_templates_and_execution_history(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "console.sqlite3")
    migrate(url, revision="console_sqlite_0001")
    engine, factory = database(url)
    ident = str(uuid5(NAMESPACE_URL, "mty-codex-template:MR 리뷰"))
    snapshot = {"id": ident, "version": 7, "skills": ["mty-mr-review"]}
    try:
        with factory.begin() as db:
            db.add(
                Task(
                    id="existing-task",
                    title="Previous run",
                    root=str(tmp_path),
                    template_snapshot=snapshot,
                    executor="templates",
                    status="completed",
                )
            )
            db.add(
                TaskTemplate(
                    id=ident,
                    version=7,
                    definition={
                        "name": "MR 리뷰",
                        "prompt": "Keep my mty notes unchanged.",
                        "skills": ["mty-mr-review", "custom-skill"],
                        "references": [
                            "AGENTS.md",
                            ".agents/skills/mty-mr-review/SKILL.md",
                            ".agents/skills/mty-docs-reader/scripts/read_mty_doc.py",
                        ],
                    },
                )
            )
        migrate(url)
        with factory() as db:
            row = db.get(TaskTemplate, ident)
            assert row.version == 8
            task = db.get(Task, "existing-task")
            assert task.template_snapshot == snapshot
            assert task.title == "Previous run" and task.status == "completed"
            assert row.definition["skills"] == ["miy-mr-review", "custom-skill"]
            assert row.definition["references"] == [
                "AGENTS.md",
                ".agents/skills/miy-mr-review/SKILL.md",
                ".agents/skills/miy-docs-reader/scripts/read_miy_doc.py",
            ]
            assert row.definition["prompt"] == "Keep my mty notes unchanged."
            assert db.scalar(text("SELECT version_num FROM console_alembic_version")) == (
                "console_sqlite_0002"
            )
        templates.seed(factory)
        migrate(url)
        with factory() as db:
            assert len(db.scalars(select(TaskTemplate)).all()) == 6
            assert db.get(TaskTemplate, ident).version == 8
    finally:
        engine.dispose()
