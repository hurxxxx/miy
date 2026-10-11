from fastapi.testclient import TestClient

from test_pms_issues import (
    _add_task_list_member,
    _auth_headers,
    _bootstrap_admin_session,
    _create_issue,
    _create_task_list,
    _create_user,
    _login,
)


def _create_task_list_user(
    client: TestClient,
    *,
    admin_token: str,
    task_list_id: str,
    email: str,
    full_name: str,
    role: str,
) -> str:
    user = _create_user(client, admin_token, email=email, full_name=full_name)
    _add_task_list_member(client, admin_token, task_list_id, user["user"]["id"], role)
    return _login(client, user["user"]["email"], user["temporary_password"])


def test_custom_fields_values_wrong_list_and_permissions(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)
    headers = _auth_headers(admin["token"])
    task_list = _create_task_list(client, admin["token"], key="CUSTA", name="Owned list")
    other_list = _create_task_list(client, admin["token"], key="CUSTB", name="Foreign list")
    task = _create_issue(client, admin["token"], task_list["id"], title="Bound field")
    owned = client.post(
        f"/api/v1/pms/lists/{task_list['id']}/custom-fields",
        headers=headers,
        json={"name": "Owned field", "field_type": "text"},
    )
    foreign = client.post(
        f"/api/v1/pms/lists/{other_list['id']}/custom-fields",
        headers=headers,
        json={"name": "Foreign field", "field_type": "text"},
    )
    assert owned.status_code == foreign.status_code == 201
    values_path = f"/api/v1/pms/tasks/{task['id']}/custom-field-values"
    saved = client.put(
        values_path, headers=headers, json={"field_id": owned.json()["id"], "value": "Preserved"}
    )
    assert saved.status_code == 200
    denied = client.put(
        values_path, headers=headers, json={"field_id": foreign.json()["id"], "value": "Wrong list"}
    )
    assert denied.status_code == 400
    assert denied.json()["code"] == "pms.custom_field_wrong_list"
    values = client.get(values_path, headers=headers)
    assert values.status_code == 200
    assert values.json() == [{"field_id": owned.json()["id"], "value": "Preserved"}]
