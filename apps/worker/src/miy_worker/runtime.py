from __future__ import annotations

import sys
from importlib.util import find_spec
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from miy_worker.settings import get_settings


def workspace_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pnpm-workspace.yaml").exists():
            return parent
    return current.parents[4]


def ensure_api_src_on_path() -> None:
    # Installed artifacts use their matching API wheel; dev keeps source fallback.
    if find_spec("miy_api") is not None:
        return
    api_src = workspace_root() / "apps" / "api" / "src"
    if str(api_src) not in sys.path:
        sys.path.insert(0, str(api_src))


def ensure_official_worker_src_on_path() -> None:
    """Use the installed owner wheel; source fallback is checkout-only."""
    if find_spec("miy_official_worker") is not None:
        return
    source = workspace_root() / "apps" / "official-suite" / "worker" / "src"
    if not (source / "miy_official_worker" / "__init__.py").is_file():
        raise RuntimeError("matching_official_worker_artifact_required")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def assert_llm_routing_control_plane_ready(*, settings) -> None:
    """Keep the existing worker's database startup contract across compositions."""
    if not settings.postgres_dsn.strip():
        raise RuntimeError("Worker PostgreSQL DSN is not configured.")
    engine = create_engine(settings.postgres_dsn, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            for statement in (
                "SELECT provider_id, provider_kind, credential_kind FROM ai_model_provider_configs LIMIT 1",
                "SELECT id FROM ai_model_catalog_entries LIMIT 1",
                "SELECT app_id, workload_id FROM ai_model_route_overrides LIMIT 1",
                "SELECT app_id, route_mode FROM ai_model_policy_defaults LIMIT 1",
            ):
                session.execute(text(statement)).all()
    except Exception as error:
        raise RuntimeError(
            "AI model control plane is unavailable. Run API migrations before starting the worker."
        ) from error
    finally:
        engine.dispose()


@lru_cache(maxsize=1)
def postgres_engine() -> Engine:
    settings = get_settings()
    options: dict[str, object] = {"pool_pre_ping": True}
    if not settings.postgres_dsn.startswith("sqlite"):
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            connect_args={
                "application_name": f"miy:{settings.env_profile}:worker"[:63],
            },
        )
    return create_engine(settings.postgres_dsn, **options)


def configure_database() -> None:
    ensure_api_src_on_path()
    from miy_api.core.db import configure_database_engine

    configure_database_engine(postgres_engine())


def reset_database_after_fork() -> None:
    # Replace the inherited pool without closing the parent's connections.
    # Session factories keep their binding to this Engine, including domain code.
    postgres_engine().dispose(close=False)


@lru_cache(maxsize=1)
def db_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=postgres_engine(), class_=Session)


def db_session() -> Session:
    return db_session_factory()()


@contextmanager
def db_session_scope() -> Iterator[Session]:
    session = db_session()
    try:
        yield session
    finally:
        session.close()


def minio_client():
    from minio import Minio

    settings = get_settings()
    parsed = urlparse(settings.minio_endpoint)
    secure = parsed.scheme == "https"
    host = parsed.netloc or parsed.path
    return Minio(
        host,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=secure,
    )
