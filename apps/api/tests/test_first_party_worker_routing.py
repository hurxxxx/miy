from __future__ import annotations

from celery import Celery
import pytest

from miy_api.core.first_party_worker_routing import configure_first_party_celery_routes
from miy_api.core.worker_queue_contract import worker_profile_task_routes


def test_native_publication_keeps_payload_and_uses_owned_queue():
    app = Celery("first-party-route-fixture", broker="memory://", set_as_current=False)
    configure_first_party_celery_routes(app)
    name = "files.cleanup_storage_object"
    queue_name = worker_profile_task_routes("official")[name]["queue"]
    try:
        app.signature(name, args=["job-id"], kwargs={"attempt_id": "attempt-id"}).apply_async(
            queue="celery", task_id="fixed-first-party-task", retry=False, ignore_result=True
        )
        with app.connection_for_write() as connection:
            with connection.SimpleQueue(queue_name) as queue:
                message = queue.get(block=False)
                assert message.headers["task"] == name
                assert message.headers["id"] == "fixed-first-party-task"
                assert message.payload[:2] == [["job-id"], {"attempt_id": "attempt-id"}]
                message.ack()
                queue.queue.delete()
    finally:
        app.close()


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
