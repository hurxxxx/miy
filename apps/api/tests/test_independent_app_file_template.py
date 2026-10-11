"""The app proxy carries selected-file authority only to two fixed Core paths."""

import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.requests import Request
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
BEARER = {"Authorization": "Bearer synthetic-app-session"}
READ_HEADERS = {**BEARER, "X-MIY-Selected-File": "synthetic-selected-file-proof"}


@pytest.fixture
def file_app(monkeypatch):
    for key, value in {
        "MIY_APP_ID": "file-fixture",
        "MIY_APP_INSTALLATION_ID": str(uuid4()),
        "MIY_APP_ORIGIN": "https://app.test",
        "MIY_APP_PLATFORM_ORIGIN": "https://portal.test",
        "MIY_APP_PLATFORM_API_ORIGIN": "http://miy-platform-gateway:8081",
    }.items():
        monkeypatch.setenv(key, value)
    for name, filename in [("business", "business.py"), ("file_app", "api.py")]:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "templates/independent-app" / filename
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, name, module)
    return module


def upstream(monkeypatch, api, responder):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(responder), **kwargs)

    monkeypatch.setattr(api.httpx, "AsyncClient", client)
    return options


def proof(api, selection_id):
    return {
        "schema_version": 1,
        "installation_id": api.settings.installation_id,
        "audience": api.settings.origin,
        "selection_id": selection_id,
        "selection_request": "synthetic-selection-proof",
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
        "max_bytes": 10485760,
    }


def test_selection_proxy_adds_only_fixed_context_and_forwards_no_cookies(file_app, monkeypatch):
    api = file_app
    selection_id = str(uuid4())
    observed = []

    def respond(request):
        observed.append(request)
        return httpx.Response(200, json=proof(api, selection_id))

    options = upstream(monkeypatch, api, respond)
    with TestClient(api.app) as client:
        result = client.post(
            "/api/platform-files/selection-request",
            json={"schema_version": 1, "selection_id": selection_id},
            headers={**BEARER, "Cookie": "platform=never-forward", "X-Other": "never-forward"},
        )
    assert result.status_code == 200
    assert result.json()["selection_request"] == "synthetic-selection-proof"
    assert result.headers["Cache-Control"] == "private, no-store"
    assert len(observed) == 1
    request = observed[0]
    assert (
        str(request.url)
        == "http://miy-platform-gateway:8081/api/v1/independent-apps/_files/selection-request"
    )
    assert json.loads(request.content) == {
        "schema_version": 1,
        "selection_id": selection_id,
        "installation_id": api.settings.installation_id,
        "audience": api.settings.origin,
    }
    assert request.headers["authorization"] == BEARER["Authorization"]
    assert "cookie" not in request.headers and "x-other" not in request.headers
    assert options[0]["follow_redirects"] is False and options[0]["trust_env"] is False


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"schema_version": True, "selection_id": str(uuid4())}, 422),
        ({"schema_version": 1, "selection_id": "not-a-uuid"}, 422),
        ({"schema_version": 1, "selection_id": str(uuid4()), "audience": "https://evil.test"}, 422),
        ({"schema_version": 1, "selection_id": str(uuid4()), "pad": "x" * 8192}, 413),
    ],
)
def test_selection_input_is_bounded_and_cannot_choose_platform_identity(
    file_app, monkeypatch, body, expected
):
    upstream(monkeypatch, file_app, lambda _: pytest.fail("Rejected before network"))
    with TestClient(file_app.app) as client:
        assert (
            client.post(
                "/api/platform-files/selection-request", json=body, headers=BEARER
            ).status_code
            == expected
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"installation_id": str(uuid4())},
        {"audience": "https://other.test"},
        {"selection_id": str(uuid4())},
        {"max_bytes": 10485761},
        {"selection_request": "x" * 4097},
        {"selection_request": "secret\nvalue"},
        {"expires_at": "2020-01-01T00:00:00Z"},
        {"expires_at": "2099-01-01T00:00:00"},
        {"unknown": "not allowed"},
    ],
)
def test_selection_rejects_malformed_or_wrong_context_success(file_app, monkeypatch, changes):
    selection_id = str(uuid4())
    upstream(
        monkeypatch,
        file_app,
        lambda _: httpx.Response(200, json={**proof(file_app, selection_id), **changes}),
    )
    with TestClient(file_app.app) as client:
        response = client.post(
            "/api/platform-files/selection-request",
            json={"schema_version": 1, "selection_id": selection_id},
            headers=BEARER,
        )
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize("body", [b"", b"\x00binary\xff", b"x" * 10485760])
def test_content_has_exact_bytes_safe_headers_and_fixed_query(file_app, monkeypatch, body):
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Length": str(len(body)),
                "Content-Type": "application/octet-stream",
                "Content-Disposition": "inline; filename=untrusted.html",
                "Set-Cookie": "not-forwarded=yes",
            },
        )

    options = upstream(monkeypatch, file_app, respond)
    with TestClient(file_app.app) as client:
        response = client.get(
            "/api/platform-files/content", headers={**READ_HEADERS, "Cookie": "never-forward"}
        )
    assert response.status_code == 200 and response.content == body
    assert response.headers["Content-Length"] == str(len(body))
    assert response.headers["Content-Type"] == "application/octet-stream"
    assert response.headers["Content-Disposition"] == 'attachment; filename="selected-file"'
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "set-cookie" not in response.headers
    assert len(seen) == 1
    assert seen[0].url.path == "/api/v1/independent-apps/_files/content"
    assert seen[0].url.host == "miy-platform-gateway"
    assert dict(seen[0].url.params) == {
        "installation_id": file_app.settings.installation_id,
        "audience": "https://app.test",
    }
    assert seen[0].headers["X-MIY-Selected-File"] == READ_HEADERS["X-MIY-Selected-File"]
    assert seen[0].headers["Accept-Encoding"] == "identity" and "cookie" not in seen[0].headers
    assert options[0]["follow_redirects"] is False and options[0]["trust_env"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"Content-Length": "0"},
        {"Content-Length": "2"},
        {"Content-Length": "10485761"},
        {"Content-Length": "invalid"},
        {"Content-Length": ""},
        {"Content-Type": "text/html"},
        {"Content-Encoding": "br"},
        {"Content-Range": "bytes 0-0/1"},
    ],
)
def test_content_rejects_size_encoding_type_and_partial_responses(file_app, monkeypatch, changes):
    # Build a plain stream to avoid httpx eagerly decoding a deliberately wrong encoding.
    upstream(
        monkeypatch,
        file_app,
        lambda _: httpx.Response(
            200,
            stream=BytesStream([b"a"]),
            headers={
                "Content-Length": "1",
                "Content-Type": "application/octet-stream",
                **changes,
            },
        ),
    )
    with TestClient(file_app.app) as client:
        assert client.get("/api/platform-files/content", headers=READ_HEADERS).status_code == 503


