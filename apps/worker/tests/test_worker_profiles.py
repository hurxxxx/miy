from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from miy_worker.task_catalog import legacy_beat_schedule, profile_beat_schedule
from miy_worker.queue_contract import TASK_QUEUE_ROUTES, WORKER_QUEUE_NAMES
from miy_api.core.worker_queue_contract import (
    WORKER_TASK_MODULES,
    WorkerProfileUnavailable,
    worker_profile_publication_route,
    worker_profile_queues,
    worker_profile_task_names,
    worker_profile_task_routes,
)
from miy_api.core.worker_task_publisher import create_fail_fast_celery_publisher

ROOT = Path(__file__).resolve().parents[3]


def test_profile_registry_is_complete_disjoint_and_preserves_legacy_routes():
    names = [task for _, tasks in WORKER_TASK_MODULES.values() for task in tasks]
    assert len(names) == len(set(names)) == 28
    assert set(names) == set(TASK_QUEUE_ROUTES)
    platform, official = (set(worker_profile_task_names(p)) for p in ("platform", "official"))
    assert len(platform) == len(official) == 14
    assert platform.isdisjoint(official) and platform | official == set(names)
    assert worker_profile_task_routes() == {
        name: {"queue": queue} for name, queue in TASK_QUEUE_ROUTES.items()
    }
    assert worker_profile_queues() == WORKER_QUEUE_NAMES
    assert profile_beat_schedule("legacy") == legacy_beat_schedule()
    queues = [set(worker_profile_queues(p)) for p in ("legacy", "platform", "official")]
    assert all(queues[a].isdisjoint(queues[b]) for a, b in ((0, 1), (0, 2), (1, 2)))
    beats = [profile_beat_schedule(p) for p in ("platform", "official")]
    assert [len(b) for b in beats] == [6, 3]
    assert set(beats[0]).isdisjoint(beats[1])
    for profile, entries in zip(("platform", "official"), beats):
        for name, entry in entries.items():
            assert entry["task"] == legacy_beat_schedule()[name]["task"]
            assert entry["schedule"] == legacy_beat_schedule()[name]["schedule"]
            assert entry["options"] == worker_profile_publication_route(profile, entry["task"])


@pytest.mark.parametrize("profile", ["platform", "official"])
def test_split_publisher_is_denied_before_celery_construction(monkeypatch, profile):
    from miy_api.core import worker_task_publisher

    def forbidden(*args, **kwargs):
        pytest.fail("An inactive profile constructed a broker client")

    monkeypatch.setattr(worker_task_publisher, "Celery", forbidden)
    with pytest.raises(WorkerProfileUnavailable, match="worker_profile_not_activated"):
        create_fail_fast_celery_publisher("split", broker="memory://", profile=profile)
    other = "official" if profile == "platform" else "platform"
    with pytest.raises(ValueError, match="worker_task_not_owned"):
        worker_profile_publication_route(profile, worker_profile_task_names(other)[0])


def test_legacy_publisher_keeps_explicit_queue_payload_and_no_retry():
    app = create_fail_fast_celery_publisher(
        "profile-legacy-fixture", broker="memory://", ignore_result=True
    )
    try:
        assert app.conf.task_publish_retry is False
        assert app.conf.broker_connection_retry is False
        with app.connection_for_write() as connection:
            with connection.SimpleQueue("profile-test-owned") as queue:
                app.signature(
                    "recording.transcribe",
                    args=["recording-id"],
                    kwargs={"attempt_id": "attempt-id"},
                    immutable=True,
                ).apply_async(queue="profile-test-owned", retry=False, task_id="fixed-task-id")
                message = queue.get(block=False)
                assert message.headers["task"] == "recording.transcribe"
                assert message.headers["id"] == "fixed-task-id"
                assert message.payload[:2] == [["recording-id"], {"attempt_id": "attempt-id"}]
                message.ack()
                queue.queue.delete()
    finally:
        app.close()


