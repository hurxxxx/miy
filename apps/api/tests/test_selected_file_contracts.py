from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import traceback
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import SecretStr, ValidationError
import pytest
from starlette.requests import Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from miy_api.app import localized_http_exception_handler
from miy_api.core.settings import Settings
from miy_api.core.db import get_db_session
from miy_api.domains.independent_apps import file_api, file_signing
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput
from miy_api.domains.independent_apps.contracts import AppDefinition, InstallationInput
from miy_api.domains.independent_apps.file_contracts import FileSelectionContext
from miy_api.domains.independent_apps.owner_preview_contracts import OwnerPreviewPatch
from miy_api.domains.independent_apps.registration_contracts import RegistrationPolicy


def _context():
    return {
        "schema_version": 1,
        "installation_id": str(uuid4()),
        "audience": "https://app.test",
        "selection_id": str(uuid4()),
    }


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setattr(
        file_signing,
        "get_settings",
        lambda: SimpleNamespace(
            independent_app_file_selection_signing_key=SecretStr(
                "9aB7cD6eF5gH4iJ3kL2mN1oP0qR8sT7u"
            ),
        ),
    )
    monkeypatch.setattr(file_signing, "time", SimpleNamespace(time=lambda: 100))
    return file_signing.FileRequestClaims(
        **_context(),
        session_key="a" * 64,
        generation=1,
        issued_at=100,
        expires=160,
    )


def test_two_signed_purposes_and_existing_opaque_values_cannot_substitute(signing):
    request = file_signing.sign(signing)
    assert file_signing.verify(request) == signing
    claims = file_signing.FileReadClaims(
        **signing.model_dump(exclude={"purpose", "expires"}),
        expires=220,
        file_id=uuid4(),
        version="b" * 64,
        grant_id=uuid4(),
    )
    read = file_signing.sign(claims)
    assert file_signing.verify(read, read=True) == claims
    for value, is_read in (
        (request, True),
        (read, False),
        ("root-bearer", False),
        ("abc.def", True),
        (request[:-1] + "!", False),
    ):
        with pytest.raises(HTTPException) as caught:
            file_signing.verify(value, read=is_read)
        assert caught.value.status_code == 403


@pytest.mark.parametrize(
    "changes",
    [
        {"expires": 100},
        {"expires": 161},
        {"issued_at": 101},
        {"expires": 99},
    ],
)
def test_signed_claim_time_is_checked_even_with_correct_signature(signing, changes):
    forged = signing.model_copy(update=changes)
    with pytest.raises(HTTPException) as caught:
        file_signing.verify(file_signing.sign(forged))
    assert caught.value.status_code == 403


@pytest.mark.parametrize(
    "key",
    [
        "short",
        "dev-" + "x" * 40,
        "example-" + "x" * 40,
        "placeholder-" + "x" * 40,
        "change-me-" + "x" * 40,
        " " + "x" * 40,
    ],
)
def test_new_signer_rejects_public_or_short_keys_in_all_environments(key):
    with pytest.raises(ValueError):
        Settings.validate_file_selection_key(SecretStr(key))
    assert Settings.validate_file_selection_key(SecretStr("")).get_secret_value() == ""


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 1.0},
        {"schema_version": 2},
        {"audience": "https://app.test/"},
        {"audience": "https://user@app.test"},
        {"extra": "unknown"},
    ],
)
def test_public_context_rejects_ambiguous_or_future_shape(change):
    with pytest.raises(ValidationError):
        FileSelectionContext.model_validate(_context() | change)


