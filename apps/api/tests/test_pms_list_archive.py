from __future__ import annotations


from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.pms.search_projection import (
    load_pms_task_search_document,
)
from miy_api.domains.rag.pms_projection import load_task_projection
from test_pms_issues import (
    _auth_headers,
    _bootstrap_admin_session,
    _create_issue,
    _create_task_list,
)


BASE_PATH = "/api/v1/pms"


def _update_list(
    client: TestClient,
    token: str,
    list_id: str,
    payload: dict[str, object],
):
    return client.patch(
        f"/api/v1/pms/lists/{list_id}",
        headers=_auth_headers(token),
        json=payload,
    )


def test_list_archive_restore_filters_preserve_state_and_gate_writes(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)
    token, headers = admin["token"], _auth_headers(admin["token"])
    task_list = _create_task_list(client, token, key="ARCH", name="Archive contract")
    task = _create_issue(
        client,
        token,
        task_list["id"],
        title="Preserved task",
        assignee_id=admin["user"]["id"],
        due_date="2026-07-17",
    )
    assigned = client.get(f"{BASE_PATH}/tasks/assigned", headers=headers)
    assert assigned.status_code == 200
    assert task["id"] in {item["id"] for item in assigned.json()["items"]}
    assert _update_list(client, token, task_list["id"], {"archived": True}).status_code == 200
    archived = client.get(
        f"{BASE_PATH}/lists", headers=headers, params={"archived": "false", "page_size": 100}
    )
    assert archived.status_code == 200
    assert task_list["id"] not in {item["id"] for item in archived.json()["items"]}
    assigned = client.get(f"{BASE_PATH}/tasks/assigned", headers=headers)
    assert assigned.status_code == 200
    assert task["id"] not in {item["id"] for item in assigned.json()["items"]}
    with get_session_factory()() as db:
        assert load_pms_task_search_document(db, task_id=task["id"]) is None
        assert load_task_projection(db, task_id=task["id"]) is None
    denied = client.patch(
        f"{BASE_PATH}/tasks/{task['id']}", headers=headers, json={"title": "Blocked"}
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "pms.task_list_archived_read_only"
    archived_detail = client.get(f"{BASE_PATH}/tasks/{task['id']}", headers=headers)
    assert archived_detail.status_code == 200
    assert archived_detail.json()["task"]["title"] == "Preserved task"
    restored = _update_list(client, token, task_list["id"], {"archived": False})
    assert restored.status_code == 200 and not restored.json()["archived"]
    assigned = client.get(f"{BASE_PATH}/tasks/assigned", headers=headers)
    assert task["id"] in {item["id"] for item in assigned.json()["items"]}
    assert (
        client.delete(f"{BASE_PATH}/spaces/{task_list['team_id']}", headers=headers).status_code
        == 204
    )
    assert client.get(f"{BASE_PATH}/tasks/{task['id']}", headers=headers).status_code == 403
    assert (
        client.post(
            f"{BASE_PATH}/lists",
            headers=headers,
            json={"key": "RECOVER", "name": "Implicit", "team_id": task_list["team_id"]},
        ).status_code
        == 404
    )
    from miy_api.domains.pms.space_models import Team
    from miy_api.domains.pms.models import Task

    with get_session_factory()() as db:
        assert db.get(Team, task_list["team_id"]).trashed_at is not None
        assert db.get(Task, task["id"]) is not None
