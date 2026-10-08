"""Selected Files routes, with app authority separate from host MIY authority."""

import asyncio
import time
from uuid import UUID
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import files, service
from miy_api.domains.independent_apps.file_contracts import (
    FileAuthorizeInput,
    FileCandidatesInput,
    FileCandidatesOut,
    FileSelectionContext,
    FileSelectionRequestOut,
    SelectedFileReadOut,
)

BODY_SECONDS = 5.0
MAX_CONTENT_RESPONSES = 4
CONTENT_RESPONSE_SECONDS = 20.0
_content_responses = 0


class _BoundedFileRoute(APIRoute):
    async def handle(self, scope, receive, send):
        global _content_responses
        if scope["type"] != "http" or scope["method"] != "GET":
            return await super().handle(scope, receive, send)
        # Keep the complete buffer budget until ASGI finishes sending the
        # response, not merely until upstream reading or authorization finishes.
        if _content_responses >= MAX_CONTENT_RESPONSES:
            service.fail("file_read_unavailable", 503)
        _content_responses += 1
        deadline = time.monotonic() + CONTENT_RESPONSE_SECONDS

        async def bounded_send(message):
            # Synchronous database work (or an ASGI sender) can block the event
            # loop past asyncio's deadline before its cancellation callback runs.
            # Recheck wall time before handing over headers or any body bytes.
            if time.monotonic() >= deadline:
                raise TimeoutError("Selected-file response deadline elapsed")
            await send(message)

        try:
            # A stalled ASGI sender cannot retain a complete buffer forever.
            # Timeout after response start propagates to cancel/close; this
            # wrapper never tries to write a second JSON response.
            async with asyncio.timeout(CONTENT_RESPONSE_SECONDS):
                return await super().handle(scope, receive, bounded_send)
        finally:
            _content_responses -= 1

    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == "POST":
                raw = bytearray()
                try:
                    async with asyncio.timeout(BODY_SECONDS):
                        async for chunk in request.stream():
                            if len(raw) + len(chunk) > 8192:
                                service.fail("file_request_invalid", 413)
                            raw.extend(chunk)
                except TimeoutError:
                    raise localized_http_exception(
                        status_code=408, code="independent_apps.file_request_invalid"
                    ) from None
                delivered = False

                async def receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(raw), "more_body": False}
                    return await request.receive()

                # Public Request/receive boundary preserves ordinary FastAPI
                # typed body/OpenAPI handling while bounding bytes before JSON.
                limited = Request(request.scope, receive=receive)
            else:
                limited = request
            try:
                return await original(limited)
            except RequestValidationError:
                raise localized_http_exception(
                    status_code=422, code="independent_apps.file_request_invalid"
                ) from None

        return bounded


router = APIRouter(prefix="/_files", tags=["independent-app-files"], route_class=_BoundedFileRoute)


def app_bearer(authorization: str | None = Header(default=None, max_length=200)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        service.fail("session_invalid", 401)
    return authorization.removeprefix("Bearer ")


@router.post("/selection-request", response_model=FileSelectionRequestOut)
def request_file_selection(
    data: FileSelectionContext,
    token: str = Depends(app_bearer),
    db: Session = Depends(get_db_session),
):
    try:
        return files.selection_request(db, data, token=token)
    except DBAPIError as error:
        files.database_error(db, error)
        raise


@router.post("/candidates", response_model=FileCandidatesOut)
def list_file_selection_candidates(
    data: FileCandidatesInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    try:
        return files.candidates(db, data, context)
    except DBAPIError as error:
        files.database_error(db, error)
        raise


@router.post("/authorize-selection", response_model=SelectedFileReadOut)
def authorize_selected_file(
    data: FileAuthorizeInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    try:
        return files.authorize(db, data, context)
    except DBAPIError as error:
        files.database_error(db, error)
        raise


class SelectedFileResponse(Response):
    media_type = "application/octet-stream"


@router.get("/content", response_class=SelectedFileResponse)
async def read_selected_file(
    installation_id: UUID,
    audience: str = Query(max_length=300),
    grant: str = Header(alias="X-MIY-Selected-File", min_length=1, max_length=4096),
    token: str = Depends(app_bearer),
    db: Session = Depends(get_db_session),
):
    try:
        body, descriptor = await files.content(
            db,
            token=token,
            grant=grant,
            installation_id=str(installation_id),
            audience=audience,
        )
    except DBAPIError as error:
        files.database_error(db, error, reading=True)
        raise
    return SelectedFileResponse(
        body,
        headers={
            "Content-Length": str(len(body)),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(descriptor.name, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
