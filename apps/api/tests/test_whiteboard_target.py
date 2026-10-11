from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from dev_accounts import dev_login


def _create_space_whiteboard(
    client: TestClient,
    token: str,
    space_id: str,
    *,
    title: str,
    sort_order: int,
) -> dict:
    response = client.post(
        "/api/v1/whiteboard/items",
        headers=_auth_headers(token),
        json={
            "title": title,
            "source_app": "pms",
            "source_kind": "manual",
            "primary_target": {
                "company_admin_read_acknowledged": True,
                "app": "pms",
                "type": "space",
                "id": space_id,
                "sort_order": sort_order,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list_slot(
    client: TestClient,
    token: str,
    task_list_id: str,
    title: str,
) -> dict:
    response = client.post(
        "/api/v1/whiteboard/contexts/slot",
        headers=_auth_headers(token),
        json={
            "app": "pms",
            "type": "task_list",
            "id": task_list_id,
            "title": title,
            "company_admin_read_acknowledged": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_meeting_slot(
    client: TestClient,
    token: str,
    meeting_id: str,
    title: str,
) -> dict:
    response = client.post(
        "/api/v1/whiteboard/contexts/slot",
        headers=_auth_headers(token),
        json={
            "app": "meeting",
            "type": "meeting",
            "id": meeting_id,
            "title": title,
            "company_admin_read_acknowledged": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_meeting(client: TestClient, token: str, *, title: str) -> dict:
    start = datetime(2031, 1, 1, 10, 0, 0)
    response = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(token),
        json={
            "title": title,
            "agenda": "",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(),
            "attendees": [],
            "task_ids": [],
            "doc_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list(client: TestClient, token: str, *, key: str, name: str) -> dict:
    from test_meeting import _create_task_list as create_pms_list

    return create_pms_list(client, token, key=key, name=name)


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_context_slot_replace_and_detach_keep_exact_board_identity(client, monkeypatch):
    from test_whiteboard_access import _add_space_member
    from test_whiteboard_access_realtime import _capture, _assert_event

    owner = _dev_login(client, "delivery-hub-admin")
    viewer = _dev_login(client, "delivery-hub-member")
    token = owner["token"]
    headers = _auth_headers(token)
    task_list = _create_task_list(client, token, key="WBSLOT", name="Whiteboard slot")
    previous = _create_task_list_slot(client, token, task_list["id"], "Previous")
    _add_space_member(client, token, task_list["team_id"], viewer["user"]["id"], "viewer")
    board_path = f"/api/v1/whiteboard/items/{previous['id']}"
    assert client.get(board_path, headers=_auth_headers(viewer["token"])).status_code == 200
    scene = {"elements": [{"id": "member-edit"}], "appState": {}, "files": {}}
    assert (
        client.patch(
            board_path, headers=_auth_headers(viewer["token"]), json={"scene": scene}
        ).status_code
        == 403
    )
    _add_space_member(client, token, task_list["team_id"], viewer["user"]["id"], "member")
    assert (
        client.patch(
            board_path, headers=_auth_headers(viewer["token"]), json={"scene": scene}
        ).status_code
        == 200
    )
    events, globals_sent = _capture(client, monkeypatch)
    replacement = _create_task_list_slot(client, token, task_list["id"], "Replacement")
    _assert_event(events, globals_sent, previous["id"])
    query = {"app": "pms", "type": "task_list", "id": task_list["id"]}
    slot = client.get("/api/v1/whiteboard/contexts/slot", headers=headers, params=query)
    assert slot.status_code == 200 and slot.json()["item"]["id"] == replacement["id"]
    reloaded = client.get(board_path, headers=headers)
    assert reloaded.status_code == 200 and all(
        t["type"] != "task_list" for t in reloaded.json()["targets"]
    )
    restored = client.put(
        "/api/v1/whiteboard/contexts/slot",
        headers=headers,
        json=query | {"whiteboard_id": previous["id"], "company_admin_read_acknowledged": True},
    )
    assert restored.status_code == 200
    assert {topic for topic, _ in events} == {
        f"whiteboard.access:{previous['id']}",
        f"whiteboard.access:{replacement['id']}",
    }
    assert globals_sent == []
    events.clear()
    assert (
        client.delete("/api/v1/whiteboard/contexts/slot", headers=headers, params=query).status_code
        == 204
    )
    _assert_event(events, globals_sent, previous["id"])
    meeting = _create_meeting(client, token, title="Meeting slot")
    meeting_board = _create_meeting_slot(client, token, meeting["id"], "Meeting board")
    detail = client.get(f"/api/v1/meeting/meetings/{meeting['id']}", headers=headers)
    assert (
        detail.status_code == 200
        and detail.json()["whiteboard_link"]["whiteboard_id"] == meeting_board["id"]
    )
