"""Owned Celery queues for an explicit first-party process composition.

Task IDs, payloads and native Celery publication remain unchanged. Existing
caller-selected legacy queues are translated only for their catalogued task;
an unrelated queue or unknown task refuses before broker access.
"""

from celery import Celery
from celery.app.amqp import AMQP
from celery.app.routes import Router
from kombu import Exchange, Queue

from miy_api.core.worker_queue_contract import (
    TASK_QUEUE_ROUTES,
    DEFAULT_QUEUE,
    WORKER_TASK_MODULES,
    worker_profile_queues,
    worker_profile_task_routes,
)

_OWNERS = {task_name: owner for owner, tasks in WORKER_TASK_MODULES.values() for task_name in tasks}
_ROUTES = {
    **worker_profile_task_routes("platform"),
    **worker_profile_task_routes("official"),
}


class FirstPartyWorkerRouter(Router):
    def route(self, options, name, args=(), kwargs=None, task_type=None):
        if name not in _OWNERS:
            raise ValueError("first_party_worker_task_not_owned")
        expected = _ROUTES[name]["queue"]
        requested = options.get("queue")
        requested_name = getattr(requested, "name", requested)
        if requested_name not in (None, TASK_QUEUE_ROUTES[name], expected):
            raise ValueError("first_party_worker_queue_not_owned")
        selected = dict(options)
        selected["queue"] = expected
        for field in ("exchange", "routing_key"):
            value = options.get(field)
            value_name = getattr(value, "name", value)
            if value_name not in (None, TASK_QUEUE_ROUTES[name], DEFAULT_QUEUE, expected):
                raise ValueError("first_party_worker_destination_not_owned")
            if value is not None:
                selected[field] = expected
        return super().route(selected, name, args, kwargs, task_type)


class FirstPartyAMQP(AMQP):
    """Pinned Celery extension: configured routes alone cannot replace explicit queues."""

    def Router(self, queues=None, create_missing=None):
        return FirstPartyWorkerRouter(
            self.routes,
            queues or self.queues,
            self.app.either("task_create_missing_queues", create_missing),
            app=self.app,
        )


def configure_first_party_celery_routes(app: Celery, *, profile: str = "legacy") -> None:
    if "amqp" in app.__dict__ and not isinstance(app.__dict__["amqp"], FirstPartyAMQP):
        raise RuntimeError("first_party_worker_routes_already_bound")
    app.amqp_cls = FirstPartyAMQP
    profiles = ("platform", "official") if profile == "legacy" else (profile,)
    names = tuple(
        dict.fromkeys(name for selected in profiles for name in worker_profile_queues(selected))
    )
    routes = {
        task: route
        for selected in profiles
        for task, route in worker_profile_task_routes(selected).items()
    }
    app.conf.update(
        task_routes=routes,
        task_queues=tuple(
            Queue(name, exchange=Exchange(name, type="direct"), routing_key=name) for name in names
        ),
        task_default_queue=names[0],
        task_create_missing_queues=False,
    )
