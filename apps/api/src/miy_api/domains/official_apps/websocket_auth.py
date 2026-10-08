"""Server-owned collaboration adapter over the prepared HTTPConnection callable."""

from fastapi import HTTPException, WebSocket
from fastapi.security import HTTPAuthorizationCredentials

from miy_api.core.i18n import LocalizedApiMessage
from miy_api.domains.auth.dependencies import AuthContext


async def resolve_prepared_official_ws_auth_context(
    websocket: WebSocket, *, token: str, logical_app_id: str
) -> AuthContext | None:
    """Use the exact server-built HTTP dependency; None selects legacy assembly only."""
    dependency = getattr(websocket.app.state, "prepared_official_auth_dependency", None)
    if dependency is None:
        return None
    websocket.state.official_logical_app_id = logical_app_id
    return await dependency(
        websocket, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )


def prepared_official_ws_close_choice(error: HTTPException) -> tuple[int, str] | None:
    if (
        error.status_code == 503
        and isinstance(error.detail, LocalizedApiMessage)
        and error.detail.code == "official_apps.authority_unavailable"
    ):
        return (1013, "official_authority_unavailable")
    return None
