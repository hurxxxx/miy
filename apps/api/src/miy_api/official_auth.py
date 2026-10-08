"""Official HTTP composition adapter. Caller headers cannot select app scope."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from anyio import CancelScope, CapacityLimiter, create_task_group, to_thread
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from miy_api.core.app_contracts_generated import OFFICIAL_APP_IDS
from miy_api.core.db import get_db_session
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import AuthContext, bearer_scheme
from miy_api.domains.official_apps.auth import resolve_official_auth_context
from miy_api.domains.official_apps.authority_reader import (
    OfficialAuthorityReaderRefused,
    resolve_prepared_official_auth_context,
)


def owned_app_scope(logical_app_id: str | None):
    """Runs before auth on the selected router, including nested owned routers."""

    def set_scope(request: Request) -> None:
        if logical_app_id is None:
            # Suite services without a canonical app admission contract remain
            # closed. In particular, do not invent a caller-selected "core" app.
            raise localized_http_exception(status_code=403, code="auth.required")
        request.state.official_logical_app_id = logical_app_id

    return set_scope


async def require_official_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db_session),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise localized_http_exception(status_code=401, code="auth.required")
    logical_app_id = getattr(request.state, "official_logical_app_id", None)
    if not isinstance(logical_app_id, str):
        raise localized_http_exception(status_code=403, code="auth.required")
    limiter = getattr(request.app.state, "auth_db_limiter", None)
    if limiter is None:
        settings = get_settings()
        limiter = CapacityLimiter(settings.db_pool_size + settings.db_max_overflow)
        request.app.state.auth_db_limiter = limiter
    context = await to_thread.run_sync(
        partial(
            resolve_official_auth_context,
            db,
            credentials.credentials,
            logical_app_id=logical_app_id,
        ),
        limiter=limiter,
    )
    request.state.auth_context = context
    return context


async def _read_prepared_authority(
    session_factory: Callable[[], Session],
    token: str,
    *,
    logical_app_id: str,
    limiter: CapacityLimiter,
) -> AuthContext:
    context: AuthContext | None = None
    error: BaseException | None = None

    async def read_owned() -> None:
        nonlocal context, error
        # A raw host Task.cancel() must not cancel the thread's await Future.
        # The structured group joins this private child before releasing the
        # parent admission permit, including repeated host cancellation.
        with CancelScope(shield=True):
            try:
                context = await to_thread.run_sync(
                    partial(
                        resolve_prepared_official_auth_context,
                        session_factory,
                        token,
                        logical_app_id=logical_app_id,
                    ),
                    limiter=CapacityLimiter(1),
                    abandon_on_cancel=False,
                )
            except BaseException as exc:
                # Preserve the original policy/control/cancellation type rather
                # than exposing an ExceptionGroup to the HTTP adapter.
                error = exc

    async with limiter:
        async with create_task_group() as group:
            group.start_soon(read_owned)
    if error is not None:
        raise error
    if context is None:
        raise OfficialAuthorityReaderRefused("authority_read_failed")
    return context


def build_prepared_official_auth_dependency(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    """Explicit auth-only assembly; no Source factory, default fallback or activation.

    The budget belongs to the separate auth Engine's owner. It bounds executing
    reads per dependency, not HTTP waiters, other workers or an overall deadline.
    """
    if not callable(session_factory):
        raise ValueError("Prepared official auth requires a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared official auth requires a positive read budget")
    limiter: CapacityLimiter | None = None

    async def require_prepared_official_auth_context(
        request: HTTPConnection,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> AuthContext:
        nonlocal limiter
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise localized_http_exception(status_code=401, code="auth.required")
        logical_app_id = getattr(request.state, "official_logical_app_id", None)
        if not isinstance(logical_app_id, str) or logical_app_id not in OFFICIAL_APP_IDS:
            raise localized_http_exception(status_code=403, code="auth.required")
        if limiter is None:
            # Construct within the ASGI async context; never initialize settings
            # or borrow the business pool's limiter to size this auth-only pool.
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            context = await _read_prepared_authority(
                session_factory,
                credentials.credentials,
                logical_app_id=logical_app_id,
                limiter=limiter,
            )
        except (OfficialAuthorityReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None
        request.state.auth_context = context
        return context

    return require_prepared_official_auth_context
