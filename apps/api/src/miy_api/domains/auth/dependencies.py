from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

from anyio import CapacityLimiter, to_thread
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.core.i18n import localized_http_exception
from miy_api.core.settings import get_settings
from miy_api.domains.auth.access import load_user_graph, resolve_system_roles
from miy_api.domains.auth.models import AuthSession, User
from miy_api.domains.auth.security import hash_token

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession
    system_roles: frozenset[str]
    impersonator_user_id: str | None = None


def resolve_auth_context_from_token(
    db: Session,
    token: str,
    *,
    update_last_seen: bool = True,
    allow_password_change: bool = False,
) -> AuthContext:
    now = datetime.now(UTC).replace(tzinfo=None)
    token_hash = hash_token(token)
    auth_session = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .execution_options(populate_existing=True)
    )
    return _resolve_session_context(
        db,
        auth_session,
        now=now,
        update_last_seen=update_last_seen,
        allow_password_change=allow_password_change,
    )


def resolve_auth_context_from_session_id(db: Session, session_id: str) -> AuthContext:
    """Core-only bridge after a delegated credential has been authenticated.

    A session ID is not a credential. Never expose this resolver as an HTTP
    authentication mechanism. It reuses current user/role checks without the
    legacy login session's last-seen write or transaction commit.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    auth_session = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .execution_options(populate_existing=True)
    )
    return _resolve_session_context(
        db,
        auth_session,
        now=now,
        update_last_seen=False,
        allow_password_change=False,
    )


def _resolve_session_context(
    db: Session,
    auth_session: AuthSession | None,
    *,
    now: datetime,
    update_last_seen: bool,
    allow_password_change: bool,
) -> AuthContext:
    if auth_session is None:
        raise localized_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth.session_invalid_or_expired",
        )

    user = load_user_graph(db, auth_session.user_id)
    if user is None:
        raise localized_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth.user_not_found",
        )
    if user.status != "active" or user.login_blocked:
        raise localized_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            code="auth.user_inactive",
        )

    if user.must_change_password and not allow_password_change:
        raise localized_http_exception(status_code=403, code="auth.password_change_required")

    if auth_session.impersonator_user_id:
        impersonator = load_user_graph(db, auth_session.impersonator_user_id)
        if (
            impersonator is None
            or impersonator.status != "active"
            or impersonator.login_blocked
            or "platform_admin" not in resolve_system_roles(db, impersonator)
        ):
            raise localized_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="auth.session_invalid_or_expired",
            )

    if update_last_seen:
        auth_session.last_seen_at = now
        db.add(auth_session)
        db.commit()
        db.refresh(auth_session)

    if auth_session.impersonator_user_id:
        db.info["impersonator_user_id"] = auth_session.impersonator_user_id
        db.info["impersonated_user_id"] = auth_session.user_id
        db.info["impersonation_session_id"] = auth_session.id
    else:
        db.info.pop("impersonator_user_id", None)
        db.info.pop("impersonated_user_id", None)
        db.info.pop("impersonation_session_id", None)
    return AuthContext(
        user=user,
        session=auth_session,
        system_roles=frozenset(resolve_system_roles(db, user)),
        impersonator_user_id=auth_session.impersonator_user_id,
    )


async def require_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db_session),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise localized_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="auth.required",
        )
    settings = get_settings()
    # Pool checkout can block. Keep authentication waiters off the default
    # thread limiter, which must remain available to finish requests already
    # holding connections. Scope this separate budget to the ASGI application.
    limiter = getattr(request.app.state, "auth_db_limiter", None)
    if limiter is None:
        limiter = CapacityLimiter(settings.db_pool_size + settings.db_max_overflow)
        request.app.state.auth_db_limiter = limiter
    context = await to_thread.run_sync(
        partial(
            resolve_auth_context_from_token,
            db,
            credentials.credentials,
            allow_password_change=(request.method, request.url.path)
            in {
                ("GET", f"{settings.api_prefix}/auth/me"),
                ("POST", f"{settings.api_prefix}/auth/change-password"),
                ("POST", f"{settings.api_prefix}/auth/logout"),
            },
        ),
        limiter=limiter,
    )
    request.state.auth_context = context
    return context


def require_current_user(context: AuthContext = Depends(require_auth_context)) -> User:
    return context.user


def require_any_system_role(*roles: str):
    def dependency(context: AuthContext = Depends(require_auth_context)) -> AuthContext:
        role_set = set(context.system_roles)
        if not any(role in role_set for role in roles):
            raise localized_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                code="auth.system_role_required",
                roles=", ".join(roles),
            )
        return context

    return dependency


PERMISSION_ROLE_MAP = {
    "admin.access": (("platform_admin",)),
    "user.read": (("platform_admin",)),
    "user.write": (("platform_admin",)),
    "organization.read": (("platform_admin",)),
    "organization.write": (("platform_admin",)),
    "platform_api_key.read": (("platform_admin",)),
    "platform_api_key.write": (("platform_admin",)),
    "platform_api_key.reveal": (("platform_admin",)),
    "audit.read": (("platform_admin",)),
    "session.revoke": (("platform_admin",)),
}


def require_permission(permission: str):
    roles = PERMISSION_ROLE_MAP.get(permission)
    if roles is None:
        raise ValueError(f"Unsupported platform permission: {permission}")
    return require_any_system_role(*roles)


def require_admin_context(
    context: AuthContext = Depends(require_any_system_role("platform_admin")),
) -> AuthContext:
    return context
