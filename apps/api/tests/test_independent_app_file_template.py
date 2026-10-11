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
