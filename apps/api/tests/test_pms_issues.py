from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Event, Lock

from fastapi.testclient import TestClient
import pytest

from miy_api.core.db import get_session_factory
from miy_api.domains.pms import service as pms_service
from miy_api.domains.search import outbox as search_outbox
from dev_accounts import dev_login
from test_docs_hub import _create_doc_page, _create_space_doc, _list_doc_pages, _list_space_docs


@pytest.fixture(autouse=True)
def _isolate_search_index_publication_from_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(search_outbox, "_publish_job", lambda *, job_id: None)


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def test_concurrent_assignee_updates_are_idempotent(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap_admin(client)
    task_list = _create_task_list(client, token)
    teammate = _create_user(
        client,
        token,
        email="concurrent-assignee@miy.local",
        full_name="Concurrent Assignee",
    )
    assignee_id = teammate["user"]["id"]
    _add_task_list_member(client, token, task_list["id"], assignee_id, "member")
    issue = _create_issue(client, token, task_list["id"], title="Concurrent assignee")

    original_get_task_for_user = pms_service._get_task_for_user
    readers_ready = Barrier(2)

    def synchronized_get_task_for_user(*args, **kwargs):
        result = original_get_task_for_user(*args, **kwargs)
        try:
            readers_ready.wait(timeout=0.5)
        except BrokenBarrierError:
            pass
        return result

    monkeypatch.setattr(
        pms_service,
        "_get_task_for_user",
        synchronized_get_task_for_user,
    )

    def assign_task():
        try:
            return client.patch(
                f"/api/v1/pms/tasks/{issue['id']}",
                headers=_auth_headers(token),
                json={"assignee_ids": [assignee_id]},
            )
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: assign_task(), range(2)))

    assert all(getattr(result, "status_code", None) == 200 for result in results), results


def test_task_reorder_rejects_parent_cycles_without_partial_write(
    client: TestClient,
) -> None:
    token = _bootstrap_admin(client)
    task_list = _create_task_list(client, token, key="REORDCYC", name="Reorder Cycle List")
    parent = _create_issue(client, token, task_list["id"], title="Parent task")
    child = _create_issue(
        client,
        token,
        task_list["id"],
        title="Child task",
        parent_id=parent["id"],
    )

    response = client.patch(
        f"/api/v1/pms/lists/{task_list['id']}/tasks/reorder",
        headers=_auth_headers(token),
        json={
            "items": [
                {
                    "task_id": parent["id"],
                    "board_position": 9000,
                    "parent_id": child["id"],
                },
                {"task_id": child["id"], "board_position": 8000},
            ],
        },
    )

    assert response.status_code == 409, response.text
    list_response = client.get(
        f"/api/v1/pms/lists/{task_list['id']}/tasks",
        headers=_auth_headers(token),
    )
    assert list_response.status_code == 200, list_response.text
    listed_by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert listed_by_id[parent["id"]]["parent_id"] is None
    assert listed_by_id[parent["id"]]["board_position"] == parent["board_position"]
    assert listed_by_id[child["id"]]["parent_id"] == parent["id"]
    assert listed_by_id[child["id"]]["board_position"] == child["board_position"]


