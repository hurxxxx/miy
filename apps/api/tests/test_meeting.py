from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient

from dev_accounts import content_headers, dev_login


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _create_company_user(
    client: TestClient,
    admin_token: str,
    *,
    email: str,
    full_name: str,
) -> dict:
    payload_json = {"email": email, "full_name": full_name}
    create_response = client.post(
        "/api/v1/admin/users",
        headers=_auth_headers(admin_token),
        json=payload_json,
    )
    assert create_response.status_code == 201, create_response.text
    payload = create_response.json()

    response = client.patch(
        f"/api/v1/admin/users/{payload['user']['id']}",
        headers=_auth_headers(admin_token),
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


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _create_meeting(
    client: TestClient,
    token: str,
    *,
    title: str = "Sprint planning",
    attendees: list[dict] | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    task_ids: list[str] | None = None,
    doc_ids: list[str] | None = None,
) -> dict:
    start = start_at or datetime(2100, 5, 1, 10, 0, 0)
    end = end_at or (start + timedelta(hours=1))
    response = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(token),
        json={
            "title": title,
            "agenda": "Discuss Q2 roadmap.",
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "attendees": attendees or [],
            "task_ids": task_ids or [],
            "doc_ids": doc_ids or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list(
    client: TestClient,
    token: str,
    *,
    key: str = "MTG",
    name: str = "Meeting Test",
    description: str = "",
    team_id: str | None = None,
) -> dict:
    payload = {
        "key": key,
        "name": name,
        "description": description,
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
    assert response.status_code == 201, response.text
    return response.json()


def _create_issue(
    client: TestClient,
    token: str,
    list_id: str,
    *,
    title: str = "Plan Q2",
    status: str = "todo",
) -> dict:
    response = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": "",
            "status": status,
            "priority": "medium",
            "label_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_meeting_notes_attendee_can_edit_and_loses_access_when_removed(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    attendee = _create_company_user(
        client,
        admin_token,
        email="notes-attendee@miy.local",
        full_name="Notes Attendee",
    )
    attendee_token = _login(
        client,
        attendee["user"]["email"],
        attendee["temporary_password"],
    )

    meeting = _create_meeting(
        client,
        admin_token,
        title="Notes attendee edit",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
    )

    ensure_response = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/notes/ensure",
        headers=_auth_headers(admin_token),
    )
    assert ensure_response.status_code == 200, ensure_response.text
    notes = ensure_response.json()

    pages_response = client.get(
        f"/api/v1/docs/items/{notes['notes_doc_id']}/pages",
        headers=_auth_headers(attendee_token),
    )
    assert pages_response.status_code == 200, pages_response.text
    attendee_page = pages_response.json()["items"][0]
    assert attendee_page["id"] == notes["notes_page_id"]
    assert attendee_page["can_edit"] is True

    update_page_response = client.patch(
        f"/api/v1/docs/pages/{notes['notes_page_id']}",
        headers=_auth_headers(attendee_token),
        json={
            "content_blocks": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Attendee updated notes"}],
                }
            ]
        },
    )
    assert update_page_response.status_code == 200, update_page_response.text

    remove_attendee_response = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin_token),
        json={"attendees": []},
    )
    assert remove_attendee_response.status_code == 200, remove_attendee_response.text

    after_removal_response = client.get(
        f"/api/v1/docs/items/{notes['notes_doc_id']}",
        headers=_auth_headers(attendee_token),
    )
    assert after_removal_response.status_code == 404


