from __future__ import annotations

from dev_accounts import dev_login
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_engine
from miy_api.core.settings import get_settings
from miy_api.domains.ai.registry import reset_ai_capability_registry
from miy_api.domains.auth.models import CompanyAppControl


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ai_path(suffix: str) -> str:
    return f"/api/v1/chatbot{suffix}"


def _disable_platform_app(app_id: str) -> None:
    with Session(get_engine()) as session:
        control = session.scalar(
            select(CompanyAppControl).where(CompanyAppControl.app_id == app_id)
        )
        assert control is not None
        control.enabled = False
        session.add(control)
        session.commit()


def _reset_settings_and_registry() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    reset_ai_capability_registry()


def test_manifest_and_openapi_reflect_platform_visibility_changes_on_next_request(
    client: TestClient,
) -> None:
    auth = _dev_login(client, "delivery-hub-admin")
    _disable_platform_app("planner")

    manifest_response = client.get(
        _ai_path("/capabilities/manifest"),
        headers=_auth_headers(auth["token"]),
    )
    assert manifest_response.status_code == 200, manifest_response.text
    manifest_payload = manifest_response.json()
    assert "planner.list_events" not in {item["name"] for item in manifest_payload["tools"]}

    openapi_response = client.get(
        _ai_path("/capabilities/openapi.json"),
        headers=_auth_headers(auth["token"]),
    )
    assert openapi_response.status_code == 200, openapi_response.text
    openapi_payload = openapi_response.json()
    assert "/mcp/tools/planner.list_events" not in openapi_payload["paths"]
