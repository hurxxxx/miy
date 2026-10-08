"""Opt-in, one-operation first registration. No credentials enter Task projections."""

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import auth, registration_source, store
from .errors import ConsoleError
from .models import RegistrationIntent, Task, WebSession, now
from .storage import database_path, private_file

PREFIX = "/api/v1/independent-apps/bootstrap-authorizations"
CALLBACK = "/api/registration-authorizations/callback"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(Contract):
    app_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    origin: str = Field(max_length=300)
    runtime_profile: Literal["web-api-v1", "web-api-postgres-v1"]
    requested_permissions: list[
        Literal["identity:read", "data:read", "data:write", "files:read-selected"]
    ] = Field(max_length=4)


class Begin(Contract):
    origin: str = Field(max_length=300)

    @field_validator("origin")
    @classmethod
    def exact_origin(cls, value):
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or any(char.isspace() for char in value)
            or "\\" in value
            or (
                parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            )
        ):
            raise ValueError("Use an exact development origin")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        default = 443 if parsed.scheme == "https" else 80
        canonical = f"{parsed.scheme}://{host}" + (f":{port}" if port and port != default else "")
        if canonical != value:
            raise ValueError("Use a canonical development origin")
        return canonical


class Receipt(Contract):
    operation_id: UUID
    app_id: str
    installation_id: UUID
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime


class Exchange(Contract):
    schema_version: Literal[1]
    id: UUID
    request_id: UUID
    operation_id: UUID
    actor_user_id: UUID
    audience: str
    policy: Policy
    expires_at: datetime
    token: str = Field(pattern=r"^miyrg_[A-Za-z0-9_-]{43}$")

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if isinstance(value, bool):
            raise ValueError("Boolean is not a protocol version")
        return value


class Status(Contract):
    task_id: UUID
    operation_id: UUID
    enabled: bool
    authorization_origin: str | None
    authorization_state: Literal[
        "required", "pending", "exchanging", "ready", "failed", "expired", "other_session"
    ]
    state: Literal["unsubmitted", "unknown", "registered", "rejected"]
    expires_at: datetime | None
    policy: Policy | None
    receipt: Receipt | None
    failure_code: str | None
    source_revision: str | None


class AuthorizationStart(Contract):
    status: Status
    authorization_url: str


def configured(settings):
    if (
        not settings.registration_authorization_enabled
        or not settings.miy_api_origin
        or settings.miy_api_origin not in settings.sso_subjects
    ):
        raise ConsoleError("registration_unconfigured", 503)
    return (
        settings.miy_api_origin,
        settings.origin + settings.base_path,
        str(settings.sso_subjects[settings.miy_api_origin]),
    )


