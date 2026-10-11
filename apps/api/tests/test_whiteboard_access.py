from __future__ import annotations

from fastapi.testclient import TestClient

from dev_accounts import dev_login


def _create_space_whiteboard(client: TestClient, token: str, space_id: str) -> dict:
    response = client.post(
        "/api/v1/whiteboard/items",
        headers=_auth_headers(token),
        json={
            "title": "ACL Board",
            "source_app": "pms",
            "source_kind": "manual",
            "company_admin_read_acknowledged": True,
            "primary_target": {
                "company_admin_read_acknowledged": True,
                "app": "pms",
                "type": "space",
                "id": space_id,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list(client: TestClient, token: str, *, key: str, name: str) -> dict:
    from test_meeting import _create_task_list as create_pms_list

    return create_pms_list(client, token, key=key, name=name)


def _add_space_member(
    client: TestClient,
    token: str,
    space_id: str,
    user_id: str,
    role: str,
) -> dict:
    response = client.post(
        f"/api/v1/pms/spaces/{space_id}/members",
        headers=_auth_headers(token),
        json={"user_id": user_id, "role": role},
    )
    if response.status_code == 409:
        response = client.patch(
            f"/api/v1/pms/spaces/{space_id}/members/{user_id}",
            headers=_auth_headers(token),
            json={"role": role},
        )
        assert response.status_code == 200, response.text
        return response.json()
    assert response.status_code == 201, response.text
    return response.json()


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_private_board_explicit_share_and_revoke_lifetime(client):
    owner = _dev_login(client, "delivery-hub-admin")
    viewer = _dev_login(client, "delivery-hub-member")
    headers = _auth_headers(owner["token"])
    view_headers = _auth_headers(viewer["token"])
    created = client.post(
        "/api/v1/whiteboard/items", headers=headers, json={"title": "Private board"}
    )
    assert created.status_code == 201 and created.json()["is_private"]
    path = f"/api/v1/whiteboard/items/{created.json()['id']}"
    assert client.get(path, headers=view_headers).status_code == 404
    share = path + f"/sharing/users/{viewer['user']['id']}"
    assert client.put(share, headers=headers, json={"access_level": "edit"}).status_code == 200
    assert client.get(path, headers=view_headers).status_code == 200
    assert (
        client.patch(
            path,
            headers=view_headers,
            json={"scene": {"elements": [], "appState": {}, "files": {}}},
        ).status_code
        == 200
    )
    assert client.delete(share, headers=headers).status_code == 200
    assert client.get(path, headers=view_headers).status_code == 404