@pytest.mark.parametrize(
    "status,expected",
    [(401, 401), (403, 403), (413, 413), (422, 422), (302, 503), (206, 503), (500, 503)],
)
def test_content_preserves_denial_but_not_upstream_details_or_redirects(
    file_app, monkeypatch, status, expected
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="internal path and credential",
            headers={"Location": "https://other.test/secret"},
        )

    upstream(monkeypatch, file_app, respond)
    with TestClient(file_app.app) as client:
        response = client.get("/api/platform-files/content", headers=READ_HEADERS)
    assert response.status_code == expected and len(calls) == 1
    assert "credential" not in response.text and "secret" not in response.text


class BytesStream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def test_total_deadline_closes_dribbling_upstream_without_partial_success(file_app, monkeypatch):
    stream = BytesStream([b"a"] * 100, delay=0.005)
    upstream(
        monkeypatch,
        file_app,
        lambda _: httpx.Response(
            200,
            stream=stream,
            headers={"Content-Length": "100", "Content-Type": "application/octet-stream"},
        ),
    )
    monkeypatch.setattr(file_app, "FILE_TOTAL_SECONDS", 0.025)
    with TestClient(file_app.app) as client:
        response = client.get("/api/platform-files/content", headers=READ_HEADERS)
    assert response.status_code == 503 and stream.closed
    assert response.content != b"a" * 100


def test_cancelled_app_request_closes_the_upstream_stream(file_app, monkeypatch):
    async def scenario():
        entered = asyncio.Event()

        class PendingStream(BytesStream):
            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b"unused"

        stream = PendingStream([])
        upstream(
            monkeypatch,
            file_app,
            lambda _: httpx.Response(
                200,
                stream=stream,
                headers={"Content-Length": "1", "Content-Type": "application/octet-stream"},
            ),
        )
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/platform-files/content",
                "query_string": b"",
                "headers": [],
            }
        )
        task = asyncio.create_task(
            file_app.selected_file_content(
                request,
                BEARER["Authorization"],
                READ_HEADERS["X-MIY-Selected-File"],
            )
        )
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "headers,query,expected",
    [
        ({}, "", 401),
        ({**READ_HEADERS, "Authorization": "Bearer "}, "", 401),
        (BEARER, "", 422),
        ({**READ_HEADERS, "X-MIY-Selected-File": "x" * 4097}, "", 422),
        (READ_HEADERS, "?url=https://other.test", 422),
    ],
)
def test_content_rejects_missing_auth_proof_and_arbitrary_query(
    file_app, monkeypatch, headers, query, expected
):
    upstream(monkeypatch, file_app, lambda _: pytest.fail("Rejected before network"))
    with TestClient(file_app.app) as client:
        assert (
            client.get("/api/platform-files/content" + query, headers=headers).status_code
            == expected
        )
