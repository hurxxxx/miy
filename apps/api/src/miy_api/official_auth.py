"""Official HTTP composition adapter. Caller headers cannot select app scope."""

from __future__ import annotations

from functools import partial

from anyio import CapacityLimiter, to_thread
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import AuthContext, bearer_scheme
from miy_api.domains.official_apps.auth import resolve_official_auth_context


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
