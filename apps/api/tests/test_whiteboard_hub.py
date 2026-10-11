from __future__ import annotations


from fastapi.testclient import TestClient

from dev_accounts import dev_login


def test_whiteboard_create_update_reload_and_archive(client: TestClient) -> None:
    session = _dev_login(client, "delivery-hub-admin")
    token = session["token"]

    create_response = client.post(
        "/api/v1/whiteboard/items",
        headers=_auth_headers(token),
        json={
            "title": "Launch Map",
            "company_visible": True,
            "company_admin_read_acknowledged": True,
        },
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["title"] == "Launch Map"
    assert created["scene"] == {"elements": [], "appState": {}, "files": {}}
    assert created["company_visible"] is True
    assert created["can_edit"] is True

    scene = {
        "elements": [{"id": "text-1", "type": "text", "text": "hello"}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    update_response = client.patch(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
        json={"title": "Launch Map v2", "scene": scene},
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["title"] == "Launch Map v2"
    assert update_response.json()["scene"] == scene

    reload_response = client.get(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
    )
    assert reload_response.status_code == 200
    assert reload_response.json()["scene"] == scene
    updated_at = reload_response.json()["updated_at"]

    view_response = client.post(
        f"/api/v1/whiteboard/items/{created['id']}/view",
        headers=_auth_headers(token),
    )
    assert view_response.status_code == 204
    after_view_response = client.get(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
    )
    assert after_view_response.status_code == 200
    assert after_view_response.json()["updated_at"] == updated_at

    noop_scene_response = client.patch(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
        json={
            "scene": {
                **scene,
                "type": "excalidraw",
                "version": 2,
                "appState": {
                    **scene["appState"],
                    "name": "Launch Map v2",
                    "selectedElementIds": {"text-1": True},
                    "scrollX": 12,
                    "zoom": {"value": 1},
                },
            }
        },
    )
    assert noop_scene_response.status_code == 200, noop_scene_response.text
    assert noop_scene_response.json()["updated_at"] == updated_at

    recent_response = client.get(
        "/api/v1/whiteboard/hub",
        headers=_auth_headers(token),
        params={"view": "recent"},
    )
    assert recent_response.status_code == 200
    assert [item["id"] for item in recent_response.json()["items"]] == [created["id"]]

    collab_session_response = client.get(
        f"/api/v1/whiteboard/collab/items/{created['id']}/session",
        headers=_auth_headers(token),
    )
    assert collab_session_response.status_code == 200, collab_session_response.text

    favorite_response = client.patch(
        f"/api/v1/whiteboard/items/{created['id']}/favorite",
        headers=_auth_headers(token),
    )
    assert favorite_response.status_code == 200, favorite_response.text

    delete_response = client.delete(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
    )
    assert delete_response.status_code == 204

    normal_hub_response = client.get(
        "/api/v1/whiteboard/hub",
        headers=_auth_headers(token),
    )
    assert normal_hub_response.status_code == 200
    assert created["id"] not in {item["id"] for item in normal_hub_response.json()["items"]}

    archived_response = client.get(
        "/api/v1/whiteboard/hub",
        headers=_auth_headers(token),
        params={"view": "archived"},
    )
    assert archived_response.status_code == 200
    assert [item["id"] for item in archived_response.json()["items"]] == [created["id"]]

    restore_response = client.post(
        f"/api/v1/whiteboard/items/{created['id']}/restore",
        headers=_auth_headers(token),
    )
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["trashed_at"] is None

    normal_after_restore_response = client.get(
        "/api/v1/whiteboard/hub",
        headers=_auth_headers(token),
    )
    assert normal_after_restore_response.status_code == 200
    assert created["id"] in {item["id"] for item in normal_after_restore_response.json()["items"]}

    delete_again_response = client.delete(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
    )
    assert delete_again_response.status_code == 204

    permanent_delete_response = client.delete(
        f"/api/v1/whiteboard/items/{created['id']}/permanent",
        headers=_auth_headers(token),
    )
    assert permanent_delete_response.status_code == 204, permanent_delete_response.text

    deleted_item_response = client.get(
        f"/api/v1/whiteboard/items/{created['id']}",
        headers=_auth_headers(token),
    )
    assert deleted_item_response.status_code == 404
    assert deleted_item_response.json()["code"] == "whiteboard.not_found"

    archived_after_delete_response = client.get(
        "/api/v1/whiteboard/hub",
        headers=_auth_headers(token),
        params={"view": "archived"},
    )
    assert archived_after_delete_response.status_code == 200
    assert created["id"] not in {
        item["id"] for item in archived_after_delete_response.json()["items"]
    }


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
