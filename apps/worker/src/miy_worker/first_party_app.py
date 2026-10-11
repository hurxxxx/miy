"""Explicit owned consumers and one shared Beat using native Celery lifecycle.

The trusted first-party services reuse current authority/storage transactions.
This is distinct from the inactive delegated Source-only artifact. Deployment
must retire legacy consumers and retain exactly one Beat before changing routes.
"""

from celery import Celery
from celery.signals import celeryd_init, worker_process_init

from miy_worker.runtime import (
    assert_llm_routing_control_plane_ready,
    configure_database,
    ensure_api_src_on_path,
    reset_database_after_fork,
)
from miy_worker.settings import get_settings
from miy_worker.task_binding import assert_profile_available, bind_task_app
from miy_worker.task_catalog import legacy_beat_schedule, task_modules

ensure_api_src_on_path()

from miy_api.core.first_party_worker_routing import (  # noqa: E402
    configure_first_party_celery_routes,
)
from miy_api.core.logging_security import install_sensitive_http_logging_guard  # noqa: E402
from miy_api.core.model_registry import import_all_models  # noqa: E402
from miy_api.core.telemetry import bootstrap_telemetry  # noqa: E402
from miy_api.core.worker_queue_contract import worker_profile, worker_profile_task_names  # noqa: E402
from miy_api.core.worker_task_publisher import configure_first_party_worker_routing  # noqa: E402
from miy_api.domains.official_apps.first_party_runtime import require_first_party_database  # noqa: E402
from miy_api.platform_extensions import initialize_platform_extensions  # noqa: E402


def _separate_beat_required(*_args, **_kwargs):
    raise RuntimeError("first_party_beat_requires_single_owner")


def _consumer_refused(*_args, **_kwargs):
    raise RuntimeError("first_party_beat_cannot_consume")


class FirstPartyConsumerApp(Celery):
    Beat = _separate_beat_required

    def Worker(self, *args, **options):
        # Celery signals log receiver exceptions instead of refusing startup.
        # Enforce ownership before constructing its native worker/consumer.
        requested = options.get("queues")
        if isinstance(requested, str):
            requested = requested.split(",")
        expected = self._first_party_owned_queues
        if frozenset(requested or expected) != expected:
            raise RuntimeError("first_party_consumer_queue_mismatch")
        if options.get("exclude_queues"):
            raise RuntimeError("first_party_consumer_queue_mismatch")
        if options.get("beat"):
            raise RuntimeError("first_party_beat_requires_single_owner")
        return super().Worker(*args, **options)

    def task(self, *args, **options):
        options["shared"] = False
        return super().task(*args, **options)


class FirstPartyBeatApp(Celery):
    Worker = _consumer_refused

    def task(self, *args, **options):
        options["shared"] = False
        return super().task(*args, **options)


def create_first_party_worker(*, profile: str, beat_only: bool = False) -> Celery:
    selected = worker_profile(profile)
    if (selected == "legacy") != beat_only:
        raise ValueError("first_party_worker_requires_owned_profile_or_single_beat")
    assert_profile_available(selected)
    settings = get_settings()
    install_sensitive_http_logging_guard()
    configure_database()
    import_all_models()
    require_first_party_database(composition="official" if selected != "platform" else "platform")
    if not beat_only:
        assert_llm_routing_control_plane_ready(settings=settings)
    configure_first_party_worker_routing()
    bootstrap_telemetry(
        service_name="miy-first-party-beat" if beat_only else f"miy-{selected}-worker",
        enabled=settings.otel_enabled,
        enable_console_exporter=settings.otel_console_exporter,
        enable_otlp_exporter=settings.otel_otlp_exporter_enabled,
        metrics_export_interval_ms=settings.otel_metrics_export_interval_ms,
    )
    initialize_platform_extensions(settings)

    app_type = FirstPartyBeatApp if beat_only else FirstPartyConsumerApp
    app = app_type(
        "miy_first_party_beat" if beat_only else f"miy_first_party_{selected}_worker",
        broker=settings.broker_url,
        backend=settings.result_backend,
        set_as_current=False,
        include=task_modules(selected),
    )
    bind_task_app(selected, app, first_party_compatibility=True)
    configure_first_party_celery_routes(app, profile=selected)
    app.conf.update(
        timezone="UTC",
        worker_concurrency=settings.concurrency,
        beat_schedule=legacy_beat_schedule() if beat_only else {},
        task_reject_on_worker_lost=True,
        worker_graceful_shutdown_timeout=3700,
    )
    if beat_only:
        from miy_worker.beat_health import install_beat_health

        install_beat_health()
    else:
        from miy_api.core.worker_queue_contract import worker_profile_queues

        expected_queues = frozenset(worker_profile_queues(selected))
        app._first_party_owned_queues = expected_queues

        @celeryd_init.connect(weak=False)
        def configure_owned_consumer(options=None, **_kwargs):
            requested = (options or {}).get("queues")
            if isinstance(requested, str):
                requested = requested.split(",")
            queues = frozenset(requested or expected_queues)
            if queues != expected_queues:
                raise RuntimeError("first_party_consumer_queue_mismatch")
            configure_database()
            require_first_party_database(
                composition="official" if selected == "official" else "platform"
            )

        @worker_process_init.connect(weak=False)
        def reset_owned_database(**_kwargs):
            reset_database_after_fork()

    app.loader.import_default_modules()
    actual = {name for name in app.tasks if not name.startswith("celery.")}
    if actual != set(worker_profile_task_names(selected)):
        raise RuntimeError("first_party_worker_registration_mismatch")
    return app
