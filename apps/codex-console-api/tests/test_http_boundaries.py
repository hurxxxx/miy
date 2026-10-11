import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from conftest import PASSWORD
from starlette.requests import Request

from codex_console import app as console_app
from codex_console import auth


def dispatch(client, *, path="/api/tasks", method="POST", authenticated=True, receive=None):
    headers = [(b"host", b"localhost"), (b"origin", b"http://localhost")]
    if authenticated:
        headers.extend(
            [
                (b"cookie", f"{auth.COOKIE}={client.cookies[auth.COOKIE]}".encode()),
                (b"x-csrf-token", client.cookies[auth.CSRF_COOKIE].encode()),
            ]
        )
    request = Request(
        {
            "type": "http",
            "app": client.app,
            "method": method,
            "path": path,
            "headers": headers,
            "query_string": b"",
        },
        receive,
    )
    boundary = client.app.user_middleware[0].kwargs["dispatch"]
    handler = AsyncMock()
    return request, boundary, handler


@pytest.mark.parametrize(
    "path",
    ["/api/tasks", "/api/codex/login", "/api/templates", "/api/monitor/host", "/api/overview"],
)
def test_unauthenticated_mutation_is_denied_without_consuming_body(client, path):
    receive = AsyncMock(side_effect=AssertionError("Unauthorized body must not be read"))
    request, boundary, handler = dispatch(client, path=path, authenticated=False, receive=receive)
    response = client.portal.call(boundary, request, handler)
    assert response.status_code == 401
    assert json.loads(response.body) == {"code": "unauthenticated"}
    assert response.headers["cache-control"] == "no-store"
    receive.assert_not_awaited()
    handler.assert_not_awaited()


def test_disconnected_json_request_does_not_reach_handler(client):
    receive = AsyncMock(
        side_effect=[
            {"type": "http.request", "body": b'{"title":"partial', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    request, boundary, handler = dispatch(client, receive=receive)
    response = client.portal.call(boundary, request, handler)
    assert response.status_code == 400
    assert json.loads(response.body) == {"code": "input_cancelled"}
    handler.assert_not_awaited()


def test_slow_json_request_has_a_total_deadline(client, monkeypatch):
    monkeypatch.setattr(console_app, "BODY_TIMEOUT_SECONDS", 0.01, raising=False)

    async def receive():
        await asyncio.Future()

    request, boundary, handler = dispatch(client, receive=receive)

    async def run():
        return await asyncio.wait_for(boundary(request, handler), 1)

    response = client.portal.call(run)
    assert response.status_code == 408
    assert json.loads(response.body) == {"code": "input_timeout"}
    handler.assert_not_awaited()


@pytest.mark.parametrize("failure", ["host", "origin", "size", "csrf", "validation"])
def test_rejected_api_requests_keep_security_headers(client, failure):
    headers, body = {}, b"{}"
    if failure == "host":
        headers["host"] = "attacker.invalid"
    elif failure == "origin":
        headers["origin"] = "https://attacker.invalid"
    elif failure == "size":
        body = b"x" * (128 * 1024 + 1)
    elif failure == "csrf":
        headers["x-csrf-token"] = "forged"
    response = client.post("/api/tasks", content=body, headers=headers)
    assert response.status_code in (401, 403, 413, 422)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_csrf_token_from_another_valid_session_cannot_authorize_mutation(client):
    previous_csrf = client.cookies[auth.CSRF_COOKIE]
    assert client.post("/api/session", json={"password": PASSWORD}).status_code == 200
    response = client.post(
        "/api/tasks", json={"title": "Rejected"}, headers={"x-csrf-token": previous_csrf}
    )
    assert response.status_code == 401
    assert client.get("/api/tasks").json() == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/tasks",
        "/api/templates",
        "/api/codex/account",
        "/api/overview",
        "/api/monitor/host",
        "/api/monitor/services",
        f"/api/tasks/{uuid4()}/events",
    ],
)
def test_forged_session_cannot_read_private_routes(client, path):
    client.cookies.set(auth.COOKIE, "forged", domain="localhost.local", path="/")
    assert client.get(path).status_code == 401
