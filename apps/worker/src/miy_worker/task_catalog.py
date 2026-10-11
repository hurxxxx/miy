from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from types import ModuleType
from miy_worker.runtime import ensure_api_src_on_path

ensure_api_src_on_path()

from miy_api.core.worker_queue_contract import (  # noqa: E402
    WORKER_TASK_MODULES,
    WorkerProfile as WorkerOwner,
    worker_profile,
    worker_profile_modules,
    worker_profile_task_routes,
)

TASK_MODULE_OWNERS = {module: owner for module, (owner, _) in WORKER_TASK_MODULES.items()}


def task_modules(owner: WorkerOwner = "legacy") -> tuple[str, ...]:
    return worker_profile_modules(owner)


def load_legacy_tasks(importer: Callable[[str], ModuleType] = import_module) -> None:
    for module in task_modules():
        importer(module)


BEAT_ENTRY_OWNERS = {
    "republish-pending-hermes-runs": "platform",
    "maintain-hermes-terminal-sessions": "platform",
    "republish-pending-ai-graph-runs": "platform",
    "cleanup-orphan-media": "platform",
    "republish-files-storage-cleanup-jobs": "official",
    "cleanup-stale-meeting-recording-staging": "official",
    "dispatch-due-mail-sync-jobs": "official",
    "republish-pending-rag-jobs": "platform",
    "republish-pending-search-index-jobs": "platform",
}


def legacy_beat_schedule() -> dict[str, dict[str, object]]:
    from miy_worker.queue_contract import (
        AI_GRAPH_REPUBLISH_TASK_NAME,
        DEFAULT_QUEUE,
        FILE_STORAGE_CLEANUP_REPUBLISH_TASK_NAME,
        HERMES_REPUBLISH_TASK_NAME,
        HERMES_TERMINAL_MAINTENANCE_TASK_NAME,
    )

    return {
        "republish-pending-hermes-runs": {
            "task": HERMES_REPUBLISH_TASK_NAME,
            "schedule": 30.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "maintain-hermes-terminal-sessions": {
            "task": HERMES_TERMINAL_MAINTENANCE_TASK_NAME,
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "republish-pending-ai-graph-runs": {
            "task": AI_GRAPH_REPUBLISH_TASK_NAME,
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "cleanup-orphan-media": {
            "task": "media.cleanup_orphans",
            "schedule": 3600.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "republish-files-storage-cleanup-jobs": {
            "task": FILE_STORAGE_CLEANUP_REPUBLISH_TASK_NAME,
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "cleanup-stale-meeting-recording-staging": {
            "task": "meeting.cleanup_stale_staging",
            "schedule": 3600.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "dispatch-due-mail-sync-jobs": {
            "task": "mail.dispatch_due_sync_jobs",
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "republish-pending-rag-jobs": {
            "task": "rag.republish_pending_jobs",
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
        "republish-pending-search-index-jobs": {
            "task": "search.republish_pending_index_jobs",
            "schedule": 60.0,
            "options": {"queue": DEFAULT_QUEUE},
        },
    }


def load_profile_tasks(
    owner: WorkerOwner, importer: Callable[[str], ModuleType] = import_module
) -> None:
    for module in task_modules(owner):
        importer(module)


def profile_beat_schedule(owner: WorkerOwner) -> dict[str, dict[str, object]]:
    selected = worker_profile(owner)
    routes = worker_profile_task_routes(selected)
    return {
        name: {**entry, "options": {**entry["options"], **routes[entry["task"]]}}
        for name, entry in legacy_beat_schedule().items()
        if selected == "legacy" or BEAT_ENTRY_OWNERS[name] == selected
    }
