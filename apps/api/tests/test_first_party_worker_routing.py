from __future__ import annotations

import importlib

from celery import Celery, current_app
import pytest

from miy_api.core.first_party_worker_routing import configure_first_party_celery_routes
from miy_api.core.worker_queue_contract import TASK_QUEUE_ROUTES, worker_profile_task_routes


@pytest.mark.parametrize(
    "name,module,attribute,args,kwargs",
    [
        (
            "files.cleanup_storage_object",
            "miy_worker.tasks.file_storage_cleanup",
            "cleanup_file_storage_object",
            ["job-id"],
            {},
        ),
        (
            "recording.transcribe",
            "miy_worker.tasks.recording",
            "transcribe_recording",
            ["recording-id"],
            {"attempt_id": "attempt-id"},
        ),
    ],
    ids=("files-cleanup", "recording-transcribe"),
)
def test_native_publication_keeps_payload_and_uses_owned_queue(
    name, module, attribute, args, kwargs
):
    previous_app = current_app._get_current_object()
    app = None
    try:
        actual = getattr(importlib.import_module(module), attribute)
        app = Celery("first-party-route-fixture", broker="memory://", set_as_current=False)
        configure_first_party_celery_routes(app)
        queue_name = worker_profile_task_routes("official")[name]["queue"]
        # Exercise the real task's native argument check regardless of import order.
        task = app.tasks[name]
        assert task.typing
        assert getattr(task.run, "__func__", task.run) is getattr(
            actual.run, "__func__", actual.run
        )
        signature = app.signature(name, args=args, kwargs=kwargs)
        assert signature.type is task
        signature.apply_async(
            queue=TASK_QUEUE_ROUTES[name],
            task_id="fixed-first-party-task",
            retry=False,
            ignore_result=True,
        )
        with app.connection_for_write() as connection:
            with connection.SimpleQueue(queue_name) as queue:
                message = queue.get(block=False)
                assert message.headers["task"] == name
                assert message.headers["id"] == "fixed-first-party-task"
                assert message.payload[:2] == [args, kwargs]
                message.ack()
                queue.queue.delete()
    finally:
        try:
            if app is not None:
                app.close()
        finally:
            previous_app.set_current()


@pytest.mark.parametrize(
    "name,queue",
    [("unregistered.task", "celery"), ("files.cleanup_storage_object", "miy.platform.celery")],
)
def test_unknown_task_or_cross_owner_queue_refuses_before_broker(monkeypatch, name, queue):
    app = Celery("first-party-route-denial", broker="memory://", set_as_current=False)
    configure_first_party_celery_routes(app)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Rejected publication opened a broker connection")

    monkeypatch.setattr(app, "connection_for_write", forbidden)
    try:
        with pytest.raises(ValueError, match="not_owned"):
            app.send_task(name, queue=queue)
    finally:
        app.close()
