from __future__ import annotations

from celery import Celery

from miy_api.core.worker_queue_contract import require_worker_profile_active

_first_party_routing = False
_legacy_publisher_created = False


def configure_first_party_worker_routing() -> None:
    """One startup-only shared queue contract, before any legacy publisher exists."""
    global _first_party_routing
    if _legacy_publisher_created and not _first_party_routing:
        raise RuntimeError("first_party_worker_routing_already_bound")
    _first_party_routing = True


def create_fail_fast_celery_publisher(
    app_name: str,
    *,
    broker: str,
    backend: str | None = None,
    ignore_result: bool = False,
    profile: str = "legacy",
) -> Celery:
    global _legacy_publisher_created
    # No broker object/connection exists before an inactive profile is rejected.
    # Existing producers keep legacy defaults and their current explicit queues.
    require_worker_profile_active(profile)
    if not _first_party_routing:
        _legacy_publisher_created = True
    celery_client = Celery(app_name, broker=broker, backend=backend)
    celery_client.conf.update(
        broker_connection_retry=False,
        broker_connection_retry_on_startup=False,
        broker_connection_max_retries=0,
        task_publish_retry=False,
        broker_transport_options={
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
            "retry_on_timeout": False,
        },
    )
    if ignore_result:
        celery_client.conf.update(
            result_backend=None,
            task_ignore_result=True,
            task_store_eager_result=False,
        )
    if _first_party_routing:
        from miy_api.core.first_party_worker_routing import configure_first_party_celery_routes

        configure_first_party_celery_routes(celery_client)
    return celery_client
