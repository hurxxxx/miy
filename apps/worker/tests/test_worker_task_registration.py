from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from miy_worker.task_catalog import (
    BEAT_ENTRY_OWNERS,
    legacy_beat_schedule,
    load_legacy_tasks,
    task_modules,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = WORKSPACE_ROOT / "apps" / "worker" / "src" / "miy_worker" / "tasks"


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        if base is None:
            return node.attr
        return f"{base}.{node.attr}"
    return None


def _declares_celery_task(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if _qualified_name(target) == "celery_app.task":
                return True
    return False


def _registered_task_modules() -> set[str]:
    imported = []
    load_legacy_tasks(importer=imported.append)
    return {module.rsplit(".", 1)[1] for module in imported}


def test_celery_task_modules_are_registered_for_worker_bootstrap() -> None:
    task_modules = {
        path.stem
        for path in TASKS_DIR.glob("*.py")
        if path.name != "__init__.py" and _declares_celery_task(path)
    }

    assert task_modules <= _registered_task_modules()


def test_task_and_beat_ownership_do_not_activate_a_second_consumer() -> None:
    platform = set(task_modules("platform"))
    official = set(task_modules("official"))
    assert platform.isdisjoint(official)
    assert platform | official == set(task_modules())
    owner = json.loads((WORKSPACE_ROOT / "apps/official-suite/ownership.json").read_text())
    assert official == set(owner["worker_modules"])
    schedule = legacy_beat_schedule()
    assert set(schedule) == set(BEAT_ENTRY_OWNERS)
    assert {key for key, value in BEAT_ENTRY_OWNERS.items() if value == "official"} == {
        "republish-files-storage-cleanup-jobs",
        "cleanup-stale-meeting-recording-staging",
        "dispatch-due-mail-sync-jobs",
    }
    assert schedule["dispatch-due-mail-sync-jobs"]["task"] == "mail.dispatch_due_sync_jobs"
    assert schedule["cleanup-stale-meeting-recording-staging"]["schedule"] == 3600.0
    assert all(entry["options"]["queue"] == "celery" for entry in schedule.values())
    with pytest.raises(ValueError, match="Unsupported worker ownership"):
        task_modules("future-owner")


def test_actual_legacy_loader_registers_owned_tasks_without_starting_a_worker() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from miy_worker.celery_app import celery_app; "
            "from miy_api.core.worker_queue_contract import TASK_QUEUE_ROUTES; "
            "celery_app.loader.import_default_modules(); "
            "assert set(TASK_QUEUE_ROUTES) <= set(celery_app.tasks); "
            "assert len(celery_app.conf.beat_schedule) == 9; "
            "celery_app.close()",
        ],
        env={
            **os.environ,
            "MIY_ENV_PROFILE": "test",
            "MIY_POSTGRES_DSN": "postgresql+psycopg://fixture:fixture@127.0.0.1:1/fixture",
            "MIY_WORKER_QUEUE_GROUP": "default",
            "MIY_WORKER_BROKER_URL": "memory://",
            "MIY_WORKER_RESULT_BACKEND": "cache+memory://",
            "MIY_OTEL_ENABLED": "0",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