@contextmanager
def vault(settings):
    """Pin every directory without following links; only the private leaf is writable here."""
    parent = database_path(settings.database_url).parent
    path = parent / "registration-credentials"
    settings.require_allowed_paths(path)
    for source in [settings.workspace, settings.worktree_root, *settings.app_source_roots]:
        if path.is_relative_to(source) or source.is_relative_to(path):
            raise ConsoleError("registration_storage_invalid", 503)
    fd = os.open("/", os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parent.parts[1:]:
            child = os.open(part, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        try:
            os.mkdir(path.name, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open(path.name, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        os.close(fd)
        fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError()
        yield fd
    except (OSError, ValueError):
        raise ConsoleError("registration_storage_invalid", 503) from None
    finally:
        os.close(fd)


def secret(settings, request_id, kind, value=None, *, remove=False):
    name = str(UUID(request_id)) + "." + kind
    if kind not in ("verifier", "token"):
        raise ValueError("Unknown credential type")
    with vault(settings) as directory:
        path = Path(f"/proc/self/fd/{directory}") / name
        if remove:
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise ValueError()
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
            except FileNotFoundError:
                pass
            return None
        if value is not None:
            fd = private_file(path, exclusive=True)
        else:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError()
            if value is not None:
                encoded = value.encode("ascii")
                if len(encoded) > 2048 or os.write(fd, encoded) != len(encoded):
                    raise ValueError()
                os.fsync(fd)
                os.fsync(directory)
                return None
            data = os.read(fd, 2049)
            if not data or len(data) > 2048:
                raise ValueError()
            return data.decode("ascii")
        finally:
            os.close(fd)


def cleanup(settings, request_id):
    if request_id:
        for kind in ("verifier", "token"):
            try:
                secret(settings, request_id, kind, remove=True)
            except (ConsoleError, OSError, ValueError):
                # Never follow or delete a foreign replacement. Access remains fail-closed.
                pass


def require(db, task_id, *, session_hash=None, allow_other=False):
    task = db.get(Task, task_id)
    row = db.get(RegistrationIntent, task_id)
    if not task or not row or (task.context or {}).get("purpose") != "registration":
        raise ConsoleError("registration_denied", 403)
    session = db.get(WebSession, row.web_session_hash)
    if not allow_other and (
        not session
        or session.expires_at <= now()
        or (session_hash is not None and row.web_session_hash != session_hash)
    ):
        raise ConsoleError("registration_session_changed", 403)
    return task, row


def turn_owner(db, task, session_hash):
    if (task.context or {}).get("purpose") == "registration":
        if not session_hash:
            raise ConsoleError("registration_session_changed", 403)
        require(db, task.id, session_hash=session_hash)


def recovery_owner(db, task, session_hash):
    """Current owner may observe/reconcile an inactive thread without inheriting its grant."""
    if (task.context or {}).get("purpose") == "registration":
        require(db, task.id, allow_other=True)
        session = db.get(WebSession, session_hash) if session_hash else None
        if not session or session.expires_at <= now():
            raise ConsoleError("registration_session_changed", 403)


def recovery_gate(factory, task_id, token):
    with factory() as db:
        task = db.get(Task, task_id)
        if task:
            recovery_owner(db, task, auth.digest(token or ""))


def session_gate(factory, task_id, token):
    with factory() as db:
        task = db.get(Task, task_id)
        if task and (task.context or {}).get("purpose") == "registration":
            require(db, task_id, session_hash=auth.digest(token or ""))


def create(db, task, token):
    if (task.context or {}).get("purpose") == "registration":
        session_hash = auth.digest(token or "")
        session = db.get(WebSession, session_hash)
        if not session or session.expires_at <= now():
            raise ConsoleError("unauthenticated", 401)
        db.add(
            RegistrationIntent(
                task_id=task.id, operation_id=str(uuid4()), web_session_hash=session_hash
            )
        )


def status(settings, factory, task_id, token):
    with factory() as db:
        _, row = require(db, task_id, allow_other=True)
        own = row.web_session_hash == auth.digest(token or "")
        state = row.authorization_state if own else "other_session"
        if own and row.expires_at and row.expires_at <= now():
            state = "expired"
        if state == "ready":
            try:
                secret(settings, row.request_id, "token")
            except (ConsoleError, OSError, ValueError):
                state = "failed"
        return Status(
            task_id=task_id,
            operation_id=row.operation_id,
            enabled=settings.registration_authorization_enabled,
            authorization_origin=settings.miy_api_origin,
            authorization_state=state,
            state=row.state,
            expires_at=row.expires_at,
            policy=row.policy,
            receipt=row.receipt,
            failure_code=row.failure_code,
            source_revision=(row.request_body or {}).get("source_revision"),
        )


def policy_for(draft, origin):
    if draft.definition["ownership"] != "personal":
        raise ConsoleError("registration_denied", 403)
    return Policy(
        app_id=draft.app_id,
        origin=origin,
        runtime_profile=draft.definition["runtime_profile"],
        requested_permissions=sorted(draft.definition["requested_permissions"]),
    )


def begin(settings, factory, task_id, token, origin):
    issuer, audience, actor = configured(settings)
    with factory() as db:
        _, previous = require(db, task_id, allow_other=True)
        historical_policy = previous.policy if previous.request_body else None
    if historical_policy is None:
        draft = registration_source.snapshot(settings, factory, task_id)
        policy = policy_for(draft, origin).model_dump(mode="json")
    else:
        policy = historical_policy
    request_id, verifier = str(uuid4()), secrets.token_urlsafe(32)
    session_hash = auth.digest(token or "")
    old_request = None
    try:
        with factory.begin() as db:
            task, row = require(db, task_id, allow_other=True)
            session = db.get(WebSession, session_hash)
            if not session or session.expires_at <= now():
                raise ConsoleError("unauthenticated", 401)
            if task.status in (*store.ACTIVE, "uncertain"):
                raise ConsoleError("task_busy", 409)
            if row.request_body:
                # Reconnect restores authority for the exact historical request, not current edits.
                policy = row.policy
                if origin != policy["origin"]:
                    raise ConsoleError("registration_request_conflict", 409)
            old_request = row.request_id
            secret(settings, request_id, "verifier", verifier)
            row.request_id, row.web_session_hash = request_id, session_hash
            row.issuer, row.audience, row.actor_user_id = issuer, audience, actor
            row.policy, row.grant_id = policy, None
            row.authorization_state, row.failure_code = "pending", None
            row.expires_at = min(now() + timedelta(seconds=300), session.expires_at)
            row.updated_at = now()
            operation_id = row.operation_id
    except Exception:
        cleanup(settings, request_id)
        raise
    cleanup(settings, old_request)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    url = (
        issuer
        + "/apps/authorize-registration?"
        + urlencode(
            {
                "v": "1",
                "request_id": request_id,
                "operation_id": operation_id,
                "audience": audience,
                "code_challenge": challenge,
                "app_id": policy["app_id"],
                "development_origin": policy["origin"],
                "runtime_profile": policy["runtime_profile"],
                "requested_permissions": ",".join(policy["requested_permissions"]),
            }
        )
    )
    return AuthorizationStart(
        status=status(settings, factory, task_id, token), authorization_url=url
    )


async def api(settings, suffix, *, token=None, body=None, missing=False):
    issuer, _, _ = configured(settings)
    try:
        async with (
            asyncio.timeout(15),
            httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=httpx.Timeout(10, connect=3)
            ) as client,
        ):
            async with client.stream(
                "POST" if body is not None else "GET",
                issuer + PREFIX + suffix,
                headers={"Authorization": "Bearer " + token} if token else {},
                json=body,
            ) as response:
                if missing and response.status_code == 404:
                    return None
                if response.status_code not in (200, 201):
                    code = (
                        "registration_unavailable"
                        if response.status_code >= 500
                        else "registration_authorization_required"
                        if response.status_code in (401, 403)
                        else "registration_unsupported"
                        if response.status_code == 404
                        else "registration_rejected"
                    )
                    raise ConsoleError(
                        code, 503 if response.status_code >= 500 else response.status_code
                    )
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 65536:
                        raise ValueError()
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError()
                return parsed
    except (TimeoutError, httpx.HTTPError, ValueError, RecursionError):
        raise ConsoleError("registration_unavailable", 503) from None


async def callback(settings, factory, request_id, code):
    configured(settings)
    from sqlalchemy import select

    with factory.begin() as db:
        row = db.scalar(
            select(RegistrationIntent).where(RegistrationIntent.request_id == request_id)
        )
        if not row:
            raise ConsoleError("registration_callback_denied", 403)
        task, row = require(db, row.task_id)
        if (
            row.authorization_state != "pending"
            or not row.expires_at
            or row.expires_at <= now()
            or task.status in (*store.ACTIVE, "uncertain")
        ):
            raise ConsoleError("registration_callback_denied", 403)
        if (row.issuer, row.audience, row.actor_user_id) != configured(settings):
            raise ConsoleError("registration_callback_denied", 403)
        expected = (
            row.task_id,
            row.operation_id,
            row.web_session_hash,
            row.policy,
            task.runtime_generation,
            task.thread_id,
        )
        row.authorization_state = "exchanging"
    task_id, operation_id, session_hash, policy, generation, thread = expected
    try:
        verifier = secret(settings, request_id, "verifier")
        value = Exchange.model_validate(
            await api(
                settings,
                "/exchange",
                body={
                    "schema_version": 1,
                    "request_id": request_id,
                    "audience": settings.origin + settings.base_path,
                    "code": code,
                    "code_verifier": verifier,
                },
            )
        )
        if (
            (
                str(value.request_id),
                str(value.operation_id),
                str(value.actor_user_id),
                value.audience,
                value.policy.model_dump(mode="json"),
            )
            != (request_id, operation_id, configured(settings)[2], configured(settings)[1], policy)
            or value.expires_at.tzinfo is None
            or not now() < value.expires_at <= now() + timedelta(seconds=305)
        ):
            raise ValueError()
        with factory.begin() as db:
            task, row = require(db, task_id, session_hash=session_hash)
            if (
                row.request_id != request_id
                or row.authorization_state != "exchanging"
                or task.runtime_generation != generation
                or task.thread_id != thread
                or task.status in (*store.ACTIVE, "uncertain")
            ):
                raise ConsoleError("registration_callback_denied", 403)
            secret(settings, request_id, "token", value.token)
            row.grant_id, row.expires_at, row.authorization_state = (
                str(value.id),
                value.expires_at,
                "ready",
            )
            row.updated_at = now()
        secret(settings, request_id, "verifier", remove=True)
    except (ConsoleError, OSError, ValueError, ValidationError):
        cleanup(settings, request_id)
        with factory.begin() as db:
            row = db.get(RegistrationIntent, task_id)
            if row and row.request_id == request_id:
                row.authorization_state, row.failure_code = (
                    "failed",
                    "registration_reconnect_required",
                )
        # Exchange may have succeeded remotely. Never retry the code automatically.
    return task_id


def logout(settings, factory, session_hash):
    from sqlalchemy import select

    with factory.begin() as db:
        rows = list(
            db.scalars(
                select(RegistrationIntent).where(
                    RegistrationIntent.web_session_hash == session_hash
                )
            )
        )
        attempts = [row.request_id for row in rows]
        for row in rows:
            row.authorization_state = "failed"
            row.failure_code = "registration_session_changed"
    for request_id in attempts:
        cleanup(settings, request_id)


def install(app, owner):
    @app.get(
        "/api/tasks/{task_id}/registration", dependencies=[Depends(owner)], response_model=Status
    )
    def registration_status(task_id: UUID, request: Request):
        return status(
            app.state.settings, app.state.factory, str(task_id), request.cookies.get(auth.COOKIE)
        )

    @app.post(
        "/api/tasks/{task_id}/registration/authorize",
        dependencies=[Depends(owner)],
        response_model=AuthorizationStart,
    )
    def registration_authorize(task_id: UUID, body: Begin, request: Request):
        return begin(
            app.state.settings,
            app.state.factory,
            str(task_id),
            request.cookies.get(auth.COOKIE),
            body.origin,
        )

    @app.post(
        "/api/tasks/{task_id}/registration/receipt",
        dependencies=[Depends(owner)],
        response_model=Status,
    )
    async def registration_receipt(task_id: UUID, request: Request):
        from .registration_tools import execute

        key = str(task_id)

        def check():
            session_gate(app.state.factory, key, request.cookies.get(auth.COOKIE))

        await execute(app.state.settings, app.state.factory, key, "status", check=check)
        return status(app.state.settings, app.state.factory, key, request.cookies.get(auth.COOKIE))

    @app.post(CALLBACK)
    async def registration_callback(request: Request):
        cfg = app.state.settings
        issuer, _, _ = configured(cfg)
        if (
            request.headers.get("origin") != issuer
            or request.headers.get("host", "").lower() != urlsplit(cfg.origin).netloc.lower()
            or request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            raise ConsoleError("registration_callback_denied", 403)
        raw = await request.body()
        try:
            if len(raw) > 4096:
                raise ValueError()
            values = parse_qs(raw.decode("ascii"), strict_parsing=True, max_num_fields=2)
            if set(values) != {"request_id", "code"} or any(len(v) != 1 for v in values.values()):
                raise ValueError()
            request_id = str(UUID(values["request_id"][0]))
            code = values["code"][0]
            if not re.fullmatch(r"miyrc_[A-Za-z0-9_-]{43}", code):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ConsoleError("registration_callback_denied", 403) from None
        task_id = await callback(cfg, app.state.factory, request_id, code)
        return RedirectResponse(cfg.base_path + "/?task=" + task_id, status_code=303)
