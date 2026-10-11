from __future__ import annotations


from fastapi.testclient import TestClient

from miy_api.domains.hermes.research_sources import (
    DEFAULT_RESEARCH_SOURCE_POLICY,
)
from dev_accounts import auth_headers, dev_login


def _admin_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(dev_login(client)["token"])


def test_admin_can_toggle_each_research_source_with_revision_control(
    client: TestClient,
) -> None:
    headers = _admin_headers(client)
    initial = client.get(
        "/api/v1/admin/hermes/research-sources",
        headers=headers,
    )

    assert initial.status_code == 200, initial.text
    payload = initial.json()
    assert payload["revision"] == 0
    assert {
        source["id"]: source["enabled"] for source in payload["sources"]
    } == DEFAULT_RESEARCH_SOURCE_POLICY

    updated = client.put(
        "/api/v1/admin/hermes/research-sources/semantic_scholar",
        headers=headers,
        json={"enabled": True, "expected_revision": payload["revision"]},
    )

    assert updated.status_code == 200, updated.text
    updated_payload = updated.json()
    assert updated_payload["revision"] == 1
    assert (
        next(source for source in updated_payload["sources"] if source["id"] == "semantic_scholar")[
            "enabled"
        ]
        is True
    )

    conflict = client.put(
        "/api/v1/admin/hermes/research-sources/crossref",
        headers=headers,
        json={"enabled": False, "expected_revision": payload["revision"]},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "hermes.research_settings_conflict"
