import pytest

from miy_api.core.db import get_session_factory

from test_organization_integrations import _auth_headers


@pytest.fixture
def independent_installation(client, monkeypatch):
    from miy_api.core.settings import get_settings
    from test_independent_apps import setup_app

    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    yield setup_app(client)
    get_settings.cache_clear()


def issue(client, admin, scopes):
    response = client.post(
        "/api/v1/admin/platform-api-keys",
        headers=_auth_headers(admin["token"]),
        json={"name": "Workbench test", "scopes": scopes},
    )
    assert response.status_code == 201
    return response.json()


def test_catalog_projection_respects_scope_and_separate_release_identity(
    client, independent_installation
):
    from test_independent_app_delivery import build_release, enqueue

    admin, owner_auth, definition, installation, _ = independent_installation
    release_id = build_release(definition)
    payload, _ = enqueue(client, independent_installation, release_id)
    key = issue(client, admin, ["app-catalog:read"])
    auth = _auth_headers(key["api_key"])
    path = "/api/v1/integrations/apps/sample-independent/installations"
    response = client.get(path, headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    item = response.json()["items"][0]
    assert item["id"] == installation["id"]
    assert item["release_id"] is None  # Queuing is not activation.
    assert item["deployment"]["request_id"] == payload["request_id"]
    assert item["deployment"]["state"] == "queued"
    assert item["deployment"]["updated_at"].endswith(("Z", "+00:00"))
    for private in (
        "actor_user_id",
        "source_session_id",
        "user_ids",
        "group_ids",
        "runtime_config",
        "request_hash",
    ):
        assert private not in response.text
    assert client.get(path, headers=owner_auth).status_code == 401
    wrong = issue(client, admin, ["app-usage:read"])
    assert client.get(path, headers=_auth_headers(wrong["api_key"])).status_code == 403
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/deployments",
            headers=auth,
            json=payload,
        ).status_code
        == 401
    )
    assert (
        client.get("/api/v1/integrations/apps/missing/installations", headers=auth).status_code
        == 404
    )
    directory = issue(client, admin, ["people:read"])
    assert (
        client.get(
            "/api/v1/integrations/apps", headers=_auth_headers(directory["api_key"])
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/integrations/apps", headers=_auth_headers(admin["token"])).status_code
        == 401
    )
    key = issue(client, admin, ["app-catalog:read"])
    auth = _auth_headers(key["api_key"])
    response = client.get("/api/v1/integrations/apps?page_size=200", headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["schema_version"] == 1
    assert response.json()["registration_status_version"] == 1
    empty_page = client.get("/api/v1/integrations/apps?page=1000000&page_size=200", headers=auth)
    assert empty_page.status_code == 200
    assert empty_page.json()["items"] == []
    assert empty_page.json()["registration_status_version"] == 1
    assert empty_page.json()["catalog_revision"] == response.json()["catalog_revision"]
    item = next(row for row in response.json()["items"] if row["app_id"] == "docs")
    assert set(item) == {
        "app_id",
        "title",
        "enabled",
        "release_unit",
        "installed_revision",
        "registered_source_revision",
        "runtime_ai",
        "title_translations",
        "icon_key",
        "source_repository",
        "source_directory",
        "definition_digest",
    }
    assert item["release_unit"] == "miy-app"
    assert item["registered_source_revision"] is None
    assert client.get("/api/v1/integrations/apps/docs/usage", headers=auth).status_code == 403
    assert client.get("/api/v1/admin/apps/docs/access-policy", headers=auth).status_code == 401
    assert (
        client.put(
            "/api/v1/admin/apps/docs/access-policy",
            headers=auth,
            json={"enabled": True, "audience": "all", "user_ids": [], "group_ids": []},
        ).status_code
        == 401
    )
    workbench = next(row for row in response.json()["items"] if row["app_id"] == "codex-console")
    assert workbench["release_unit"] == "miy-workbench" and workbench["installed_revision"] is None
    assert (
        client.post(
            f"/api/v1/admin/platform-api-keys/{key['item']['id']}/revoke",
            headers=_auth_headers(admin["token"]),
        ).status_code
        == 200
    )
    assert client.get("/api/v1/integrations/apps", headers=auth).status_code == 401
    from dev_accounts import create_company_user_session
    from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant
    from test_apps_launch_catalog import _headers

    member = create_company_user_session(
        client, login_id="launch-member", email="launch@example.test", full_name="Launch Member"
    )
    user_id = member["user"]["id"]
    with get_session_factory()() as db:
        db.get(AppAccessPolicy, "docs").audience = "selected"
        db.add(AppUserGrant(app_id="docs", user_id=user_id))
        db.commit()
    admitted = client.get("/api/v1/apps/bootstrap", headers=_headers(member))
    assert admitted.status_code == 200, admitted.text
    assert "docs" in {a["app_id"] for a in admitted.json()["apps"]}
    with get_session_factory()() as db:
        db.delete(db.get(AppUserGrant, ("docs", user_id)))
        db.commit()
    revoked = client.get("/api/v1/apps/bootstrap", headers=_headers(member))
    assert revoked.status_code == 200, revoked.text
    assert "docs" not in {a["app_id"] for a in revoked.json()["apps"]}
    direct = client.get("/api/v1/docs/hub", headers=_headers(member))
    assert direct.status_code == 403, direct.text
