from __future__ import annotations

from fastapi.testclient import TestClient

from dev_accounts import auth_headers, dev_login


def test_personal_todos_are_isolated_by_user(client: TestClient) -> None:
    owner = dev_login(client, "administrator")
    other = dev_login(client, "delivery-hub-member")
    owner_headers = auth_headers(owner["token"])
    other_headers = auth_headers(other["token"])
    todo = _create_todo(client, headers=owner_headers, title="Private task")

    other_list = client.get("/api/v1/personal-widgets/todos", headers=other_headers)
    assert other_list.status_code == 200, other_list.text
    assert other_list.json() == {"items": []}

    other_update = client.patch(
        f"/api/v1/personal-widgets/todos/{todo['id']}",
        headers=other_headers,
        json={"completed": True},
    )
    assert other_update.status_code == 404, other_update.text

    other_delete = client.delete(
        f"/api/v1/personal-widgets/todos/{todo['id']}",
        headers=other_headers,
    )
    assert other_delete.status_code == 404, other_delete.text

    owner_list = client.get("/api/v1/personal-widgets/todos", headers=owner_headers)
    assert [item["id"] for item in owner_list.json()["items"]] == [todo["id"]]


def test_personal_memo_is_isolated_by_user(client: TestClient) -> None:
    owner = dev_login(client, "administrator")
    other = dev_login(client, "delivery-hub-member")

    owner_save = client.put(
        "/api/v1/personal-widgets/memo",
        headers=auth_headers(owner["token"]),
        json={"body": "Owner private memo"},
    )
    assert owner_save.status_code == 200, owner_save.text

    other_get = client.get(
        "/api/v1/personal-widgets/memo",
        headers=auth_headers(other["token"]),
    )
    assert other_get.status_code == 200, other_get.text
    assert other_get.json()["body"] == ""

    other_save = client.put(
        "/api/v1/personal-widgets/memo",
        headers=auth_headers(other["token"]),
        json={"body": "Other private memo"},
    )
    assert other_save.status_code == 200, other_save.text

    owner_get = client.get(
        "/api/v1/personal-widgets/memo",
        headers=auth_headers(owner["token"]),
    )
    assert owner_get.json()["body"] == "Owner private memo"


def _create_todo(client: TestClient, *, headers: dict[str, str], title: str) -> dict:
    response = client.post(
        "/api/v1/personal-widgets/todos",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()
