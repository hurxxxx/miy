from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps.models import (
    AppSession,
)
from test_organization_integrations import _auth_headers, _bootstrap_admin


@pytest.fixture(autouse=True)
def platform_origins(monkeypatch):
    monkeypatch.setenv(
        "MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test", "http://127.0.0.1:4200"]'
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def manifest(app_id: str = "sample-independent") -> dict:
    return {
        "schema_version": 1,
        "app_id": app_id,
        "display": {"name": "Test application", "translations": {"ko-KR": "시험 앱"}},
        "source": {"repository": "https://example.test/team/sample.git"},
        "requested_permissions": ["identity:read"],
    }


def setup_app(client):
    admin = _bootstrap_admin(client)
    headers = _auth_headers(admin["token"])
    definition = client.put(
        "/api/v1/independent-apps/definitions",
        headers=headers,
        json={
            "definition": manifest(),
            "source_revision": "a" * 40,
        },
    )
    assert definition.status_code == 200, definition.text
    installation_data = {
        "environment": "development",
        "origin": "https://sample.test",
        "enabled": True,
        "user_ids": [admin["user"]["id"]],
        "granted_permissions": ["identity:read"],
    }
    installation = client.post(
        "/api/v1/independent-apps/sample-independent/installations",
        headers=headers,
        json=installation_data,
    )
    assert installation.status_code == 201, installation.text
    return admin, headers, definition.json(), installation.json(), installation_data


def launch(client, headers, installation):
    verifier = "v" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    response = client.post(
        "/api/v1/independent-apps/launch",
        headers=headers,
        json={
            "installation_id": installation["id"],
            "code_challenge": challenge,
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert datetime.fromisoformat(response.json()["expires_at"]).utcoffset() == timedelta(0)
    return {
        "installation_id": installation["id"],
        "code": response.json()["code"],
        "code_verifier": verifier,
    }


def exchange(client, payload):
    return client.post(
        "/api/v1/independent-apps/exchange", headers={"Origin": "https://sample.test"}, json=payload
    )


def identity(client, token, installation_id, audience="https://sample.test"):
    return client.get(
        "/api/v1/independent-apps/session",
        headers=_auth_headers(token),
        params={
            "installation_id": installation_id,
            "audience": audience,
        },
    )


def test_exchange_is_bound_to_pkce_origin_installation_and_one_use(client):
    admin, headers, _, installation, _ = setup_app(client)
    payload = launch(client, headers, installation)
    assert exchange(client, payload | {"code_verifier": "x" * 43}).status_code == 401
    assert (
        client.post(
            "/api/v1/independent-apps/exchange",
            headers={"Origin": "https://wrong.test"},
            json=payload,
        ).status_code
        == 401
    )
    assert exchange(client, payload | {"installation_id": "wrong-installation"}).status_code == 401
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: exchange(client, payload), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 401]
    session = next(response.json() for response in responses if response.status_code == 200)
    assert session["audience"] == "https://sample.test"
    assert datetime.fromisoformat(session["expires_at"]).utcoffset() == timedelta(0)
    assert (
        identity(client, session["token"], installation["id"]).json()["user_id"]
        == admin["user"]["id"]
    )
    assert (
        identity(client, session["token"], installation["id"], "https://other.test").status_code
        == 401
    )
    assert identity(client, admin["token"], installation["id"]).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth_headers(session["token"])).status_code == 401
    with get_session_factory()() as db:
        stored = db.get(AppSession, hash_token(session["token"]))
        assert stored is not None and stored.token_hash != session["token"]
