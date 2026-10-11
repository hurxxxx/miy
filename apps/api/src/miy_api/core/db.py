from __future__ import annotations

import logging
import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from miy_api.core.i18n import localized_http_exception
from miy_api.core.model_registry import import_all_models
from miy_api.core.settings import WORKSPACE_ROOT, get_settings

logger = logging.getLogger(__name__)
_configured_engine: Engine | None = None


class Base(DeclarativeBase):
    pass


def _engine_options(database_url: str) -> dict[str, object]:
    settings = get_settings()
    options: dict[str, object] = {
        "pool_pre_ping": True,
    }
    if not database_url.startswith("sqlite"):
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
        )
    if database_url.startswith("postgresql"):
        options["connect_args"] = {
            "application_name": f"miy:{settings.env_profile or 'local'}:api"[:63],
        }
    return options


@lru_cache(maxsize=1)
def get_engine():
    if _configured_engine is not None:
        return _configured_engine
    settings = get_settings()
    return create_engine(settings.postgres_dsn, **_engine_options(settings.postgres_dsn))


def configure_database_engine(engine: Engine) -> None:
    """Bind an embedding runtime's engine before it starts accepting work.

    Worker-hosted domain services must share the worker's connection budget.
    This is a startup composition hook, not a per-request reconfiguration API.
    """
    global _configured_engine
    if get_engine.cache_info().currsize:
        previous = get_engine()
        if previous is not engine:
            previous.dispose()
    _configured_engine = engine
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    except DBAPIError as error:
        if not is_official_writer_guard_error(error):
            raise
        # The statement trigger aborts the transaction, including services that
        # commit internally. Roll it back before returning a retryable response.
        session.rollback()
        raise official_writer_unavailable() from None
    finally:
        session.close()


def official_writer_unavailable():
    """Stable public failure envelope shared by HTTP and Docs collaboration."""
    return localized_http_exception(
        status_code=503,
        code="official_apps.writer_unavailable",
        headers={"Retry-After": "5"},
    )


def is_official_writer_guard_error(error: Exception) -> bool:
    """Recognize only the migrated guard's exact diagnostic, never SQL/error text."""
    if not isinstance(error, DBAPIError):
        return False
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    diagnostic = getattr(original, "diag", None)
    return sqlstate == "55000" and getattr(diagnostic, "message_primary", None) in {
        "official_writer_fenced",
        "official_writer_control_missing",
    }


def _alembic_config():
    from alembic.config import Config

    ini_path = WORKSPACE_ROOT / "apps" / "api" / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", get_settings().postgres_dsn)
    return cfg


def run_migrations() -> None:
    """Apply all pending Alembic migrations against the configured database."""
    from alembic import command

    command.upgrade(_alembic_config(), "head")


def init_db() -> None:
    """Application startup database hook.

    Schema is owned by Alembic. Setting ``MIY_API_AUTO_MIGRATE=1`` runs
    ``alembic upgrade head`` at boot — convenient for local dev and test
    fixtures, but production deploys must run migrations explicitly from a
    release script and leave this flag unset.
    """
    from miy_api.domains.ai import approvals as ai_approvals  # noqa: F401
    from miy_api.domains.auth.access import (
        ensure_dev_login_seed_data,
        ensure_seed_data,
    )

    import_all_models()

    if os.environ.get("MIY_API_AUTO_MIGRATE", "").lower() in {"1", "true", "yes"}:
        run_migrations()

    engine = get_engine()
    with Session(engine) as session:
        if get_settings().seed_dev_login_account:
            ensure_dev_login_seed_data(session)
        else:
            ensure_seed_data(session)
