"""One Celery registration owner per process, without another execution loop.

Task modules retain their real functions/options. A split artifact selects its
app before importing them; ordinary imports retain the legacy default. Reusing
Python's cached task modules for a different app would silently lose or leak
registrations, so that combination is deliberately rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from celery import Celery

_profile: str | None = None
_app: Celery | None = None


def assert_profile_available(profile: str) -> None:
    if _profile is not None and _profile != profile:
        raise RuntimeError("worker_profile_process_conflict")


def bind_task_app(profile: str, app: Celery) -> None:
    global _profile, _app
    assert_profile_available(profile)
    if _app is not None and _app is not app:
        raise RuntimeError("worker_profile_process_conflict")
    _profile, _app = profile, app


def selected_profile() -> str:
    return _profile or "legacy"


def task_app(module_name: str) -> Celery:
    if _app is None:
        from miy_worker.celery_app import celery_app

        app = celery_app
    else:
        app = _app
    from miy_worker.task_catalog import task_modules

    if module_name not in task_modules(selected_profile()):
        raise RuntimeError("worker_task_module_not_owned")
    return app


def mail_task_time_limit() -> int:
    from miy_worker.settings import Settings, get_settings

    if selected_profile() == "legacy":
        return get_settings().mail_sync_processing_lease_seconds
    # Inactive artifact inspection must not read host credentials/.env. This is
    # the canonical default, not a configurable executable runtime profile.
    return Settings.model_fields["mail_sync_processing_lease_seconds"].default