@pytest.mark.parametrize("profile", ["platform", "official"])
def test_actual_profile_registry_and_execution_closed_without_runtime_initialization(profile):
    # Fresh process is intentional: task modules and Celery finalizers are cached.
    script = """
import importlib, json, pathlib, socket, sys
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        if pathlib.Path(args[0]).name.startswith(".env"):
            raise AssertionError("environment file read")
    if event.startswith("socket.connect") or event == "socket.bind":
        raise AssertionError("network access")
sys.addaudithook(audit)
from miy_worker import runtime
from miy_worker import settings
def forbidden(*args, **kwargs):
    raise AssertionError("runtime initialization")
runtime.configure_database = forbidden
runtime.postgres_engine = forbidden
settings.get_settings = forbidden
import miy_api.platform_extensions as extensions
extensions.initialize_platform_extensions = forbidden
from miy_api.core.worker_queue_contract import *
profile = sys.argv[1]
entry = "miy_official_worker.celery_app" if profile == "official" else "miy_worker.platform_app"
app = importlib.import_module(entry).celery_app
owned = set(worker_profile_task_names(profile))
assert {n for n in app.tasks if not n.startswith("celery.")} == owned
assert "miy_worker.celery_app" not in sys.modules
assert set(worker_profile_modules(profile)) <= set(sys.modules)
other = "platform" if profile == "official" else "official"
assert not set(worker_profile_modules(other)).intersection(sys.modules)
assert set(app.amqp.queues) == set(worker_profile_queues(profile))
assert app.conf.task_create_missing_queues is False
if profile == "official":
    for name, limit in (("recording.analyze_transcript", 900), ("recording.verify_transcript_summary", 600)):
        assert app.tasks[name].time_limit == limit
        assert app.tasks[name]._get_exec_options()["time_limit"] == limit
    for name, hard, soft in (("recording.transcribe", 3600, 3300), ("recording.persist_result", 300, None)):
        assert app.tasks[name].time_limit == hard
        assert app.tasks[name].soft_time_limit == soft
        assert app.tasks[name]._get_exec_options()["time_limit"] == hard
        assert app.tasks[name]._get_exec_options()["soft_time_limit"] == soft
    from miy_worker.tasks.mail import _MAIL_SYNC_TASK_TIME_LIMIT, _MAIL_SYNC_SOFT_TIME_LIMIT
    for name in ("mail.sync_job", "mail.sync_account"):
        task = app.tasks[name]
        assert task.time_limit == _MAIL_SYNC_TASK_TIME_LIMIT
        assert task.soft_time_limit == _MAIL_SYNC_SOFT_TIME_LIMIT
        assert task._get_exec_options()["time_limit"] == _MAIL_SYNC_TASK_TIME_LIMIT
        assert task._get_exec_options()["soft_time_limit"] == _MAIL_SYNC_SOFT_TIME_LIMIT
    cleanup = app.tasks[FILE_STORAGE_CLEANUP_TASK_NAME]
    assert cleanup.time_limit == 120 and cleanup.soft_time_limit == 90
    assert cleanup._get_exec_options()["time_limit"] == 120
    assert cleanup._get_exec_options()["soft_time_limit"] == 90
for action in [lambda: app.Worker(queues="celery"), lambda: app.Beat(),
               lambda: app.worker_main(), lambda: app.start(),
               lambda: app.send_task(next(iter(owned))),
               lambda: app.connection_for_write(), lambda: app.connection_for_read(),
               lambda: app.tasks[next(iter(owned))].run("fixture"),
               lambda: app.tasks[next(iter(owned))].apply(args=["fixture"], throw=True)]:
    try: action()
    except WorkerProfileUnavailable: pass
    else: raise AssertionError("inactive execution accepted")
for name in [worker_profile_modules(other)[0], "miy_worker.celery_app"]:
    try: importlib.import_module(name)
    except RuntimeError as exc:
        assert str(exc) in {"worker_task_module_not_owned", "worker_profile_process_conflict"}
    else: raise AssertionError("mixed profile accepted")
print(json.dumps({"profile": profile, "tasks": len(owned), "beat": len(app.conf.beat_schedule)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, profile],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                str(ROOT / path)
                for path in ("apps/worker/src", "apps/api/src", "apps/official-suite/worker/src")
            ),
        },
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tasks"] == 14