def test_all_core_permission_contracts_accept_four_and_old_profile_stays_valid():
    permissions = ["identity:read", "data:read", "data:write", "files:read-selected"]
    definition = {
        "app_id": "four-permissions",
        "display": {"name": "Four"},
        "source": {"repository": "https://example.test/four.git"},
        "runtime_profile": "web-api-postgres-v1",
        "requested_permissions": permissions,
    }
    assert AppDefinition.model_validate(definition).requested_permissions == permissions
    assert AppDefinition.model_validate(
        definition
        | {
            "runtime_profile": "web-api-v1",
            "requested_permissions": ["identity:read", "files:read-selected"],
        }
    )
    assert InstallationInput(
        environment="development", origin="https://app.test", granted_permissions=permissions
    )
    assert BootstrapInput(
        operation_id=uuid4(),
        definition=definition,
        origin="https://app.test",
        source_revision="a" * 40,
        granted_permissions=permissions,
    )
    assert RegistrationPolicy(
        app_id="four-permissions",
        origin="https://app.test",
        runtime_profile="web-api-postgres-v1",
        requested_permissions=permissions,
    )
    assert OwnerPreviewPatch(
        expected_generation=1,
        expected_definition_digest="sha256:" + "a" * 64,
        expected_source_revision="a" * 40,
        enabled=True,
        granted_permissions=permissions,
    )
    with pytest.raises(ValidationError):
        AppDefinition.model_validate(
            definition | {"requested_permissions": permissions + ["identity:read"]}
        )


def test_body_deadline_and_oversize_use_bounded_request_before_json(monkeypatch):
    monkeypatch.setattr(file_api, "BODY_SECONDS", 0.02)
    invoked = []

    async def endpoint(data: FileSelectionContext):
        invoked.append(data)
        return {"ok": True}

    route = file_api._BoundedFileRoute("/synthetic", endpoint, methods=["POST"])
    handler = route.get_route_handler()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/synthetic",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "server": ("test", 80),
        "scheme": "http",
    }

    async def exercise():
        stopped = asyncio.Event()
        calls = 0

        async def slow():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"type": "http.request", "body": b'{"schema_version":', "more_body": True}
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with pytest.raises(HTTPException) as timeout:
            await handler(Request(scope, slow))
        assert timeout.value.status_code == 408
        assert stopped.is_set() and calls == 2 and not invoked
        parts = iter([b" " * 4096, b" " * 4096, b" "])

        async def large():
            return {"type": "http.request", "body": next(parts), "more_body": True}

        with pytest.raises(HTTPException) as oversized:
            await handler(Request(scope, large))
        assert oversized.value.status_code == 413 and not invoked

        async def invalid():
            return {
                "type": "http.request",
                "body": b'{"secret":"SYNTHETIC-DO-NOT-ECHO"}',
                "more_body": False,
            }

        async with AsyncExitStack() as stack:
            current_scope = scope | {
                "fastapi_middleware_astack": stack,
                "fastapi_inner_astack": stack,
                "fastapi_function_astack": stack,
            }
            with pytest.raises(HTTPException) as validation:
                await handler(Request(current_scope, invalid))
        assert validation.value.status_code == 422
        assert "SYNTHETIC-DO-NOT-ECHO" not in str(validation.value)
        assert "SYNTHETIC-DO-NOT-ECHO" not in "".join(traceback.format_exception(validation.value))
        assert not invoked

    asyncio.run(exercise())


def test_response_buffer_slots_include_slow_client_send_and_release_on_cancel(monkeypatch):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.include_router(file_api.router)
    app.dependency_overrides[get_db_session] = lambda: object()

    async def content(*args, **kwargs):
        return b"data", SimpleNamespace(name="synthetic")

    monkeypatch.setattr(file_api.files, "content", content)

    async def exercise():
        body_count = 0
        all_bodies = asyncio.Event()
        gate = asyncio.Event()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": "/_files/content",
            "raw_path": b"/_files/content",
            "query_string": f"installation_id={uuid4()}&audience=https://app.test".encode(),
            "headers": [
                (b"authorization", b"Bearer synthetic"),
                (b"x-miy-selected-file", b"synthetic"),
            ],
            "server": ("test", 80),
            "client": ("test", 80),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def slow_send(message):
            nonlocal body_count
            if message["type"] == "http.response.body":
                body_count += 1
                if body_count == 4:
                    all_bodies.set()
                await gate.wait()

        tasks = [asyncio.create_task(app(scope.copy(), receive, slow_send)) for _ in range(4)]
        try:
            await asyncio.wait_for(all_bodies.wait(), 2)
            assert file_api._content_responses == 4
            messages = []

            async def send(message):
                messages.append(message)

            await app(scope.copy(), receive, send)
            assert (
                next(item for item in messages if item["type"] == "http.response.start")["status"]
                == 503
            )
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            assert file_api._content_responses == 3
            gate.set()
            await asyncio.gather(*tasks[1:])
            assert file_api._content_responses == 0
        finally:
            gate.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["send_error", "deadline"])
