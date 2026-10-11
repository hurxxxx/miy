from fastapi.testclient import TestClient

from dev_accounts import dev_login
from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import CompanyAppControl


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def test_docs_hub_reuses_pms_acl_and_blocks_resharing_of_source_docs(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)

    task_list = _create_task_list(client, admin["token"], key="DOCS", name="Docs Source List")

    space_doc = _create_space_doc(
        client, admin["token"], task_list["team_id"], title="Space Handbook"
    )
    original_space_page = _create_doc_page(
        client,
        admin["token"],
        space_doc["id"],
        title="Overview",
        content_blocks=[],
    )

    viewer = _create_user(
        client, admin["token"], email="docs-viewer@miy.local", full_name="Docs Viewer"
    )
    _add_task_list_member(client, admin["token"], task_list["id"], viewer["user"]["id"], "viewer")
    viewer_token = _login(client, viewer["user"]["email"], viewer["temporary_password"])

    viewer_hub_response = client.get("/api/v1/docs/hub", headers=_auth_headers(viewer_token))
    assert viewer_hub_response.status_code == 200
    viewer_items = {item["title"]: item for item in viewer_hub_response.json()["items"]}
    assert viewer_items["Space Handbook"]["source_app"] == "pms"
    assert viewer_items["Space Handbook"]["primary_target"]["app"] == "pms"
    assert viewer_items["Space Handbook"]["primary_target"]["type"] == "space"
    assert viewer_items["Space Handbook"]["primary_target"]["id"] == task_list["team_id"]
    assert viewer_items["Space Handbook"]["can_edit"] is False
    assert viewer_items["Space Handbook"]["can_manage"] is False

    viewer_pages_response = client.get(
        f"/api/v1/docs/items/{viewer_items['Space Handbook']['id']}/pages",
        headers=_auth_headers(viewer_token),
    )
    assert viewer_pages_response.status_code == 200
    viewer_page = viewer_pages_response.json()["items"][0]
    assert viewer_page["can_edit"] is False

    viewer_page_update_response = client.patch(
        f"/api/v1/docs/pages/{viewer_page['id']}",
        headers=_auth_headers(viewer_token),
        json={"content_blocks": [{"type": "paragraph", "content": "blocked"}]},
    )
    assert viewer_page_update_response.status_code == 403

    viewer_share_response = client.get(
        f"/api/v1/docs/items/{viewer_items['Space Handbook']['id']}/sharing",
        headers=_auth_headers(viewer_token),
    )
    assert viewer_share_response.status_code == 403

    member = _create_user(
        client, admin["token"], email="docs-user@miy.local", full_name="Docs User"
    )
    _add_task_list_member(client, admin["token"], task_list["id"], member["user"]["id"], "member")
    member_token = _login(client, member["user"]["email"], member["temporary_password"])

    member_hub_response = client.get("/api/v1/docs/hub", headers=_auth_headers(member_token))
    assert member_hub_response.status_code == 200
    member_items = {item["title"]: item for item in member_hub_response.json()["items"]}
    assert member_items["Space Handbook"]["can_edit"] is True
    assert member_items["Space Handbook"]["can_manage"] is False

    member_create_page_response = client.post(
        f"/api/v1/docs/items/{member_items['Space Handbook']['id']}/pages",
        headers=_auth_headers(member_token),
        json={"title": "Member Page"},
    )
    assert member_create_page_response.status_code == 201
    member_created_page = member_create_page_response.json()
    assert member_created_page["created_by_id"] == member["user"]["id"]
    assert member_created_page["created_by_name"] == "Docs User"

    member_delete_space_doc_response = client.delete(
        f"/api/v1/docs/items/{member_items['Space Handbook']['id']}",
        headers=_auth_headers(member_token),
    )
    assert member_delete_space_doc_response.status_code == 403

    original_space_page_lookup_response = client.get(
        f"/api/v1/docs/items/{member_items['Space Handbook']['id']}/pages",
        headers=_auth_headers(member_token),
    )
    assert original_space_page_lookup_response.status_code == 200
    overview_page = next(
        item
        for item in original_space_page_lookup_response.json()["items"]
        if item["source_page_id"] == original_space_page["id"]
    )

    update_space_page_response = client.patch(
        f"/api/v1/docs/pages/{overview_page['id']}",
        headers=_auth_headers(member_token),
        json={"content_blocks": [{"type": "paragraph", "content": "space edit"}]},
    )
    assert update_space_page_response.status_code == 200


