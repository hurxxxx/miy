"""API composition ownership, independent of business authorization and activation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from fastapi import APIRouter
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

ApiComposition = Literal["legacy", "platform", "official"]
RouterOwner = Literal["platform", "official"]


def require_composition(value: str) -> ApiComposition:
    if value not in ("legacy", "platform", "official"):
        raise ValueError("Unsupported API composition")
    return cast(ApiComposition, value)


@dataclass(frozen=True)
class RouterSpec:
    router: APIRouter
    protection: Literal["public", "protected"]
    position: int
    owner: RouterOwner
    source: str
    logical_app_id: str | None = None


class InactiveCompositionMiddleware:
    """New artifacts cannot become a second writer before cutover fencing exists.

    This is a closed transition boundary, not an authorization replacement. There
    is deliberately no environment flag or header that enables business traffic.
    """

    _inspection_paths = frozenset(
        {
            "/healthz",
            "/readyz",
            "/openapi.json",
            "/docs",
            "/redoc",
            "/docs/oauth2-redirect",
        }
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1013, "reason": "service_not_activated"})
            return
        if scope["type"] == "http" and not (
            scope["method"] in {"GET", "HEAD"} and scope["path"] in self._inspection_paths
        ):
            response = JSONResponse({"code": "service_not_activated"}, status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