def test_concurrent_subtask_unlinks_keep_root_positions_consistent(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap_admin(client)
    task_list = _create_task_list(client, token, key="UNLINKRACE", name="Unlink Race List")
    first_parent = _create_issue(client, token, task_list["id"], title="First parent")
    first_child = _create_issue(client, token, task_list["id"], title="First child")
    second_parent = _create_issue(client, token, task_list["id"], title="Second parent")
    second_child = _create_issue(client, token, task_list["id"], title="Second child")
    nest_response = client.patch(
        f"/api/v1/pms/lists/{task_list['id']}/tasks/reorder",
        headers=_auth_headers(token),
        json={
            "items": [
                {
                    "task_id": first_child["id"],
                    "board_position": 1000,
                    "parent_id": first_parent["id"],
                },
                {
                    "task_id": second_child["id"],
                    "board_position": 1000,
                    "parent_id": second_parent["id"],
                },
            ],
        },
    )
    assert nest_response.status_code == 200, nest_response.text

    original_get_task_for_user = pms_service._get_task_for_user
    readers_ready = Barrier(2)

    def synchronized_get_task_for_user(*args, **kwargs):
        result = original_get_task_for_user(*args, **kwargs)
        try:
            readers_ready.wait(timeout=0.5)
        except BrokenBarrierError:
            pass
        return result

    monkeypatch.setattr(
        pms_service,
        "_get_task_for_user",
        synchronized_get_task_for_user,
    )

    def unlink_task(task_id: str):
        return client.patch(
            f"/api/v1/pms/tasks/{task_id}",
            headers=_auth_headers(token),
            json={"parent_id": None},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(unlink_task, [first_child["id"], second_child["id"]]))
    assert all(response.status_code == 200 for response in responses)

    list_response = client.get(
        f"/api/v1/pms/lists/{task_list['id']}/tasks",
        headers=_auth_headers(token),
    )
    assert list_response.status_code == 200, list_response.text
    roots = [item for item in list_response.json()["items"] if item["parent_id"] is None]
    assert [item["id"] for item in roots] == [
        first_parent["id"],
        first_child["id"],
        second_parent["id"],
        second_child["id"],
    ]
    assert len({item["board_position"] for item in roots}) == len(roots)


def test_unlink_and_root_reorder_do_not_deadlock(
    client: TestClient,
    monkeypatch,
) -> None:
    token = _bootstrap_admin(client)
    task_list = _create_task_list(client, token, key="UNLINKLOCK", name="Unlink Lock List")
    parent = _create_issue(client, token, task_list["id"], title="Parent")
    root_to_move = _create_issue(client, token, task_list["id"], title="Other root")
    child = _create_issue(client, token, task_list["id"], title="Child")
    nest_response = client.patch(
        f"/api/v1/pms/lists/{task_list['id']}/tasks/reorder",
        headers=_auth_headers(token),
        json={
            "items": [
                {
                    "task_id": child["id"],
                    "board_position": 1000,
                    "parent_id": parent["id"],
                }
            ],
        },
    )
    assert nest_response.status_code == 200, nest_response.text

    task_rows_locked = Barrier(2)
    unlink_list_locked = Event()
    role_assignment_lock = Lock()
    roles_by_session: dict[int, str] = {}
    unassigned_lock_calls = 0
    original_get_task_for_user = pms_service._get_task_for_user
    original_lock_task_list_order = pms_service._lock_task_list_order

    def synchronized_get_task_for_user(db, user, task_id, **kwargs):
        if task_id == child["id"]:
            roles_by_session[id(db)] = "unlink"
        elif task_id == root_to_move["id"]:
            roles_by_session[id(db)] = "root"
        result = original_get_task_for_user(db, user, task_id, **kwargs)
        try:
            task_rows_locked.wait(timeout=0.5)
        except BrokenBarrierError:
            pass
        return result

    def synchronized_lock_task_list_order(db, list_id):
        nonlocal unassigned_lock_calls
        role = roles_by_session.get(id(db))
        if role is None:
            with role_assignment_lock:
                role = "unlink" if unassigned_lock_calls == 0 else "root"
                unassigned_lock_calls += 1
        if role == "unlink":
            result = original_lock_task_list_order(db, list_id)
            unlink_list_locked.set()
            return result
        if role == "root":
            assert unlink_list_locked.wait(timeout=2)
        return original_lock_task_list_order(db, list_id)

    monkeypatch.setattr(
        pms_service,
        "_get_task_for_user",
        synchronized_get_task_for_user,
    )
    monkeypatch.setattr(
        pms_service,
        "_lock_task_list_order",
        synchronized_lock_task_list_order,
    )

    def patch_task(task_id: str, payload: dict):
        try:
            return client.patch(
                f"/api/v1/pms/tasks/{task_id}",
                headers=_auth_headers(token),
                json=payload,
            )
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        unlink_future = executor.submit(patch_task, child["id"], {"parent_id": None})
        reorder_future = executor.submit(
            patch_task,
            root_to_move["id"],
            {"board_position": root_to_move["board_position"] + 500},
        )
        results = [unlink_future.result(), reorder_future.result()]

    assert all(getattr(result, "status_code", None) == 200 for result in results), results


def test_viewer_cannot_modify_issue_comment_or_folder(client: TestClient, monkeypatch) -> None:
    admin_session = _bootstrap_admin_session(client)
    task_list = _create_task_list(client, admin_session["token"])
    issue = _create_issue(client, admin_session["token"], task_list["id"], title="Protected issue")

    viewer = _create_user(
        client, admin_session["token"], email="viewer@miy.local", full_name="Viewer User"
    )
    _add_task_list_member(
        client, admin_session["token"], task_list["id"], viewer["user"]["id"], "viewer"
    )
    viewer_token = _login(client, viewer["user"]["email"], viewer["temporary_password"])

    update_response = client.patch(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(viewer_token),
        json={"title": "Viewer edit attempt"},
    )
    assert update_response.status_code == 403

    comment_response = client.post(
        f"/api/v1/pms/tasks/{issue['id']}/comments",
        headers=_auth_headers(viewer_token),
        json={"body": "viewer comment"},
    )
    assert comment_response.status_code == 403

    folder_response = client.post(
        "/api/v1/pms/folders",
        headers=_auth_headers(viewer_token),
        json={"name": "Viewer folder", "team_id": task_list["team_id"]},
    )
    assert folder_response.status_code == 403

    space_doc_response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(viewer_token),
        json={
            "title": "Viewer collection",
            "source_app": "pms",
            "source_kind": "manual",
            "primary_target": {
                "app": "pms",
                "type": "space",
                "id": task_list["team_id"],
            },
        },
    )
    assert space_doc_response.status_code == 403

    from test_pms_attachments import _FakeTaskAttachmentStore, _install_fake_store

    _install_fake_store(monkeypatch, _FakeTaskAttachmentStore())
    upload = client.post(
        f"/api/v1/pms/tasks/{issue['id']}/attachments",
        headers=_auth_headers(admin_session["token"]),
        files={"file": ("admin.txt", b"payload", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    denied_upload = client.post(
        f"/api/v1/pms/tasks/{issue['id']}/attachments",
        headers=_auth_headers(viewer_token),
        files={"file": ("viewer.txt", b"payload", "text/plain")},
    )
    assert denied_upload.status_code == 403
    denied_delete = client.delete(
        f"/api/v1/pms/attachments/{upload.json()['id']}",
        headers=_auth_headers(viewer_token),
    )
    assert denied_delete.status_code == 403


def test_space_docs_collection_permissions_and_soft_delete(client: TestClient) -> None:
    admin_session = _bootstrap_admin_session(client)
    task_list = _create_task_list(client, admin_session["token"])
    space_id = task_list["team_id"]
    assert space_id is not None

    collection = _create_space_doc(
        client,
        admin_session["token"],
        space_id,
        title="Engineering Handbook",
    )

    first_page = _create_doc_page(
        client,
        admin_session["token"],
        collection["id"],
        title="Overview",
    )

    child_page = _create_doc_page(
        client,
        admin_session["token"],
        collection["id"],
        title="Checklist",
        parent_id=first_page["id"],
    )

    outsider = _create_user(
        client,
        admin_session["token"],
        email="space-outsider@miy.local",
        full_name="Space Outsider",
    )
    outsider_token = _login(client, outsider["user"]["email"], outsider["temporary_password"])

    outsider_list_response = client.get(
        "/api/v1/docs/hub",
        headers=_auth_headers(outsider_token),
        params={"space_id": space_id},
    )
    assert outsider_list_response.status_code == 200
    assert outsider_list_response.json()["items"] == []

    outsider_create_response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(outsider_token),
        json={
            "title": "Forbidden",
            "source_app": "pms",
            "source_kind": "manual",
            "primary_target": {"app": "pms", "type": "space", "id": space_id},
        },
    )
    assert outsider_create_response.status_code == 403

    task_list_editor = _create_user(
        client,
        admin_session["token"],
        email="space-editor@miy.local",
        full_name="Task List Editor",
    )
    _add_task_list_member(
        client, admin_session["token"], task_list["id"], task_list_editor["user"]["id"], "admin"
    )
    task_list_editor_token = _login(
        client,
        task_list_editor["user"]["email"],
        task_list_editor["temporary_password"],
    )

    editor_docs = _list_space_docs(client, task_list_editor_token, space_id)
    assert [item["id"] for item in editor_docs] == [collection["id"]]

    member_collection = _create_space_doc(
        client,
        task_list_editor_token,
        space_id,
        title="Task List Notes",
    )
    assert member_collection["created_by_id"] == task_list_editor["user"]["id"]

    member_page = _create_doc_page(
        client,
        task_list_editor_token,
        collection["id"],
        title="Member page",
    )
    assert member_page["doc_id"] == collection["id"]

    member_folder_response = client.post(
        "/api/v1/pms/folders",
        headers=_auth_headers(task_list_editor_token),
        json={"name": "Member folder", "team_id": space_id},
    )
    assert member_folder_response.status_code == 201
    member_folder = member_folder_response.json()
    assert member_folder["team_id"] == space_id

    second_collection = _create_space_doc(
        client,
        admin_session["token"],
        space_id,
        title="Admin Notes",
    )

    cross_collection_parent_response = client.post(
        f"/api/v1/docs/items/{second_collection['id']}/pages",
        headers=_auth_headers(admin_session["token"]),
        json={
            "title": "Invalid child",
            "parent_id": first_page["id"],
        },
    )
    assert cross_collection_parent_response.status_code == 404
    assert cross_collection_parent_response.json()["code"] == "docs.parent_page_not_found"

    delete_collection_response = client.delete(
        f"/api/v1/docs/items/{collection['id']}",
        headers=_auth_headers(admin_session["token"]),
    )
    assert delete_collection_response.status_code == 204

    visible_ids = sorted(
        item["id"] for item in _list_space_docs(client, admin_session["token"], space_id)
    )
    assert visible_ids == sorted([member_collection["id"], second_collection["id"]])

    deleted_collection_response = client.get(
        f"/api/v1/docs/items/{collection['id']}",
        headers=_auth_headers(admin_session["token"]),
    )
    assert deleted_collection_response.status_code == 200
    assert deleted_collection_response.json()["trashed_at"] is not None

    deleted_page_response = client.get(
        f"/api/v1/docs/pages/{first_page['id']}",
        headers=_auth_headers(admin_session["token"]),
    )
    assert deleted_page_response.status_code == 403

    deleted_child_response = client.get(
        f"/api/v1/docs/pages/{child_page['id']}",
        headers=_auth_headers(admin_session["token"]),
    )
    assert deleted_child_response.status_code == 403

    deleted_collection_pages = _list_doc_pages(client, admin_session["token"], collection["id"])
    assert deleted_collection_pages == []


def test_media_linking_follows_parent_resource_acl(client: TestClient) -> None:
    admin_session = _bootstrap_admin_session(client)
    task_list = _create_task_list(client, admin_session["token"])
    space_id = task_list["team_id"]
    assert space_id is not None

    issue = _create_issue(client, admin_session["token"], task_list["id"], title="Media ACL issue")

    collection = _create_space_doc(
        client,
        admin_session["token"],
        space_id,
        title="Space Collection",
    )
    page = _create_doc_page(
        client,
        admin_session["token"],
        collection["id"],
        title="Space Page",
    )

    project_member = _create_user(
        client,
        admin_session["token"],
        email="media-task-list-member@miy.local",
        full_name="Media Task List Member",
    )
    _add_task_list_member(
        client, admin_session["token"], task_list["id"], project_member["user"]["id"], "member"
    )
    project_member_token = _login(
        client,
        project_member["user"]["email"],
        project_member["temporary_password"],
    )

    issue_media = _create_unlinked_media(project_member["user"]["id"])
    issue_link_response = client.post(
        "/api/v1/media/link",
        headers=_auth_headers(project_member_token),
        json={
            "media_ids": [issue_media["id"]],
            "resource_type": "task",
            "resource_id": issue["id"],
        },
    )
    assert issue_link_response.status_code == 204

    removed_doc_media = _create_unlinked_media(project_member["user"]["id"])
    removed_doc_link_response = client.post(
        "/api/v1/media/link",
        headers=_auth_headers(project_member_token),
        json={
            "media_ids": [removed_doc_media["id"]],
            "resource_type": "doc",
            "resource_id": issue["id"],
        },
    )
    assert removed_doc_link_response.status_code == 400

    forbidden_space_media = _create_unlinked_media(project_member["user"]["id"])
    forbidden_space_link_response = client.post(
        "/api/v1/media/link",
        headers=_auth_headers(project_member_token),
        json={
            "media_ids": [forbidden_space_media["id"]],
            "resource_type": "docs_native_page",
            "resource_id": page["id"],
        },
    )
    assert forbidden_space_link_response.status_code == 204

    space_member = _create_user(
        client,
        admin_session["token"],
        email="media-space-member@miy.local",
        full_name="Media Space Member",
    )
    _add_team_member(client, admin_session["token"], space_id, space_member["user"]["id"])
    space_member_token = _login(
        client,
        space_member["user"]["email"],
        space_member["temporary_password"],
    )

    page_media = _create_unlinked_media(space_member["user"]["id"])
    page_link_response = client.post(
        "/api/v1/media/link",
        headers=_auth_headers(space_member_token),
        json={
            "media_ids": [page_media["id"]],
            "resource_type": "docs_native_page",
            "resource_id": page["id"],
        },
    )
    assert page_link_response.status_code == 204


def _bootstrap_admin(client: TestClient) -> str:
    return _bootstrap_admin_session(client)["token"]


def test_assigned_issues_rechecks_app_admission(client: TestClient) -> None:
    admin_session = _bootstrap_admin_session(client)
    _dev_login(client, "delivery-hub-admin")
    ordinary_user = _create_ordinary_user(
        client,
        admin_session["token"],
        email="administrator-assigned-admin@miy.local",
        full_name="Administrator Assigned Admin",
    )
    ordinary_user_token = _login(
        client,
        ordinary_user["user"]["email"],
        ordinary_user["temporary_password"],
    )

    task_list = _create_task_list(
        client,
        ordinary_user_token,
        key="ADMINASGN",
        name="Administrator Assigned Route",
    )
    _create_issue(
        client,
        ordinary_user_token,
        task_list["id"],
        title="Administrator scoped assigned issue",
        assignee_id=ordinary_user["user"]["id"],
    )

    response = client.get(
        "/api/v1/pms/tasks/assigned",
        headers=_auth_headers(ordinary_user_token),
    )
    assert response.status_code == 200
    assert [item["title"] for item in response.json()["items"]] == [
        "Administrator scoped assigned issue"
    ]

    from miy_api.domains.auth.app_access_models import AppAccessPolicy

    with get_session_factory()() as db:
        db.get(AppAccessPolicy, "pms").audience = "selected"
        db.commit()
    denied_response = client.get(
        "/api/v1/pms/tasks/assigned",
        headers=_auth_headers(ordinary_user_token),
    )
    assert denied_response.status_code == 403


def _bootstrap_admin_session(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "full_name": "miy Admin",
            "email": "admin@miy.local",
            "password": "supersecret123",
        },
    )
    assert response.status_code == 201
    session = response.json()
    from dev_accounts import configure_company_app_access
    from miy_api.core.db import get_session_factory

    with get_session_factory()() as db:
        configure_company_app_access(db)
    me_response = client.get(
        "/api/v1/auth/me",
        headers=_auth_headers(session["token"]),
    )
    assert me_response.status_code == 200, me_response.text
    session["user"] = me_response.json()
    return session


def _create_task_list(
    client: TestClient,
    token: str,
    *,
    key: str = "PMS",
    name: str = "PMS List",
) -> dict:
    space_response = client.post(
        "/api/v1/pms/spaces", headers=_auth_headers(token), json={"name": name}
    )
    assert space_response.status_code == 201, space_response.text
    response = client.post(
        "/api/v1/pms/lists",
        headers=_auth_headers(token),
        json={
            "team_id": space_response.json()["id"],
            "key": key,
            "name": name,
            "description": "List for PMS issue tests",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_issue(
    client: TestClient,
    token: str,
    list_id: str,
    *,
    title: str,
    status: str = "todo",
    assignee_id: str | None = None,
    parent_id: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    recurrence_rule: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": "",
            "status": status,
            "priority": "medium",
            "assignee_id": assignee_id,
            "milestone_id": None,
            "parent_id": parent_id,
            "start_date": start_date,
            "due_date": due_date,
            "recurrence_rule": recurrence_rule,
            "label_ids": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_user(client: TestClient, token: str, *, email: str, full_name: str) -> dict:
    response = client.post(
        "/api/v1/admin/users",
        headers=_auth_headers(token),
        json={
            "email": email,
            "full_name": full_name,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    response = client.patch(
        f"/api/v1/admin/users/{payload['user']['id']}",
        headers=_auth_headers(token),
        json={"must_change_password": False},
    )
    assert response.status_code == 200, response.text
    payload["user"] = response.json()
    return payload


def _create_ordinary_user(client: TestClient, token: str, *, email: str, full_name: str) -> dict:
    payload = _create_user(client, token, email=email, full_name=full_name)
    return payload


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"login_id": email.split("@", 1)[0].lower(), "password": password},
    )
    assert response.status_code == 200
    return response.json()["token"]


def _add_task_list_member(
    client: TestClient, token: str, list_id: str, user_id: str, role: str
) -> dict:
    list_response = client.get(
        f"/api/v1/pms/lists/{list_id}",
        headers=_auth_headers(token),
    )
    assert list_response.status_code == 200

    response = client.post(
        f"/api/v1/pms/spaces/{list_response.json()['team_id']}/members",
        headers=_auth_headers(token),
        json={"user_id": user_id, "role": role},
    )
    assert response.status_code == 201
    return response.json()


def _add_team_member(client: TestClient, token: str, team_id: str, user_id: str):
    response = client.post(
        f"/api/v1/pms/spaces/{team_id}/members",
        headers=_auth_headers(token),
        json={"user_id": user_id, "role": "member"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_unlinked_media(uploaded_by_id: str) -> dict[str, str]:
    from miy_api.core.db import get_session_factory
    from miy_api.domains.media.models import MediaFile
    from miy_api.domains.auth.security import new_id

    media_id = new_id()
    db = get_session_factory()()
    try:
        db.add(
            MediaFile(
                id=media_id,
                storage_key=f"media/{uploaded_by_id}/{media_id}/fixture.png",
                filename="fixture.png",
                content_type="image/png",
                size_bytes=128,
                uploaded_by_id=uploaded_by_id,
            )
        )
        db.commit()
    finally:
        db.close()

    return {"id": media_id}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
