from __future__ import annotations

from fastapi.testclient import TestClient

from dev_accounts import dev_login


TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/l5vN2wAAAABJRU5ErkJggg=="
)


def test_diagrams_visibility_limits_personal_items_to_owner(
    client: TestClient,
    in_memory_object_storage: None,
) -> None:
    owner = dev_login(client, "delivery-hub-admin")
    member = dev_login(client, "delivery-hub-member")

    personal_response = client.post(
        "/api/v1/diagrams/items",
        headers=_auth_headers(owner["token"]),
        json={"title": "Private Flow"},
    )
    assert personal_response.status_code == 201, personal_response.text
    personal = personal_response.json()
    assert personal["visibility"] == "personal"

    company_response = client.post(
        "/api/v1/diagrams/items",
        headers=_auth_headers(owner["token"]),
        json={
            "title": "Shared Flow",
            "visibility": "company",
            "company_admin_read_acknowledged": True,
        },
    )
    assert company_response.status_code == 201, company_response.text
    company_item = company_response.json()
    assert company_item["visibility"] == "company"

    member_hub_response = client.get(
        "/api/v1/diagrams/hub",
        headers=_auth_headers(member["token"]),
    )
    assert member_hub_response.status_code == 200, member_hub_response.text
    member_ids = [item["id"] for item in member_hub_response.json()["items"]]
    assert company_item["id"] in member_ids
    assert personal["id"] not in member_ids

    member_private_response = client.get(
        f"/api/v1/diagrams/items/{personal['id']}",
        headers=_auth_headers(member["token"]),
    )
    assert member_private_response.status_code == 404

    member_public_update_response = client.patch(
        f"/api/v1/diagrams/items/{company_item['id']}",
        headers=_auth_headers(member["token"]),
        json={"version": company_item["version"], "title": "Shared Flow Updated"},
    )
    assert member_public_update_response.status_code == 403, member_public_update_response.text

    member_visibility_response = client.patch(
        f"/api/v1/diagrams/items/{company_item['id']}",
        headers=_auth_headers(member["token"]),
        json={"version": company_item["version"], "visibility": "personal"},
    )
    assert member_visibility_response.status_code == 403


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