def test_meeting_create_rejects_attendees_without_meeting_admission(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    # An invitation cannot implicitly grant admission to the meeting app.
    outsider = _create_company_user(
        client,
        admin_token,
        email="no-meeting-access@miy.local",
        full_name="No Meeting Access",
    )

    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.app_access_models import AppAccessPolicy

    with get_session_factory()() as db:
        db.get(AppAccessPolicy, "meeting").audience = "selected"
        db.commit()
    response = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(admin_token),
        json={
            "title": "Ineligible attendee",
            "agenda": "",
            "start_at": datetime(2026, 5, 1, 10, 0, 0).isoformat(),
            "end_at": datetime(2026, 5, 1, 11, 0, 0).isoformat(),
            "attendees": [{"user_id": outsider["user"]["id"], "role": "required"}],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "meeting.unknown_attendees"


def test_meeting_create_rolls_back_when_initial_attachments_fail(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    before = client.get(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(admin_token),
        params={"scope": "mine"},
    )
    assert before.status_code == 200
    assert before.json()["total"] == 0

    missing_issue = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(admin_token),
        json={
            "title": "Broken issue attach",
            "agenda": "",
            "start_at": datetime(2026, 5, 1, 10, 0, 0).isoformat(),
            "end_at": datetime(2026, 5, 1, 11, 0, 0).isoformat(),
            "attendees": [],
            "task_ids": ["missing-issue"],
        },
    )
    assert missing_issue.status_code == 404

    missing_doc = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(admin_token),
        json={
            "title": "Broken doc attach",
            "agenda": "",
            "start_at": datetime(2026, 5, 1, 10, 0, 0).isoformat(),
            "end_at": datetime(2026, 5, 1, 11, 0, 0).isoformat(),
            "attendees": [],
            "doc_ids": ["missing-doc"],
        },
    )
    assert missing_doc.status_code == 404

    after = client.get(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(admin_token),
        params={"scope": "mine"},
    )
    assert after.status_code == 200
    assert after.json()["total"] == 0


class _FakeMinioClient:
    """Minimal stand-in for the minio client used by file attachment tests.
    Captures put_object calls so assertions can verify the storage path
    without needing a running MinIO container."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.removed: list[str] = []

    def put_object(self, bucket: str, key: str, body, length: int, content_type: str) -> None:
        del bucket, length, content_type
        self.objects[key] = body.read()

    def remove_object(self, bucket: str, key: str) -> None:
        del bucket
        self.removed.append(key)
        self.objects.pop(key, None)

    def open_attachment_object(self, storage_key: str, chunk_size: int):
        del chunk_size
        yield self.objects[storage_key]


def _install_fake_minio(monkeypatch) -> _FakeMinioClient:
    """Patch the meeting service module's storage and URL builder to a
    fake in-memory MinIO so the upload/list/delete paths can be exercised
    without external dependencies."""
    from miy_api.domains.meeting import file_storage as meeting_file_storage

    fake = _FakeMinioClient()
    monkeypatch.setattr(
        meeting_file_storage,
        "put_attachment_object",
        lambda *, storage_key, data, content_type: fake.put_object(
            "bucket",
            storage_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type or meeting_file_storage.DEFAULT_ATTACHMENT_CONTENT_TYPE,
        ),
    )
    monkeypatch.setattr(
        meeting_file_storage,
        "remove_attachment_object",
        lambda storage_key: fake.remove_object("bucket", storage_key),
    )
    monkeypatch.setattr(
        meeting_file_storage,
        "open_attachment_object",
        lambda *, storage_key, chunk_size: fake.open_attachment_object(
            storage_key,
            chunk_size,
        ),
    )
    return fake


def _create_native_doc(client: TestClient, token: str, title: str) -> str:
    response = client.post(
        "/api/v1/docs/items",
        headers=_auth_headers(token),
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


def _native_item_id(doc_id: str) -> str:
    return f"native_doc__{doc_id}"


def test_meeting_attachment_grants_allow_read_but_not_metadata_or_sharing(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    task_list = _create_task_list(client, admin_token, key="ACL", name="ACL List")
    issue = _create_issue(client, admin_token, task_list["id"], title="Meeting-shared issue")
    doc_id = _create_native_doc(client, admin_token, "Meeting-shared doc")

    attendee = _create_company_user(
        client,
        admin_token,
        email="meeting-reader@miy.local",
        full_name="Meeting Reader",
    )
    attendee_token = _login(
        client,
        attendee["user"]["email"],
        attendee["temporary_password"],
    )

    _create_meeting(
        client,
        admin_token,
        title="ACL grant meeting",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
        task_ids=[issue["id"]],
        doc_ids=[doc_id],
    )

    issue_detail = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert issue_detail.status_code == 200, issue_detail.text
    issue_payload = issue_detail.json()
    assert issue_payload["task"]["list_id"] == task_list["id"]
    assert "project_id" not in issue_payload["task"]

    issue_list = client.get(
        f"/api/v1/pms/lists/{task_list['id']}/tasks",
        headers=_auth_headers(attendee_token),
    )
    assert issue_list.status_code == 403

    doc_item = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert doc_item.status_code == 200, doc_item.text
    doc_payload = doc_item.json()
    assert doc_payload["source_id"] == doc_id
    assert doc_payload["can_view"] is True
    assert doc_payload["can_edit"] is False
    assert doc_payload["can_share"] is False
    assert doc_payload["can_manage"] is False

    doc_pages = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}/pages",
        headers=_auth_headers(attendee_token),
    )
    assert doc_pages.status_code == 200, doc_pages.text
    assert len(doc_pages.json()["items"]) == 1

    doc_sharing = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}/sharing",
        headers=_auth_headers(attendee_token),
    )
    assert doc_sharing.status_code == 403


def test_meeting_add_attendee_inherits_existing_task_and_doc_attachment_grants(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    task_list = _create_task_list(client, admin_token, key="LATE", name="Late Grants")
    issue = _create_issue(client, admin_token, task_list["id"], title="Late issue")
    doc_id = _create_native_doc(client, admin_token, "Late doc")

    attendee = _create_company_user(
        client,
        admin_token,
        email="late-reader@miy.local",
        full_name="Late Reader",
    )
    attendee_token = _login(
        client,
        attendee["user"]["email"],
        attendee["temporary_password"],
    )

    meeting = _create_meeting(
        client,
        admin_token,
        title="Late attendee grant meeting",
        task_ids=[issue["id"]],
        doc_ids=[doc_id],
    )

    add_attendee = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/attendees",
        headers=_auth_headers(admin_token),
        json={"attendees": [{"user_id": attendee["user"]["id"], "role": "required"}]},
    )
    assert add_attendee.status_code == 200, add_attendee.text

    issue_detail = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert issue_detail.status_code == 200, issue_detail.text
    doc_item = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert doc_item.status_code == 200, doc_item.text

    expired_update = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin_token),
        json={
            "start_at": "2000-01-01T09:00:00",
            "end_at": "2000-01-01T10:00:00",
        },
    )
    assert expired_update.status_code == 200, expired_update.text

    expired_issue = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert expired_issue.status_code == 403
    expired_doc = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert expired_doc.status_code == 404

    restored_update = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin_token),
        json={
            "start_at": "2100-01-01T09:00:00",
            "end_at": "2100-01-01T10:00:00",
        },
    )
    assert restored_update.status_code == 200, restored_update.text

    restored_issue = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert restored_issue.status_code == 200
    restored_doc = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert restored_doc.status_code == 200

    remove_attendee = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin_token),
        json={"attendees": []},
    )
    assert remove_attendee.status_code == 200, remove_attendee.text

    blocked_issue = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert blocked_issue.status_code == 403
    blocked_doc = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert blocked_doc.status_code == 404


def test_meeting_detach_preserves_other_meeting_grants_until_last_source_is_removed(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    task_list = _create_task_list(client, admin_token, key="SAFE", name="Safety List")
    issue = _create_issue(client, admin_token, task_list["id"], title="Multi-meeting issue")
    doc_id = _create_native_doc(client, admin_token, "Multi-meeting doc")

    attendee = _create_company_user(
        client,
        admin_token,
        email="multi-reader@miy.local",
        full_name="Multi Reader",
    )
    attendee_token = _login(
        client,
        attendee["user"]["email"],
        attendee["temporary_password"],
    )

    meeting_a = _create_meeting(
        client,
        admin_token,
        title="Meeting A",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
        task_ids=[issue["id"]],
        doc_ids=[doc_id],
    )
    meeting_b = _create_meeting(
        client,
        admin_token,
        title="Meeting B",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
        task_ids=[issue["id"]],
        doc_ids=[doc_id],
    )

    first_issue_detach = client.delete(
        f"/api/v1/meeting/meetings/{meeting_a['id']}/tasks/{issue['id']}",
        headers=_auth_headers(admin_token),
    )
    assert first_issue_detach.status_code == 200
    first_doc_detach = client.delete(
        f"/api/v1/meeting/meetings/{meeting_a['id']}/docs/{doc_id}",
        headers=_auth_headers(admin_token),
    )
    assert first_doc_detach.status_code == 200

    still_can_read_issue = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert still_can_read_issue.status_code == 200
    still_can_read_doc = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert still_can_read_doc.status_code == 200

    second_issue_detach = client.delete(
        f"/api/v1/meeting/meetings/{meeting_b['id']}/tasks/{issue['id']}",
        headers=_auth_headers(admin_token),
    )
    assert second_issue_detach.status_code == 200
    second_doc_detach = client.delete(
        f"/api/v1/meeting/meetings/{meeting_b['id']}/docs/{doc_id}",
        headers=_auth_headers(admin_token),
    )
    assert second_doc_detach.status_code == 200

    blocked_issue = client.get(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert blocked_issue.status_code == 403
    blocked_doc = client.get(
        f"/api/v1/docs/items/{_native_item_id(doc_id)}",
        headers=_auth_headers(attendee_token),
    )
    assert blocked_doc.status_code == 404


def test_meeting_file_attachment_upload_and_permission_matrix(
    client: TestClient, monkeypatch
) -> None:
    """End-to-end exercise of the new POST/DELETE /meetings/{id}/files
    routes. Uses an in-memory fake MinIO so no external services are
    required."""
    fake = _install_fake_minio(monkeypatch)

    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    attendee = _create_company_user(
        client,
        admin_token,
        email="filer@miy.local",
        full_name="File Attendee",
    )
    attendee_token = _login(client, attendee["user"]["email"], attendee["temporary_password"])

    meeting = _create_meeting(
        client,
        admin_token,
        title="Files meeting",
        attendees=[{"user_id": attendee["user"]["id"], "role": "required"}],
    )

    # Attendee uploads a prep file → success.
    upload_response = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/files",
        headers=_auth_headers(attendee_token),
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert upload_response.status_code == 200, upload_response.text
    body = upload_response.json()
    assert len(body["file_attachments"]) == 1
    file_meta = body["file_attachments"][0]
    assert file_meta["filename"] == "notes.txt"
    assert file_meta["content_type"] == "text/plain"
    assert file_meta["size_bytes"] == len(b"hello world")
    assert file_meta["added_by_id"] == attendee["user"]["id"]
    assert any("notes.txt" in key for key in fake.objects)

    file_id = file_meta["id"]
    assert file_meta["download_url"].startswith("/api/v1/content#grant=")
    assert "127.0.0.1" not in file_meta["download_url"]
    assert "fake-minio" not in file_meta["download_url"]

    download_response = client.get(
        file_meta["download_url"],
        headers=content_headers(attendee_token, file_meta["download_url"]),
    )
    assert download_response.status_code == 200, download_response.text
    assert download_response.content == b"hello world"
    assert download_response.headers["content-type"].startswith("text/plain")
    assert "notes.txt" in download_response.headers["content-disposition"]

    # GET via meeting detail surfaces the same data.
    detail_response = client.get(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(attendee_token),
    )
    assert detail_response.status_code == 200
    fetched_files = detail_response.json()["file_attachments"]
    assert len(fetched_files) == 1
    assert fetched_files[0]["id"] == file_id

    # Admin uploads their own file as the organizer.
    admin_upload = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/files",
        headers=_auth_headers(admin_token),
        files={"file": ("agenda.md", b"# agenda", "text/markdown")},
    )
    assert admin_upload.status_code == 200
    admin_file_id = next(
        item["id"]
        for item in admin_upload.json()["file_attachments"]
        if item["filename"] == "agenda.md"
    )

    # Attendee tries to delete the organizer's file → 403.
    forbidden = client.delete(
        f"/api/v1/meeting/meetings/{meeting['id']}/files/{admin_file_id}",
        headers=_auth_headers(attendee_token),
    )
    assert forbidden.status_code == 403

    # Attendee deletes their own file → success.
    own_delete = client.delete(
        f"/api/v1/meeting/meetings/{meeting['id']}/files/{file_id}",
        headers=_auth_headers(attendee_token),
    )
    assert own_delete.status_code == 200
    remaining = own_delete.json()["file_attachments"]
    assert {item["id"] for item in remaining} == {admin_file_id}
    assert any("notes.txt" in key for key in fake.removed)

    # Organizer deletes the remaining file (their own) → success.
    organizer_delete = client.delete(
        f"/api/v1/meeting/meetings/{meeting['id']}/files/{admin_file_id}",
        headers=_auth_headers(admin_token),
    )
    assert organizer_delete.status_code == 200
    assert organizer_delete.json()["file_attachments"] == []
