from __future__ import annotations

from typing import Literal

from fastapi.testclient import TestClient
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.search import outbox as search_outbox
from miy_api.domains.search.indexing import process_search_index_job
from miy_api.domains.search.models import SearchIndexJob

from test_meeting import (
    _auth_headers as _auth_headers,
    _bootstrap_admin_session as _bootstrap_admin_session,
    _create_meeting as _create_meeting,
    _create_company_user as _create_company_user,
    _login as _login,
)


class _RecordingSearchClient:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deletes: list[tuple[str, str]] = []

    def upsert_document(self, document: dict) -> None:
        self.upserts.append(document)

    def delete_document(self, *, entity_type: str, entity_id: str) -> None:
        self.deletes.append((entity_type, entity_id))

    def upsert_partitioned_document(self, document: dict) -> str:
        self.upserts.append(document)
        return "upserted"

    def delete_partitioned_document(
        self,
        *,
        resource_type: str,
        resource_id: str,
        projection_version: int,
    ) -> str:
        del projection_version
        prior = next(
            (
                document
                for document in reversed(self.upserts)
                if document.get("entity_id") == resource_id
            ),
            None,
        )
        entity_type = (
            str(prior["entity_type"])
            if prior is not None
            else {
                "docs_native_doc": "doc",
                "file_manager_file": "file",
                "meeting": "meeting",
                "pms_task": "task",
            }[resource_type]
        )
        self.deletes.append(
            (
                entity_type,
                resource_id,
            )
        )
        return "deleted"


def _stub_search_publish(monkeypatch) -> list[tuple[str, list[str], str]]:
    published: list[tuple[str, list[str], str]] = []

    class _FakeSignature:
        def __init__(self, task_name: str, args: list[str]) -> None:
            self.task_name = task_name
            self.args = args

        def apply_async(self, *, queue: str, retry: bool) -> None:
            published.append((self.task_name, self.args, queue))

    class _FakeCeleryClient:
        def signature(self, task_name: str, args: list[str], immutable: bool):
            assert immutable is True
            return _FakeSignature(task_name, args)

    monkeypatch.setattr(search_outbox, "get_celery_client", lambda: _FakeCeleryClient())
    return published


def _process_pending_entity(
    search_client: _RecordingSearchClient,
    *,
    entity_type: str,
    entity_id: str,
    lifecycle_operation: Literal["create", "update"],
) -> dict:
    with get_session_factory()() as db:
        job_ids = list(
            db.scalars(
                select(SearchIndexJob.id)
                .where(
                    SearchIndexJob.status == "pending",
                    SearchIndexJob.entity_type == entity_type,
                    SearchIndexJob.entity_id == entity_id,
                )
                .order_by(SearchIndexJob.created_at.asc(), SearchIndexJob.id.asc())
            )
        )
    assert job_ids, (
        f"expected pending {lifecycle_operation} search index job for {entity_type}:{entity_id}"
    )

    for job_id in job_ids:
        with get_session_factory()() as db:
            process_search_index_job(db, job_id, client=search_client)

    matches = [
        document
        for document in search_client.upserts
        if document.get("entity_type") == entity_type and document.get("entity_id") == entity_id
    ]
    assert matches, f"expected search upsert for {entity_type}:{entity_id}"
    return matches[-1]


def _process_pending_delete(
    search_client: _RecordingSearchClient,
    *,
    entity_type: str,
    entity_id: str,
    lifecycle_operation: Literal["delete"],
) -> tuple[str, str]:
    with get_session_factory()() as db:
        job_ids = list(
            db.scalars(
                select(SearchIndexJob.id)
                .where(
                    SearchIndexJob.status == "pending",
                    SearchIndexJob.entity_type == entity_type,
                    SearchIndexJob.entity_id == entity_id,
                )
                .order_by(SearchIndexJob.created_at.asc(), SearchIndexJob.id.asc())
            )
        )
    assert job_ids, (
        f"expected pending {lifecycle_operation} search index job for {entity_type}:{entity_id}"
    )

    for job_id in job_ids:
        with get_session_factory()() as db:
            process_search_index_job(db, job_id, client=search_client)

    matches = [
        item for item in search_client.deletes if item[0] == entity_type and item[1] == entity_id
    ]
    assert matches, f"expected search delete for {entity_type}:{entity_id}"
    return matches[-1]


def _create_space(client: TestClient, token: str, *, name: str) -> dict:
    response = client.post(
        "/api/v1/pms/spaces",
        headers=_auth_headers(token),
        json={"name": name, "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list(
    client: TestClient,
    token: str,
    *,
    team_id: str,
    key: str,
    name: str,
) -> dict:
    response = client.post(
        "/api/v1/pms/lists",
        headers=_auth_headers(token),
        json={
            "key": key,
            "name": name,
            "description": "",
            "team_id": team_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_issue(
    client: TestClient,
    token: str,
    *,
    list_id: str,
    title: str,
) -> dict:
    response = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": "Task body",
            "status": "todo",
            "priority": "medium",
            "label_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_meeting_delete_detaches_access_grant_foreign_keys_and_deletes_search_document(
    client: TestClient,
    monkeypatch,
) -> None:
    _stub_search_publish(monkeypatch)
    search_client = _RecordingSearchClient()
    admin = _bootstrap_admin_session(client)
    attendee = _create_company_user(
        client,
        admin["token"],
        email="search-meeting-delete-attendee@miy.local",
        full_name="Search Meeting Delete Attendee",
    )
    space = _create_space(
        client,
        admin["token"],
        name="Search Meeting Delete Space",
    )
    task_list = _create_task_list(
        client,
        admin["token"],
        team_id=space["id"],
        key="SMDL",
        name="Search Meeting Delete List",
    )
    issue = _create_issue(
        client,
        admin["token"],
        list_id=task_list["id"],
        title="Meeting Delete Task",
    )
    meeting = _create_meeting(
        client,
        admin["token"],
        title="Delete Meeting With Grants",
        attendees=[],
        task_ids=[issue["id"]],
    )

    add_response = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/attendees",
        headers=_auth_headers(admin["token"]),
        json={"attendees": [{"user_id": attendee["user"]["id"], "role": "required"}]},
    )
    assert add_response.status_code == 200, add_response.text

    remove_response = client.patch(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin["token"]),
        json={"attendees": []},
    )
    assert remove_response.status_code == 200, remove_response.text

    delete_response = client.delete(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(admin["token"]),
    )
    assert delete_response.status_code == 204, delete_response.text

    _process_pending_delete(
        search_client,
        entity_type="meeting",
        entity_id=meeting["id"],
        lifecycle_operation="delete",
    )
