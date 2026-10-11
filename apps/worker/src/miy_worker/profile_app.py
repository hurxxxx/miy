"""Inspectable split Celery artifacts; execution remains unconditionally closed."""

from __future__ import annotations

from functools import wraps

from celery import Celery
from kombu import Queue

from miy_worker.runtime import ensure_api_src_on_path
from miy_worker.task_binding import assert_profile_available, bind_task_app

ensure_api_src_on_path()

from miy_api.core.worker_queue_contract import (  # noqa: E402
    WorkerProfileUnavailable,
    worker_profile,
    worker_profile_modules,
    worker_profile_queues,
    worker_profile_task_names,
    worker_profile_task_routes,
)
from miy_worker.task_catalog import profile_beat_schedule  # noqa: E402


def _unavailable(*_args, **_kwargs):
    raise WorkerProfileUnavailable("worker_profile_not_activated")


class InactiveProfileApp(Celery):
    """No flag, supplied broker URL or Celery CLI option opens this profile."""

    send_task = _unavailable
    Worker = _unavailable
    Beat = _unavailable
    worker_main = _unavailable
    start = _unavailable
    connection = _unavailable
    connection_for_read = _unavailable
    connection_for_write = _unavailable

    def task(self, *args, **options):
        # Celery shared decorators otherwise populate later apps globally.
        options["shared"] = False

        def register(function):
            if (
                options.get("name") not in worker_profile_task_names(self.profile)
                and function.__module__ != "celery.app.builtins"
            ):
                raise ValueError("worker_task_not_owned")

            @wraps(function)
            def unavailable(*_args, **_kwargs):
                return _unavailable()

            return super(InactiveProfileApp, self).task(unavailable, **options)

        return register(args[0]) if args else register


def create_inactive_profile_app(profile: str) -> InactiveProfileApp:
    selected = worker_profile(profile)
    if selected == "legacy":
        raise ValueError("legacy_requires_existing_entrypoint")
    assert_profile_available(selected)
    app = InactiveProfileApp(
        f"miy_{selected}_worker",
        broker="memory://",
        backend="cache+memory://",
        set_as_current=False,
        include=worker_profile_modules(selected),
    )
    app.profile = selected
    bind_task_app(selected, app)
    queues = worker_profile_queues(selected)
    app.conf.update(
        timezone="UTC",
        task_default_queue=queues[0],
        task_queues=tuple(Queue(name) for name in queues),
        task_create_missing_queues=False,
        task_routes=worker_profile_task_routes(selected),
        beat_schedule=profile_beat_schedule(selected),
        task_reject_on_worker_lost=True,
        worker_graceful_shutdown_timeout=3700,
    )
    app.loader.import_default_modules()
    owned = set(worker_profile_task_names(selected))
    actual = {name for name in app.tasks if not name.startswith("celery.")}
    if actual != owned:
        raise RuntimeError("worker_profile_registration_mismatch")
    return app
