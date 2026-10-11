from __future__ import annotations


from fastapi.testclient import TestClient
from minio.error import S3Error
import pytest
from sqlalchemy import select

from dev_accounts import (
    content_grant_headers,
    content_headers,
    create_company_user_session,
    dev_login,
)

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.core.storage import get_minio_client
from miy_api.domains.files import (
    rag_projection,
    rag_status,
    retrieval_contract,
    service as files_service,
)
from miy_api.domains.files.models import FileManagerFile, FileManagerStorageCleanupJob
from miy_api.domains.files.rag_projection import FileExtractionArtifact
from miy_api.domains.rag.models import RagSyncJob


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _administrator_member_session(client: TestClient, login_id: str) -> dict:
    return create_company_user_session(
        client,
        login_id=login_id,
        email=f"{login_id}@miy.local",
        full_name="Company Member",
    )


@pytest.mark.external_integration("minio")
def test_file_manager_upload_download_and_delete_with_rag_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exercise the post-generation lifecycle explicitly. Runtime Files
    # retrieval remains fail-closed until the isolated backend cutover.
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", True)
    monkeypatch.setattr(rag_status, "FILES_RETRIEVAL_ACTIVE", True)
    session = dev_login(client, "administrator")
    headers = _auth_headers(session["token"])

    folder_response = client.post(
        "/api/v1/files/folders",
        headers=headers,
        json={"name": "Policies", "visibility": "company", "company_admin_read_acknowledged": True},
    )
    assert folder_response.status_code == 201, folder_response.text
    folder = folder_response.json()
    assert folder["name"] == "Policies"
    assert folder["visibility"] == "company"

    upload_response = client.post(
        "/api/v1/files/upload",
        headers=headers,
        data={
            "folder_id": folder["id"],
            "visibility": "company",
            "company_admin_read_acknowledged": True,
        },
        files={"file": ("policy.txt", b"plain file storage", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file = upload_response.json()
    assert file["filename"] == "policy.txt"
    assert file["folder_id"] == folder["id"]
    assert file["visibility"] == "company"
    assert file["rag_status"] == "pending"
    assert file["rag_updated_at"] is not None

    browse_response = client.get(
        "/api/v1/files",
        headers=headers,
        params={"folder_id": folder["id"]},
    )
    assert browse_response.status_code == 200, browse_response.text
    browse = browse_response.json()
    assert browse["current_folder"]["id"] == folder["id"]
    assert browse["files"][0]["id"] == file["id"]

    download_response = client.get(
        f"/api/v1/files/{file['id']}/download",
        headers=headers,
    )
    assert download_response.status_code == 200, download_response.text
    download_url = download_response.json()["url"]
    assert download_url.startswith("/api/v1/content#grant=")
    assert "127.0.0.1" not in download_url

    anonymous_response = client.get(
        download_url,
        headers=content_grant_headers(download_url),
    )
    assert anonymous_response.status_code == 403, anonymous_response.text

    query_grant_response = client.get(
        download_url.replace("#grant=", "?grant=", 1),
        headers=headers,
    )
    assert query_grant_response.status_code == 403, query_grant_response.text

    other_session = dev_login(client, "administrator")
    other_session_response = client.get(
        download_url,
        headers=content_headers(other_session["token"], download_url),
    )
    assert other_session_response.status_code == 403, other_session_response.text

    content_response = client.get(
        download_url,
        headers=content_headers(session["token"], download_url),
    )
    assert content_response.status_code == 200, content_response.text
    assert content_response.content == b"plain file storage"
    assert content_response.headers["content-type"].startswith("text/plain")
    assert content_response.headers["content-disposition"].startswith("attachment;")
    assert "policy.txt" in content_response.headers["content-disposition"]

    with get_session_factory()() as db:
        rag_job = db.scalar(select(RagSyncJob).where(RagSyncJob.resource_id == file["id"]))
        assert rag_job is not None
        assert rag_job.operation == "upsert"

    delete_response = client.delete(
        f"/api/v1/files/{file['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 204, delete_response.text

    with get_session_factory()() as db:
        row = db.get(FileManagerFile, file["id"])
        assert row is not None
        assert row.deleted_at is not None
        storage_key = row.storage_key

    # A soft-delete flag alone does not prove the byte grant and physical object are gone.
    revoked = client.get(download_url, headers=content_headers(session["token"], download_url))
    assert revoked.status_code == 403, revoked.text
    assert revoked.json()["code"] == "content.grant_invalid"
    with pytest.raises(S3Error) as exc:
        get_minio_client().stat_object(get_settings().minio_bucket, storage_key)
    assert exc.value.code == "NoSuchKey"


def test_extraction_result_cannot_be_persisted_after_concurrent_soft_delete(
    client: TestClient,
    in_memory_object_storage: None,
) -> None:
    session = dev_login(client, "administrator")
    headers = _auth_headers(session["token"])
    upload_response = client.post(
        "/api/v1/files/upload",
        headers=headers,
        data={"visibility": "private"},
        files={"file": ("concurrent-delete.txt", b"heater content", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file_id = upload_response.json()["id"]

    worker_db = get_session_factory()()
    try:
        stale_file = worker_db.get(FileManagerFile, file_id)
        assert stale_file is not None and stale_file.deleted_at is None
        delete_response = client.delete(
            f"/api/v1/files/{file_id}",
            headers=headers,
        )
        assert delete_response.status_code == 204, delete_response.text

        stored = rag_projection._store_artifact_if_active(
            worker_db,
            file_id=file_id,
            artifact=FileExtractionArtifact(
                content_checksum="a" * 64,
                text="late sensitive extraction",
                blocks=[],
                metadata={"parser": "plain_text"},
            ),
        )
        worker_db.commit()
        assert stored is False
    finally:
        worker_db.close()

    with get_session_factory()() as db:
        row = db.get(FileManagerFile, file_id)
        assert row is not None and row.deleted_at is not None
        assert row.extraction_text is None
        assert row.extraction_blocks == []
        assert row.extraction_metadata == {}


def test_company_shared_file_is_readable_but_not_deletable_by_user(
    client: TestClient,
    in_memory_object_storage: None,
) -> None:
    admin_session = dev_login(client, "administrator")
    member_session = _administrator_member_session(client, "filesmember")

    upload_response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(admin_session["token"]),
        data={"visibility": "company", "company_admin_read_acknowledged": True},
        files={"file": ("shared.txt", b"shared", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file = upload_response.json()

    private_response = client.post(
        "/api/v1/files/upload",
        headers=_auth_headers(admin_session["token"]),
        data={"visibility": "private"},
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    assert private_response.status_code == 201, private_response.text
    private_file = private_response.json()
    browse_response = client.get(
        "/api/v1/files",
        headers=_auth_headers(member_session["token"]),
    )
    assert browse_response.status_code == 200, browse_response.text
    visible = {item["id"] for item in browse_response.json()["files"]}
    assert file["id"] in visible
    assert private_file["id"] not in visible
    assert (
        client.get(
            f"/api/v1/files/{private_file['id']}/download",
            headers=_auth_headers(member_session["token"]),
        ).status_code
        == 403
    )

    delete_response = client.delete(
        f"/api/v1/files/{file['id']}",
        headers=_auth_headers(member_session["token"]),
    )
    assert delete_response.status_code == 403, delete_response.text


def test_delete_queues_storage_cleanup_job_when_minio_delete_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    in_memory_object_storage: None,
) -> None:
    session = dev_login(client, "administrator")
    headers = _auth_headers(session["token"])

    upload_response = client.post(
        "/api/v1/files/upload",
        headers=headers,
        data={"visibility": "private"},
        files={"file": ("cleanup.txt", b"cleanup", "text/plain")},
    )
    assert upload_response.status_code == 201, upload_response.text
    file = upload_response.json()

    def fail_remove(keys):
        return [
            files_service.file_storage.FileStorageRemovalFailure(
                storage_key=key,
                exc=RuntimeError(f"cannot remove {key}"),
            )
            for key in keys
        ]

    monkeypatch.setattr(files_service.file_storage, "remove_file_objects", fail_remove)

    delete_response = client.delete(
        f"/api/v1/files/{file['id']}",
        headers=headers,
    )
    assert delete_response.status_code == 204, delete_response.text

    with get_session_factory()() as db:
        job = db.scalar(select(FileManagerStorageCleanupJob))
        assert job is not None
        assert job.storage_key.endswith("/cleanup.txt")
        assert job.status == "pending"