def test_response_buffer_slot_releases_after_send_failure_without_second_response(
    failure, monkeypatch
):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.include_router(file_api.router)
    app.dependency_overrides[get_db_session] = lambda: object()
    monkeypatch.setattr(file_api, "CONTENT_RESPONSE_SECONDS", 0.05)

    async def content(*args, **kwargs):
        return b"data", SimpleNamespace(name="synthetic")

    monkeypatch.setattr(file_api.files, "content", content)

    async def exercise():
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": "/_files/content",
            "raw_path": b"/_files/content",
            "query_string": f"installation_id={uuid4()}&audience=https://app.test".encode(),
            "headers": [
                (b"authorization", b"Bearer synthetic"),
                (b"x-miy-selected-file", b"synthetic"),
            ],
            "server": ("test", 80),
            "client": ("test", 80),
            "scheme": "http",
        }
        messages = []
        stopped = asyncio.Event()

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def failing_send(message):
            messages.append(message)
            if message["type"] == "http.response.body":
                assert file_api._content_responses == 1
                if failure == "send_error":
                    raise OSError("synthetic disconnect")
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        with pytest.raises(OSError if failure == "send_error" else TimeoutError):
            await app(scope.copy(), receive, failing_send)
        assert [m["type"] for m in messages] == ["http.response.start", "http.response.body"]
        assert messages[0]["status"] == 200
        assert file_api._content_responses == 0
        if failure == "deadline":
            assert stopped.is_set()
        messages.clear()

        async def send(message):
            messages.append(message)

        await app(scope.copy(), receive, send)
        assert messages[0]["status"] == 200 and messages[1]["body"] == b"data"
        assert file_api._content_responses == 0

    asyncio.run(exercise())


@pytest.mark.parametrize("blocked_at", ["handler", "headers_send"])
def test_response_deadline_rejects_bytes_after_synchronous_event_loop_stall(
    blocked_at, monkeypatch
):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.include_router(file_api.router)
    app.dependency_overrides[get_db_session] = lambda: object()
    monkeypatch.setattr(file_api, "CONTENT_RESPONSE_SECONDS", 0.1)

    async def content(*args, **kwargs):
        if blocked_at == "handler":
            # Simulates synchronous SQL work that asyncio.timeout cannot preempt.
            time.sleep(0.15)
        return b"PRIVATE-SYNTHETIC-BYTES", SimpleNamespace(name="synthetic")

    monkeypatch.setattr(file_api.files, "content", content)

    async def exercise():
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": "/_files/content",
            "raw_path": b"/_files/content",
            "query_string": f"installation_id={uuid4()}&audience=https://app.test".encode(),
            "headers": [
                (b"authorization", b"Bearer synthetic"),
                (b"x-miy-selected-file", b"synthetic"),
            ],
            "server": ("test", 80),
            "client": ("test", 80),
            "scheme": "http",
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)
            if blocked_at == "headers_send" and message["type"] == "http.response.start":
                time.sleep(0.15)

        with pytest.raises(TimeoutError):
            await app(scope, receive, send)
        assert all(item.get("body") != b"PRIVATE-SYNTHETIC-BYTES" for item in messages)
        if blocked_at == "handler":
            assert all(item.get("status") != 200 for item in messages)
        else:
            assert len(messages) == 1 and messages[0]["status"] == 200
        assert file_api._content_responses == 0

    asyncio.run(exercise())
