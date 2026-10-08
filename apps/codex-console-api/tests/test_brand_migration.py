import importlib.util
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import select, text

from codex_console import templates
from codex_console.cli import migrate
from codex_console.models import Task, TaskTemplate, database
from codex_console.storage import SCHEMA


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
            assert db.scalar(text("SELECT version_num FROM console_alembic_version")) == SCHEMA
        templates.seed(factory)
        migrate(url)
        with factory() as db:
            assert len(db.scalars(select(TaskTemplate)).all()) == 11
            assert db.get(TaskTemplate, ident).version == 8
    finally:
        engine.dispose()


@pytest.mark.parametrize("customized", [False, True])
def test_retired_skill_migration_only_updates_unchanged_seed(tmp_path, customized):
    path = Path(__file__).parents[1] / "sqlite_migrations/versions/minimal_harness_template.py"
    spec = importlib.util.spec_from_file_location("minimal_harness_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    previous = {**migration.PREVIOUS_DEFINITION}
    if customized:
        previous["context"] = "My custom review context"
    url = "sqlite+pysqlite:///" + str(tmp_path / "console.sqlite3")
    migrate(url, revision="console_sqlite_0003")
    engine, factory = database(url)
    ident = str(uuid5(NAMESPACE_URL, "mty-codex-template:MR 리뷰"))
    copied_id = str(uuid5(NAMESPACE_URL, "user-copy"))
    historical = {"template_id": ident, "version": 7, "definition": previous}
    try:
        with factory.begin() as db:
            db.add(TaskTemplate(id=ident, definition=previous, version=7))
            db.add(TaskTemplate(id=copied_id, definition=previous, version=2))
            db.add(
                Task(
                    id="historical",
                    title="Review",
                    root=str(tmp_path),
                    executor="templates",
                    template_snapshot=historical,
                    status="completed",
                )
            )
        migrate(url)
        templates.seed(factory)
        migrate(url)
        templates.seed(factory)
        with factory() as db:
            row = db.get(TaskTemplate, ident)
            assert row.version == (7 if customized else 8)
            assert row.definition == (previous if customized else {**previous, "skills": []})
            assert db.get(TaskTemplate, copied_id).definition == previous
            assert db.get(TaskTemplate, copied_id).version == 2
            assert db.get(Task, "historical").template_snapshot == historical
            seeded_review = db.get(
                TaskTemplate, str(uuid5(NAMESPACE_URL, "mty-codex-template:코드 검토"))
            )
            assert seeded_review.definition["stage"] == "plan"
            assert seeded_review.definition["skills"] == []
    finally:
        engine.dispose()
