from __future__ import annotations

from dev_accounts import dev_login
from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import CompanyAppControl


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def test_app_gate_rechecks_company_master_for_existing_session(client: TestClient) -> None:
    session = _dev_login(client, "administrator")
    headers = {"Authorization": f"Bearer {session['token']}"}
    enabled = client.get("/api/v1/docs/hub", headers=headers)
    assert enabled.status_code == 200, enabled.text
    with get_session_factory()() as db:
        db.get(CompanyAppControl, "docs").enabled = False
        db.commit()
    disabled = client.get("/api/v1/docs/hub", headers=headers)
    assert disabled.status_code == 403, disabled.text
    bootstrap = client.get("/api/v1/apps/bootstrap", headers=headers)
    assert bootstrap.status_code == 200
    payload = bootstrap.json()
    assert "docs" not in {item["app_id"] for item in payload["apps"]}
    assert "docs" not in {item["app_id"] for item in payload["nav"]}
    assert "doc" not in {item["value"] for item in payload["keyword_search"]["entity_types"]}