def test_internal_shared_links_require_auth_and_honor_read_vs_edit(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)

    owner = _create_user(
        client, admin["token"], email="share-owner@miy.local", full_name="Share Owner"
    )
    owner_token = _login(client, owner["user"]["email"], owner["temporary_password"])

    recipient = _create_user(
        client,
        admin["token"],
        email="share-recipient@miy.local",
        full_name="Share Recipient",
    )
    recipient_token = _login(client, recipient["user"]["email"], recipient["temporary_password"])

    create_doc_response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(owner_token),
        json={"title": "Shared Draft"},
    )
    assert create_doc_response.status_code == 201
    doc = create_doc_response.json()

    pages_response = client.get(
        f"/api/v1/docs/items/{doc['id']}/pages",
        headers=_auth_headers(owner_token),
    )
    assert pages_response.status_code == 200
    page = pages_response.json()["items"][0]

    private_hub = client.get("/api/v1/docs/hub", headers=_auth_headers(recipient_token))
    assert private_hub.status_code == 200
    assert doc["id"] not in {item["id"] for item in private_hub.json()["items"]}
    direct_share = client.put(
        f"/api/v1/docs/items/{doc['id']}/sharing/users/{recipient['user']['id']}",
        headers=_auth_headers(owner_token),
        json={"access_level": "read"},
    )
    assert direct_share.status_code == 200, direct_share.text
    shared_hub = client.get("/api/v1/docs/hub", headers=_auth_headers(recipient_token))
    assert shared_hub.status_code == 200
    shared = next(item for item in shared_hub.json()["items"] if item["id"] == doc["id"])
    assert not shared["can_edit"] and not shared["can_share"]
    denied_direct_edit = client.patch(
        f"/api/v1/docs/pages/{page['id']}",
        headers=_auth_headers(recipient_token),
        json={"content_blocks": [{"type": "paragraph", "content": "blocked"}]},
    )
    assert denied_direct_edit.status_code == 403

    enable_read_link_response = client.put(
        f"/api/v1/docs/items/{doc['id']}/sharing/link",
        headers=_auth_headers(owner_token),
        json={"access_level": "read", "active": True},
    )
    assert enable_read_link_response.status_code == 200
    share_token = enable_read_link_response.json()["link_share"]["token"]
    assert enable_read_link_response.json()["link_share"]["share_path"] == (
        f"/apps/docs/shared/{share_token}"
    )

    unauthenticated_response = client.get(f"/api/v1/docs/shared-links/{share_token}")
    assert unauthenticated_response.status_code == 401

    resolve_read_link_response = client.get(
        f"/api/v1/docs/shared-links/{share_token}",
        headers=_auth_headers(recipient_token),
    )
    assert resolve_read_link_response.status_code == 200
    assert resolve_read_link_response.json()["item"]["can_edit"] is False

    read_edit_attempt_response = client.patch(
        f"/api/v1/docs/pages/{page['id']}?share_token={share_token}",
        headers=_auth_headers(recipient_token),
        json={"content_blocks": [{"type": "paragraph", "content": "blocked"}]},
    )
    assert read_edit_attempt_response.status_code == 403

    enable_edit_link_response = client.put(
        f"/api/v1/docs/items/{doc['id']}/sharing/link",
        headers=_auth_headers(owner_token),
        json={"access_level": "edit", "active": True},
    )
    assert enable_edit_link_response.status_code == 200
    updated_share_token = enable_edit_link_response.json()["link_share"]["token"]

    resolve_edit_link_response = client.get(
        f"/api/v1/docs/shared-links/{updated_share_token}",
        headers=_auth_headers(recipient_token),
    )
    assert resolve_edit_link_response.status_code == 200
    assert resolve_edit_link_response.json()["item"]["can_edit"] is True

    edit_via_link_response = client.patch(
        f"/api/v1/docs/pages/{page['id']}?share_token={updated_share_token}",
        headers=_auth_headers(recipient_token),
        json={"content_blocks": [{"type": "paragraph", "content": "allowed"}]},
    )
    assert edit_via_link_response.status_code == 200

    with get_session_factory()() as db:
        control = db.get(CompanyAppControl, "docs")
        assert control is not None
        control.enabled = False
        db.add(control)
        db.commit()

    disabled_response = client.get(
        f"/api/v1/docs/shared-links/{updated_share_token}",
        headers=_auth_headers(recipient_token),
    )
    assert disabled_response.status_code == 403
    assert disabled_response.json()["code"] == "app.access_required"


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


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"login_id": email.split("@", 1)[0].lower(), "password": password},
    )
    assert response.status_code == 200
    return response.json()["token"]


