from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_data_size_limit_counts_utf8_and_rejects_nonfinite_json():
    from miy_api.domains.independent_apps.data_store import DataStoreError, PostgresAppData

    PostgresAppData._validate("notes", {"text": "한" * 4000})
    with pytest.raises(DataStoreError, match="payload_invalid"):
        PostgresAppData._validate("notes", {"text": "한" * 6000})
    with pytest.raises(DataStoreError, match="payload_invalid"):
        PostgresAppData._validate("notes", {"score": float("inf")})


@pytest.fixture
def notes_app(monkeypatch):
    installation = str(uuid4())
    for key, value in {
        "MIY_APP_ID": "private-notes",
        "MIY_APP_INSTALLATION_ID": installation,
        "MIY_APP_ORIGIN": "https://notes.test",
        "MIY_APP_PLATFORM_ORIGIN": "https://platform.test",
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        "business", ROOT / "templates/independent-app-data/business.py"
    )
    business = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(business)
    monkeypatch.setitem(sys.modules, "business", business)
    spec = importlib.util.spec_from_file_location(
        "notes_app", ROOT / "templates/independent-app/api.py"
    )
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api, installation


def test_business_routes_keep_actor_and_database_selection_outside_app_input(
    notes_app, monkeypatch
):
    api, installation = notes_app
    seen = []

    def respond(request):
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        if request.method == "POST":
            return httpx.Response(
                201, json={"id": str(uuid4()), "payload": {"text": "한글 메모"}, "version": 1}
            )
        return httpx.Response(204)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        api.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with TestClient(api.app) as client:
        assert client.get("/api/notes").status_code == 401
        assert seen == []
        bearer = {"Authorization": "Bearer synthetic-app-session"}
        assert (
            client.get(
                "/api/notes?installation_id=forged&audience=https://evil.test", headers=bearer
            ).status_code
            == 200
        )
        assert (
            client.post("/api/notes", headers=bearer, json={"text": "한글 메모"}).status_code == 201
        )
        assert (
            client.post(
                "/api/notes", headers=bearer, json={"text": "no", "owner_id": "victim"}
            ).status_code
            == 422
        )
        assert (
            client.delete(f"/api/notes/{uuid4()}?expected_version=1", headers=bearer).status_code
            == 204
        )
    assert len(seen) == 3
    for request in seen:
        assert request.url.host == "platform.test"
        assert request.url.path.startswith("/api/v1/independent-apps/_data/notes")
        assert request.url.params["installation_id"] == installation
        assert request.url.params["audience"] == "https://notes.test"
        assert request.headers["authorization"] == bearer["Authorization"]


@pytest.mark.parametrize(
    "upstream_status, expected", [(401, 401), (403, 403), (409, 409), (502, 503)]
)
def test_data_proxy_preserves_revocation_conflict_and_hides_upstream_errors(
    notes_app, monkeypatch, upstream_status, expected
):
    api, _ = notes_app
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _: httpx.Response(upstream_status, text="internal details")
    )
    monkeypatch.setattr(
        api.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    with TestClient(api.app) as client:
        response = client.get("/api/notes", headers={"Authorization": "Bearer synthetic"})
    assert response.status_code == expected
    assert "internal details" not in response.text


def test_data_proxy_bounds_streamed_platform_response(notes_app, monkeypatch):
    api, _ = notes_app
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * (512 * 1024 + 1)))
    monkeypatch.setattr(
        api.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    with TestClient(api.app) as client:
        assert (
            client.get("/api/notes", headers={"Authorization": "Bearer synthetic"}).status_code
            == 503
        )
