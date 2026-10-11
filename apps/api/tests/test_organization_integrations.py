from __future__ import annotations

from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.integrations.models import PlatformApiKey


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_admin(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "full_name": "Directory Admin",
            "email": "directory-admin@miy.local",
            "password": "supersecret123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_organization_unit(
    client: TestClient,
    token: str,
    *,
    name: str,
    parent_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/admin/groups",
        headers=_auth_headers(token),
        json={
            "name": name,
            "unit_type": "department",
            "source": "hr",
            "parent_id": parent_id,
            "active": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_scoped_platform_api_keys_are_revealable_audited_and_revocable(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin(client)
    admin_token = admin["token"]
    organization = _create_organization_unit(client, admin_token, name="Operations")

    issue_response = client.post(
        "/api/v1/admin/platform-api-keys",
        headers=_auth_headers(admin_token),
        json={"name": "HR directory sync", "scopes": ["organization:read"]},
    )
    assert issue_response.status_code == 201, issue_response.text
    assert issue_response.headers["cache-control"] == "private, no-store"
    issued = issue_response.json()
    key_id = issued["item"]["id"]
    api_key = issued["api_key"]
    assert api_key.startswith("miy_pk_")
    assert issued["item"]["key_prefix"] == api_key[:18]

    with get_session_factory()() as db:
        stored = db.get(PlatformApiKey, key_id)
        assert stored is not None
        assert stored.token_hash != api_key
        assert api_key not in stored.secret_ciphertext
        assert stored.secret_ciphertext

    list_response = client.get(
        "/api/v1/admin/platform-api-keys",
        headers=_auth_headers(admin_token),
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.headers["cache-control"] == "private, no-store"
    list_payload = list_response.json()
    assert set(list_payload["available_scopes"]) == {
        "organization:read",
        "people:read",
        "app-catalog:read",
        "app-usage:read",
    }
    assert "api_key" not in list_response.text
    assert any(
        operation["path"] == "/api/v1/integrations/directory/organization-units"
        for spec in list_payload["scope_specs"]
        if spec["scope"] == "organization:read"
        for operation in spec["operations"]
    )

    external_response = client.get(
        "/api/v1/integrations/directory/organization-units",
        headers=_auth_headers(api_key),
    )
    assert external_response.status_code == 200, external_response.text
    assert external_response.headers["cache-control"] == "private, no-store"
    assert organization["id"] in {item["id"] for item in external_response.json()["items"]}

    wrong_scope_response = client.get(
        "/api/v1/integrations/directory/people",
        headers=_auth_headers(api_key),
    )
    assert wrong_scope_response.status_code == 403
    assert wrong_scope_response.json()["code"] == "platform_api_key.scope_required"
    assert wrong_scope_response.headers["cache-control"] == "private, no-store"

    user_token_response = client.get(
        "/api/v1/integrations/directory/organization-units",
        headers=_auth_headers(admin_token),
    )
    assert user_token_response.status_code == 401
    assert user_token_response.json()["code"] == "platform_api_key.invalid"

    reveal_response = client.post(
        f"/api/v1/admin/platform-api-keys/{key_id}/reveal",
        headers=_auth_headers(admin_token),
    )
    assert reveal_response.status_code == 200, reveal_response.text
    assert reveal_response.headers["cache-control"] == "private, no-store"
    assert reveal_response.json()["api_key"] == api_key

    audit_response = client.get(
        "/api/v1/admin/audit-logs?limit=100",
        headers=_auth_headers(admin_token),
    )
    assert audit_response.status_code == 200, audit_response.text
    assert api_key not in audit_response.text
    actions = {item["action"] for item in audit_response.json()["items"]}
    assert {
        "admin.platform_api_key.issue",
        "admin.platform_api_key.reveal",
        "integration.directory.organization_units.read",
    }.issubset(actions)

    revoke_response = client.post(
        f"/api/v1/admin/platform-api-keys/{key_id}/revoke",
        headers=_auth_headers(admin_token),
    )
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "revoked"

    with get_session_factory()() as db:
        revoked = db.get(PlatformApiKey, key_id)
        assert revoked is not None
        assert revoked.secret_ciphertext == ""
        assert revoked.revoked_at is not None

    rejected_response = client.get(
        "/api/v1/integrations/directory/organization-units",
        headers=_auth_headers(api_key),
    )
    assert rejected_response.status_code == 401
    assert rejected_response.json()["code"] == "platform_api_key.invalid"

    reveal_revoked_response = client.post(
        f"/api/v1/admin/platform-api-keys/{key_id}/reveal",
        headers=_auth_headers(admin_token),
    )
    assert reveal_revoked_response.status_code == 409
    assert reveal_revoked_response.json()["code"] == "platform_api_key.inactive"