def _create_task_list(
    client: TestClient,
    token: str,
    *,
    key: str,
    name: str,
    team_id: str | None = None,
) -> dict:
    payload = {
        "key": key,
        "name": name,
        "description": f"{name} description",
    }
    if team_id is None:
        space_response = client.post(
            "/api/v1/pms/spaces", headers=_auth_headers(token), json={"name": name}
        )
        assert space_response.status_code == 201, space_response.text
        team_id = space_response.json()["id"]
    payload["team_id"] = team_id
    response = client.post(
        "/api/v1/pms/lists",
        headers=_auth_headers(token),
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def _create_space(client: TestClient, token: str, *, name: str) -> dict:
    response = client.post(
        "/api/v1/pms/spaces",
        headers=_auth_headers(token),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(
    client: TestClient,
    token: str,
    list_id: str,
    *,
    title: str,
) -> dict:
    response = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": "",
            "status": "todo",
            "priority": "medium",
            "assignee_id": None,
            "milestone_id": None,
            "parent_id": None,
            "label_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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


def _create_space_doc(client: TestClient, token: str, space_id: str, *, title: str) -> dict:
    response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(token),
        json={
            "title": title,
            "source_app": "pms",
            "source_kind": "manual",
            "primary_target": {
                "app": "pms",
                "type": "space",
                "id": space_id,
                "company_admin_read_acknowledged": True,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_native_doc(client: TestClient, token: str, *, title: str) -> dict:
    response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(token),
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _attach_task_doc(client: TestClient, token: str, task_id: str, doc_id: str) -> None:
    response = client.post(
        f"/api/v1/pms/tasks/{task_id}/docs",
        headers=_auth_headers(token),
        json={"doc_id": doc_id},
    )
    assert response.status_code == 201, response.text


def _update_doc_target(client: TestClient, token: str, doc_id: str, space_id: str) -> None:
    response = client.put(
        f"/api/v1/docs/items/{doc_id}/target",
        headers=_auth_headers(token),
        json={
            "app": "pms",
            "type": "space",
            "id": space_id,
        },
    )
    assert response.status_code == 200, response.text


def _list_space_docs(client: TestClient, token: str, space_id: str) -> list[dict]:
    response = client.get(
        "/api/v1/docs/hub",
        headers=_auth_headers(token),
        params={
            "view": "all",
            "space_id": space_id,
            "sort_by": "target_sort_order",
            "sort_dir": "asc",
            "page_size": 200,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _create_doc_page(
    client: TestClient,
    token: str,
    doc_id: str,
    *,
    title: str,
    parent_id: str | None = None,
    content_blocks: list[dict] | None = None,
    sort_order: int | None = None,
) -> dict:
    payload: dict[str, object] = {"title": title}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if content_blocks is not None:
        payload["content_blocks"] = content_blocks
    if sort_order is not None:
        payload["sort_order"] = sort_order
    response = client.post(
        f"/api/v1/docs/items/{doc_id}/pages",
        headers=_auth_headers(token),
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _list_doc_pages(client: TestClient, token: str, doc_id: str) -> list[dict]:
    response = client.get(
        f"/api/v1/docs/items/{doc_id}/pages",
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _get_doc_item(
    client: TestClient,
    token: str,
    doc_id: str,
) -> dict:
    response = client.get(
        f"/api/v1/docs/items/{doc_id}",
        headers=_auth_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
