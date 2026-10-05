from uuid import uuid4

from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.models import AuditLog, utcnow_naive
from miy_api.domains.usage.models import UsageEvent

from test_organization_integrations import _auth_headers, _bootstrap_admin


def issue(client, admin, scopes):
    response = client.post(
        "/api/v1/admin/platform-api-keys",
        headers=_auth_headers(admin["token"]),
        json={"name": "Workbench test", "scopes": scopes},
    )
    assert response.status_code == 201
    return response.json()


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
    item = next(row for row in response.json()["items"] if row["app_id"] == "docs")
    assert set(item) == {
        "app_id",
        "title",
        "enabled",
        "release_unit",
        "installed_revision",
        "runtime_ai",
    }
    assert item["release_unit"] == "miy-app"
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
