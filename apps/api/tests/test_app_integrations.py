from uuid import uuid4

import pytest
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.models import AuditLog, utcnow_naive
from miy_api.domains.usage.models import UsageEvent

from test_organization_integrations import _auth_headers, _bootstrap_admin


@pytest.fixture
def independent_installation(client, monkeypatch):
    from miy_api.core.settings import get_settings
    from test_independent_apps import setup_app

    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    yield setup_app(client)
    get_settings.cache_clear()


def test_installation_observations_are_scoped_read_only_and_omit_private_context(
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


def test_installation_observation_pages_detect_policy_changes(client, independent_installation):
    from miy_api.domains.independent_apps.models import AppInstallationRecord

    admin, _, _, installation, _ = independent_installation
    with get_session_factory()() as db:
        db.add_all(
            [
                AppInstallationRecord(
                    id=str(uuid4()),
                    app_id="sample-independent",
                    environment="development",
                    origin=f"https://preview-{index}.example.test",
                    enabled=False,
                )
                for index in range(204)
            ]
        )
        db.commit()
    key = issue(client, admin, ["app-catalog:read"])
    auth = _auth_headers(key["api_key"])
    path = "/api/v1/integrations/apps/sample-independent/installations"
    first = client.get(path + "?page=1&page_size=200", headers=auth).json()
    second = client.get(path + "?page=2&page_size=200", headers=auth).json()
    assert first["total"] == second["total"] == 205
    assert len(first["items"]) == 200 and len(second["items"]) == 5
    assert first["catalog_revision"] == second["catalog_revision"]
    with get_session_factory()() as db:
        db.get(AppInstallationRecord, installation["id"]).generation += 1
        db.commit()
    changed = client.get(path, headers=auth).json()
    assert changed["catalog_revision"] != first["catalog_revision"]


def issue(client, admin, scopes):
    response = client.post(
        "/api/v1/admin/platform-api-keys",
        headers=_auth_headers(admin["token"]),
        json={"name": "Workbench test", "scopes": scopes},
    )
    assert response.status_code == 201
    return response.json()


def test_first_registration_projects_commit_without_changing_inactive_installation(
    client, monkeypatch
):
    from miy_api.core.settings import get_settings
    from miy_api.domains.independent_apps.models import AppInstallationRecord
    from test_independent_app_bootstrap import payload

    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    request = payload()
    response = client.post(
        "/api/v1/independent-apps/bootstrap", headers=_auth_headers(admin["token"]), json=request
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    key = issue(client, admin, ["app-catalog:read"])
    auth = _auth_headers(key["api_key"])

    def observed():
        result = client.get("/api/v1/integrations/apps?page_size=200", headers=auth)
        assert result.status_code == 200
        body = result.json()
        return body, next(item for item in body["items"] if item["app_id"] == receipt["app_id"])

    before, item = observed()
    assert item["registered_source_revision"] == receipt["source_revision"] == "a" * 40
    assert item["definition_digest"] == receipt["definition_digest"]
    assert item["installed_revision"] is None and item["enabled"] is False
    update = client.put(
        "/api/v1/independent-apps/definitions", headers=_auth_headers(admin["token"]),
        json={"definition": request["definition"], "source_revision": "b" * 40,
              "expected_digest": receipt["definition_digest"], "expected_source_revision": "a" * 40},
    )
    assert update.status_code == 200, update.text
    after, item = observed()
    assert item["registered_source_revision"] == "b" * 40
    assert item["definition_digest"] == receipt["definition_digest"]
    assert item["installed_revision"] is None
    assert before["catalog_revision"] != after["catalog_revision"]
    with get_session_factory()() as db:
        installation = db.get(AppInstallationRecord, receipt["installation_id"])
        assert installation.enabled is False and installation.state == "disabled"
        assert installation.generation == 1 and installation.release_id is None
    get_settings.cache_clear()


def test_registered_commit_stays_separate_from_existing_production_release(
    client, independent_installation
):
    from miy_api.domains.independent_apps.models import AppInstallationRecord
    from test_independent_app_delivery import build_release

    admin, owner_auth, definition, _, _ = independent_installation
    release_id = build_release(definition)
    with get_session_factory()() as db:
        db.add(AppInstallationRecord(
            id=str(uuid4()), app_id="sample-independent", environment="production",
            origin="https://existing-production.test", release_id=release_id,
        ))
        db.commit()
    response = client.put(
        "/api/v1/independent-apps/definitions", headers=owner_auth,
        json={"definition": definition["definition"], "source_revision": "b" * 40,
              "expected_digest": definition["definition_digest"], "expected_source_revision": "a" * 40},
    )
    assert response.status_code == 200, response.text
    key = issue(client, admin, ["app-catalog:read"])
    body = client.get(
        "/api/v1/integrations/apps?page_size=200", headers=_auth_headers(key["api_key"])
    ).json()
    item = next(item for item in body["items"] if item["app_id"] == "sample-independent")
    assert item["registered_source_revision"] == "b" * 40
    assert item["installed_revision"] == "a" * 40


def test_app_projection_requires_its_own_scopes_and_never_becomes_admin(client):
    admin = _bootstrap_admin(client)
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
    empty_page = client.get(
        "/api/v1/integrations/apps?page=1000000&page_size=200", headers=auth
    )
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
    assert (
        client.post(
            f"/api/v1/admin/platform-api-keys/{key['item']['id']}/revoke",
            headers=_auth_headers(admin["token"]),
        ).status_code
        == 200
    )
    assert client.get("/api/v1/integrations/apps", headers=auth).status_code == 401


def test_usage_is_app_scoped_monthly_aggregate_with_missing_cost_and_tokens(client):
    admin = _bootstrap_admin(client)
    key = issue(client, admin, ["app-usage:read"])
    with get_session_factory()() as db:
        for app_id, tokens in (("docs", 120), ("docs", None), ("pms", 999)):
            record_audit_log(
                db,
                actor_user_id=None,
                action="llm_call",
                entity_kind="ai",
                entity_id=None,
                summary="Test aggregate input",
                payload={
                    "app_id": app_id,
                    "status": "ok",
                    "usage": {"total_tokens": tokens},
                    "private_prompt": "never-export-this",
                },
            )
        clock = utcnow_naive()
        db.add(
            UsageEvent(
                id=str(uuid4()),
                actor_user_id=admin["user"]["id"],
                app_id="docs",
                event_type="app.open",
                content_title="private document",
                count=3,
                dedupe_key=str(uuid4()),
                bucket_started_at=clock,
                occurred_at=clock,
            )
        )
        db.commit()
    auth = _auth_headers(key["api_key"])
    response = client.get("/api/v1/integrations/apps/docs/usage", headers=auth)
    assert response.status_code == 200
    result = response.json()
    assert result["app_opens"] == 3
    assert result["llm_calls"] == 2 and result["total_tokens"] == 120
    assert result["unreported_calls"] == 1
    assert result["amount_minor"] is None and result["cost_basis"] == "not_reported"
    assert "never-export-this" not in response.text and "private document" not in response.text
    assert "actor_user_id" not in response.text
    assert client.get("/api/v1/integrations/apps/unknown/usage", headers=auth).status_code == 404
    assert (
        client.get(
            "/api/v1/integrations/apps/docs/usage?month=9999-12-01", headers=auth
        ).status_code
        == 422
    )
    with get_session_factory()() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == "integration.apps.usage.read"))
        assert event.payload["api_key_id"] == key["item"]["id"]


