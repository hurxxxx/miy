from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_meeting import _auth_headers, _bootstrap_admin_session, _create_meeting

from miy_api.core.db import get_engine
from miy_api.domains.recording import blob_store
from miy_api.domains.recording import service as canonical_recording_service
from miy_api.domains.recording.models import Recording, RecordingStaging, RecordingTarget


class _FakeMinioObject:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def stream(self, chunk_size: int):
        for offset in range(0, len(self._data), chunk_size):
            yield self._data[offset : offset + chunk_size]

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class _FakeRecordingMinio:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.removed: list[str] = []

    def put_object(self, bucket: str, key: str, data, length: int, content_type: str) -> None:
        del bucket, length, content_type
        self.objects[key] = data.read()

    def fput_object(
        self, bucket: str, key: str, path: str, content_type: str | None = None
    ) -> None:
        del bucket, content_type
        self.objects[key] = Path(path).read_bytes()

    def fget_object(self, bucket: str, key: str, path: str) -> None:
        del bucket
        Path(path).write_bytes(self.objects[key])

    def get_object(self, bucket: str, key: str) -> _FakeMinioObject:
        del bucket
        return _FakeMinioObject(self.objects[key])

    def remove_object(self, bucket: str, key: str) -> None:
        del bucket
        self.removed.append(key)
        self.objects.pop(key, None)

    def presigned_get_object(self, bucket: str, key: str, expires) -> str:
        del bucket, expires
        return f"https://fake-minio.local/{key}"


def _install_fake_recording_storage(monkeypatch, tmp_path) -> _FakeRecordingMinio:
    fake = _FakeRecordingMinio()
    spool_root = tmp_path / "recording-spool"
    spool_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(blob_store, "get_minio_client", lambda: fake)
    monkeypatch.setattr(blob_store, "recording_spool_root", lambda: spool_root)
    monkeypatch.setattr(canonical_recording_service, "_broker_is_reachable", lambda: True)
    monkeypatch.setattr(
        canonical_recording_service,
        "new_recording_attempt_id",
        lambda recording_id: f"task-{recording_id}",
    )
    monkeypatch.setattr(
        canonical_recording_service,
        "enqueue_recording_pipeline",
        lambda recording_id, attempt_id: None,
    )
    return fake


def _meeting_recording_target(
    session: Session,
    *,
    meeting_id: str,
    recording_id: str,
) -> RecordingTarget:
    target = session.scalar(
        select(RecordingTarget).where(
            RecordingTarget.recording_id == recording_id,
            RecordingTarget.target_app == "meeting",
            RecordingTarget.target_type == "meeting",
            RecordingTarget.target_id == meeting_id,
        )
    )
    assert target is not None
    return target


def _meeting_staging_rows(session: Session, meeting_id: str) -> list[RecordingStaging]:
    return list(
        session.scalars(
            select(RecordingStaging).where(
                RecordingStaging.initial_target_app == "meeting",
                RecordingStaging.initial_target_type == "meeting",
                RecordingStaging.initial_target_id == meeting_id,
            )
        )
    )


def test_only_one_user_can_record_at_a_time(client, monkeypatch, tmp_path) -> None:
    """Single-recorder lock: while one participant is staging an active
    recording, other participants get a 409 with the active recorder name."""
    fake_minio = _install_fake_recording_storage(monkeypatch, tmp_path)
    from test_meeting import _create_company_user, _login

    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]

    second = _create_company_user(
        client,
        admin_token,
        email="second-recorder@miy.local",
        full_name="Second Recorder",
    )
    second_token = _login(client, second["user"]["email"], second["temporary_password"])

    meeting = _create_meeting(
        client,
        admin_token,
        title="Single recorder lock",
        attendees=[{"user_id": second["user"]["id"], "role": "required"}],
    )

    # Admin starts a recording.
    first_init = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging",
        headers=_auth_headers(admin_token),
        json={"idempotency_key": "lock-test-admin", "mime_type": "audio/webm"},
    )
    assert first_init.status_code == 201, first_init.text
    admin_staging_id = first_init.json()["id"]

    # Second user tries to start a recording while admin is still active → 409.
    blocked = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging",
        headers=_auth_headers(second_token),
        json={"idempotency_key": "lock-test-second", "mime_type": "audio/webm"},
    )
    assert blocked.status_code == 409, blocked.text
    body = blocked.json()
    assert body["code"] == "meeting.recording_in_progress"
    assert body["params"]["active_recorder_id"] == admin["user"]["id"]
    assert body["params"]["active_recorder_name"] == admin["user"]["full_name"]
    assert body["params"]["active_staging_id"] == admin_staging_id

    # Admin can still resume their own staging (idempotent path).
    same_admin = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging",
        headers=_auth_headers(admin_token),
        json={"idempotency_key": "lock-test-admin", "mime_type": "audio/webm"},
    )
    assert same_admin.status_code == 201
    assert same_admin.json()["id"] == admin_staging_id

    # The meeting detail exposes the active recorder so the frontend can disable
    # the start button on other users' UIs.
    detail_response = client.get(
        f"/api/v1/meeting/meetings/{meeting['id']}",
        headers=_auth_headers(second_token),
    )
    assert detail_response.status_code == 200
    body = detail_response.json()
    lock = body["active_recording_lock"]
    assert lock is not None
    assert lock["user_id"] == admin["user"]["id"]
    assert lock["user_name"] == admin["user"]["full_name"]
    assert lock["staging_id"] == admin_staging_id

    # Admin uploads a chunk and completes — releases the lock.
    chunk = b"x"
    digest = hashlib.sha256(chunk).hexdigest()
    upload = client.put(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging/{admin_staging_id}/chunks/0",
        headers={**_auth_headers(admin_token), "X-Chunk-Sha256": digest},
        files={"file": ("0.webm", chunk, "audio/webm")},
    )
    assert upload.status_code == 200, upload.text
    replay = client.put(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging/{admin_staging_id}/chunks/0",
        headers={**_auth_headers(admin_token), "X-Chunk-Sha256": digest},
        files={"file": ("0.webm", chunk, "audio/webm")},
    )
    assert replay.status_code == 200
    assert replay.json()["bytes_received"] == upload.json()["bytes_received"] == len(chunk)
    with Session(get_engine()) as db:
        staging = db.get(RecordingStaging, admin_staging_id)
        assert staging.chunk_count == 1 and staging.bytes_received == len(chunk)
    complete = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging/{admin_staging_id}/complete",
        headers=_auth_headers(admin_token),
        json={"duration_sec_estimate": 1},
    )
    assert complete.status_code == 200
    assert complete.json()["recordings"][0]["source"] == "live_recording"
    with Session(get_engine()) as db:
        recording = db.get(Recording, admin_staging_id)
        assert recording.celery_task_id == f"task-{admin_staging_id}"
        assert (
            _meeting_recording_target(
                db, meeting_id=meeting["id"], recording_id=recording.id
            ).sort_order
            == 1
        )
        assert fake_minio.objects[recording.storage_key] == chunk

    # Second user can now start.
    after_release = client.post(
        f"/api/v1/meeting/meetings/{meeting['id']}/recordings/staging",
        headers=_auth_headers(second_token),
        json={"idempotency_key": "lock-test-second", "mime_type": "audio/webm"},
    )
    assert after_release.status_code == 201, after_release.text
