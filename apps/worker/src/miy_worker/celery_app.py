from __future__ import annotations

import sys
from importlib.util import find_spec
from pathlib import Path

from celery import Celery

from miy_worker.task_binding import assert_profile_available, bind_task_app

from celery.signals import (
    after_setup_logger,
    after_setup_task_logger,
    celeryd_init,
    worker_process_init,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from miy_worker.beat_health import install_beat_health
from miy_worker.task_catalog import legacy_beat_schedule
from miy_worker.queue_contract import (
    assert_worker_queue_access,
    celery_task_routes,
    celery_worker_queue_argument,
    worker_bootstrap_group_requires_llm_routing,
)
from miy_worker.settings import get_settings
from miy_worker.runtime import configure_database, reset_database_after_fork


def _workspace_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pnpm-workspace.yaml").exists():
            return parent
    return current.parents[4]


def _ensure_api_src_on_path() -> None:
    # Installed artifacts use their matching API wheel; dev keeps source fallback.
    if find_spec("miy_api") is not None:
        return
    api_src = _workspace_root() / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))


_ensure_api_src_on_path()

from miy_api.core.logging_security import (  # noqa: E402
    install_sensitive_http_logging_guard,
)
from miy_api.core.telemetry import bootstrap_telemetry  # noqa: E402
from miy_api.platform_extensions import initialize_platform_extensions  # noqa: E402

assert_profile_available("legacy")
settings = get_settings()
install_sensitive_http_logging_guard()
install_beat_health()


@after_setup_logger.connect
@after_setup_task_logger.connect
def _restore_sensitive_http_logging_guard(**_kwargs) -> None:
    install_sensitive_http_logging_guard()


@celeryd_init.connect
def _configure_database_pools(**_kwargs) -> None:
    configure_database()


@worker_process_init.connect
def _reset_database_pool_after_fork(**_kwargs) -> None:
    reset_database_after_fork()


@celeryd_init.connect
def _guard_server_managed_queues(
    sender=None,
    instance=None,
    conf=None,
    options=None,
    **_kwargs,
) -> None:
    del sender, instance, conf
    worker_options = options if isinstance(options, dict) else {}
    requested_queues = worker_options.get("queues")
    if not requested_queues:
        requested_queues = (
            celery_worker_queue_argument()
            if settings.queue_group == "all"
            else celery_worker_queue_argument(settings.queue_group)
        )
    assert_worker_queue_access(
        queue_group=settings.queue_group,
        requested_queues=requested_queues,
        env_profile=settings.env_profile,
        root=_workspace_root(),
    )


# Keep telemetry bootstrapped before task modules import RAG metric wrappers.
bootstrap_telemetry(
    service_name="miy-worker",
    enabled=settings.otel_enabled,
    enable_console_exporter=settings.otel_console_exporter,
    enable_otlp_exporter=settings.otel_otlp_exporter_enabled,
    metrics_export_interval_ms=settings.otel_metrics_export_interval_ms,
)
initialize_platform_extensions(settings)


def _assert_llm_routing_control_plane_ready() -> None:
    if not settings.postgres_dsn.strip():
        raise RuntimeError("Worker PostgreSQL DSN is not configured.")

    engine = create_engine(settings.postgres_dsn, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            session.execute(
                text(
                    "SELECT provider_id, provider_kind, credential_kind FROM ai_model_provider_configs LIMIT 1"
                )
            ).all()
            session.execute(text("SELECT id FROM ai_model_catalog_entries LIMIT 1")).all()
            session.execute(
                text("SELECT app_id, workload_id FROM ai_model_route_overrides LIMIT 1")
            ).all()
            session.execute(
                text("SELECT app_id, route_mode FROM ai_model_policy_defaults LIMIT 1")
            ).all()
    except Exception as error:
        raise RuntimeError(
            "AI model control plane is unavailable. Run API migrations before starting the worker."
        ) from error
    finally:
        engine.dispose()


if worker_bootstrap_group_requires_llm_routing(settings.queue_group):
    _assert_llm_routing_control_plane_ready()

celery_app = Celery(
    "miy_worker",
    broker=settings.broker_url,
    backend=settings.result_backend,
)
bind_task_app("legacy", celery_app)
celery_app.autodiscover_tasks(["miy_worker.tasks"])
celery_app.conf.timezone = "UTC"
celery_app.conf.worker_concurrency = settings.concurrency

celery_app.conf.beat_schedule = legacy_beat_schedule()
celery_app.conf.task_routes = celery_task_routes()
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_graceful_shutdown_timeout = 3700