def test_runtime_revision_is_not_invented_for_separately_released_workbench(client):
    admin = _bootstrap_admin(client)
    key = issue(client, admin, ["app-catalog:read"])
    items = client.get("/api/v1/integrations/apps", headers=_auth_headers(key["api_key"])).json()[
        "items"
    ]
    workbench = next(a for a in items if a["app_id"] == "codex-console")
    assert workbench["title"] == "MIY Workbench"
    assert workbench["release_unit"] == "miy-workbench" and workbench["installed_revision"] is None


def test_catalog_pages_include_unmanaged_apps_and_share_a_revision(client, monkeypatch):
    from miy_api.domains.integrations import app_projection

    apps = [{"app_id": f"dynamic-{i}", "title": f"Dynamic {i}"} for i in range(205)]
    monkeypatch.setattr(app_projection, "APP_CONTRACTS", apps)
    admin = _bootstrap_admin(client)
    key = issue(client, admin, ["app-catalog:read"])
    auth = _auth_headers(key["api_key"])
    first = client.get("/api/v1/integrations/apps?page=1&page_size=200", headers=auth).json()
    second = client.get("/api/v1/integrations/apps?page=2&page_size=200", headers=auth).json()
    assert first["total"] == second["total"] == 205
    assert len(first["items"]) == 200 and len(second["items"]) == 5
    assert first["catalog_revision"] == second["catalog_revision"]
    assert len({item["app_id"] for item in first["items"] + second["items"]}) == 205
    assert all(
        item["release_unit"] is None and item["installed_revision"] is None
        for item in second["items"]
    )
    apps[-1]["title"] = "Changed"
    changed = client.get("/api/v1/integrations/apps?page=2&page_size=200", headers=auth).json()
    assert changed["catalog_revision"] != first["catalog_revision"]
