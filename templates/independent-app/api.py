"""App-owned API. Portal credentials and product-database access are never needed."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from business import install


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIY_APP_", extra="ignore")
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    installation_id: str = Field(min_length=1, max_length=36)
    origin: str
    platform_origin: str
    # Set only by the core executor. The internal gateway exposes exchange and
    # identity verification; it does not grant general platform/network access.
    platform_api_origin: str | None = None

    @field_validator("platform_api_origin")
    @classmethod
    def api_origin(cls, value: str | None) -> str | None:
        if value is None or value == "http://miy-platform-gateway:8081":
            return value
        return cls.exact_origin(value)

    @field_validator("origin", "platform_origin")
    @classmethod
    def exact_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(char.isspace() for char in value)
            or (
                parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise ValueError("Use an exact HTTPS origin or loopback development origin")
        return value


settings = Settings()
if settings.origin == settings.platform_origin:
    raise ValueError("The app and platform must use different origins")


def no_store(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


app = FastAPI(dependencies=[Depends(no_store)])


class Exchange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: str = Field(min_length=1, max_length=36)
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{40,128}$")
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


async def platform_request(
    method: str, path: str, *, success_codes=(200,), max_bytes=32768, **kwargs
):
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                method,
                (settings.platform_api_origin or settings.platform_origin)
                + "/api/v1/independent-apps"
                + path,
                **kwargs,
            ) as response:
                if response.status_code not in success_codes:
                    raise HTTPException(
                        status_code=response.status_code
                        if response.status_code in {401, 403, 404, 409, 422}
                        else 503,
                        detail="App authorization unavailable",
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise HTTPException(status_code=503, detail="Invalid platform response")
                return json.loads(content) if response.status_code != 204 else None
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="App authorization unavailable") from exc


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {
        "app_id": settings.id,
        "installation_id": settings.installation_id,
        "platform_origin": settings.platform_origin,
    }


@app.post("/api/session/exchange")
async def exchange(data: Exchange, request: Request):
    if (
        request.headers.get("origin") != settings.origin
        or data.installation_id != settings.installation_id
    ):
        raise HTTPException(status_code=403, detail="Invalid app installation")
    return await platform_request(
        "POST", "/exchange", headers={"Origin": settings.origin}, json=data.model_dump()
    )


@app.get("/api/me")
async def me(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 200:
        raise HTTPException(status_code=401, detail="App session required")
    # Every protected business endpoint must recheck this authority and then its own
    # resource ACL. App admission alone is not permission to read another user's data.
    return await platform_request(
        "GET",
        "/session",
        headers={"Authorization": authorization},
        params={
            "installation_id": settings.installation_id,
            "audience": settings.origin,
        },
    )


FILE_MAX_BYTES = 10 * 1024 * 1024
FILE_REQUEST_MAX_BYTES = 8192
FILE_TOTAL_SECONDS = 15


class FileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    selection_id: UUID

    @field_validator("schema_version", mode="before")
    @classmethod
    def version(cls, value):
        if isinstance(value, bool):
            raise ValueError("Invalid version")
        return value


class FileSelectionProof(FileSelection):
    installation_id: UUID
    audience: str
    selection_request: str = Field(pattern=r"^[!-~]{1,4096}$")
    expires_at: datetime
    max_bytes: Literal[10485760]

    @field_validator("expires_at", mode="before")
    @classmethod
    def utc_expiry(cls, value):
        if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
            raise ValueError("Invalid expiry")
        return value


def file_bearer(authorization: str | None) -> str:
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not 8 <= len(authorization) <= 200
        or not all(33 <= ord(char) <= 126 for char in authorization[7:])
    ):
        raise HTTPException(status_code=401, detail="App session required")
    return authorization


@app.post("/api/platform-files/selection-request")
async def file_selection_request(
    request: Request, authorization: str | None = Header(default=None)
):
    bearer = file_bearer(authorization)
    if request.query_params:
        raise HTTPException(status_code=422, detail="Invalid file request")
    try:
        async with asyncio.timeout(FILE_TOTAL_SECONDS):
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > FILE_REQUEST_MAX_BYTES:
                    raise HTTPException(status_code=413, detail="File request too large")
                body.extend(chunk)
            try:
                selection = FileSelection.model_validate_json(body)
            except ValidationError:
                raise HTTPException(status_code=422, detail="Invalid file request") from None
            result = await platform_request(
                "POST",
                "/_files/selection-request",
                headers={"Authorization": bearer},
                json={
                    **selection.model_dump(mode="json"),
                    "installation_id": settings.installation_id,
                    "audience": settings.origin,
                },
            )
            proof = FileSelectionProof.model_validate(result)
            if (
                str(proof.installation_id) != settings.installation_id
                or proof.audience != settings.origin
                or proof.selection_id != selection.selection_id
                or proof.expires_at.utcoffset() is None
                or proof.expires_at <= datetime.now(timezone.utc)
            ):
                raise ValueError("Invalid file selection context")
            return proof.model_dump(mode="json")
    except (TimeoutError, ValueError):
        raise HTTPException(status_code=503, detail="File selection unavailable") from None


@app.get("/api/platform-files/content")
async def selected_file_content(
    request: Request,
    authorization: str | None = Header(default=None),
    x_miy_selected_file: str | None = Header(default=None),
):
    bearer = file_bearer(authorization)
    if request.query_params or not re.fullmatch(r"[!-~]{1,4096}", x_miy_selected_file or ""):
        raise HTTPException(status_code=422, detail="Invalid selected file")
    # This whole-body reader is deliberately separate from the small JSON proxy.
    # No caller-controlled URL, file ID, cookies or platform credentials are forwarded.
    try:
        async with asyncio.timeout(FILE_TOTAL_SECONDS):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(12, connect=3), follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "GET",
                    (settings.platform_api_origin or settings.platform_origin)
                    + "/api/v1/independent-apps/_files/content",
                    headers={
                        "Authorization": bearer,
                        "X-MIY-Selected-File": x_miy_selected_file,
                        "Accept-Encoding": "identity",
                    },
                    params={
                        "installation_id": settings.installation_id,
                        "audience": settings.origin,
                    },
                ) as response:
                    if response.status_code != 200:
                        raise HTTPException(
                            status_code=response.status_code
                            if response.status_code in {401, 403, 413, 422}
                            else 503,
                            detail="Selected file unavailable",
                        )
                    length = response.headers.get("Content-Length", "")
                    if (
                        not re.fullmatch(r"[0-9]{1,8}", length)
                        or int(length) > FILE_MAX_BYTES
                        or response.headers.get("Content-Type") != "application/octet-stream"
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                        or "Content-Range" in response.headers
                    ):
                        raise ValueError("Invalid selected file response")
                    content = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(content) + len(chunk) > int(length):
                            raise ValueError("Invalid selected file size")
                        content.extend(chunk)
                    if len(content) != int(length):
                        raise ValueError("Incomplete selected file")
                    return Response(
                        bytes(content),
                        media_type="application/octet-stream",
                        headers={
                            "Content-Length": str(len(content)),
                            "Content-Disposition": 'attachment; filename="selected-file"',
                            "Cache-Control": "private, no-store",
                            "X-Content-Type-Options": "nosniff",
                            "Referrer-Policy": "no-referrer",
                        },
                    )
    except (httpx.HTTPError, TimeoutError, ValueError):
        raise HTTPException(status_code=503, detail="Selected file unavailable") from None


# App-owned business routes are installed before the static UI fallback.
install(app, settings, platform_request)

dist = Path(__file__).resolve().parent / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
