"""Legacy API dispatch: real source transactions, synthetic broker/storage only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from company_admission_fixture import seed_company_app_access
from fastapi import HTTPException
from sqlalchemy import select, text
from test_official_writer_fence import wait_for_blockers
from test_official_writer_fence import writer as writer

from miy_api.domains.auth.models import CompanyAppControl, User
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.recording import service
from miy_api.domains.recording.models import Recording, RecordingTarget

legacy_enqueue = service.enqueue_recording_pipeline


@pytest.fixture
def dispatch_case(writer, monkeypatch):
    factory, admin, _ = writer
    recording_id, meeting_id, attempt_id = (str(uuid4()) for _ in range(3))
    now = datetime(2026, 10, 7, 12)
    with factory.begin() as db:
        seed_company_app_access(db, ["recording", "meeting"])
        db.add(
            Meeting(
                id=meeting_id,
                organizer_id=admin["user"]["id"],
                title="Synthetic",
                start_at=now,
                end_at=now + timedelta(hours=1),
            )
        )
        db.add(
            Recording(
                id=recording_id,
                owner_id=admin["user"]["id"],
                title="Synthetic",
                storage_key=f"synthetic/{recording_id}.wav",
                audio_status="saved",
                transcript_status="pending",
                summary_status="pending",
            )
        )
        db.flush()
        db.add(
            RecordingTarget(
                id=str(uuid4()),
                recording_id=recording_id,
                target_app="meeting",
                target_type="meeting",
                target_id=meeting_id,
                added_by_id=admin["user"]["id"],
            )
        )
    calls, revoked = [], []
    monkeypatch.setattr(service, "_broker_is_reachable", lambda: True)
    monkeypatch.setattr(service, "new_recording_attempt_id", lambda _: attempt_id)
    monkeypatch.setattr(service, "enqueue_recording_pipeline", lambda *args: calls.append(args))
    monkeypatch.setattr(service, "revoke_recording_task", lambda value: revoked.append(value))
    return SimpleNamespace(
        factory=factory,
        admin=admin,
        recording_id=recording_id,
        meeting_id=meeting_id,
        attempt_id=attempt_id,
        calls=calls,
        revoked=revoked,
    )


def enqueue(c, db):
    service._enqueue_pipeline_or_mark_failed(db, recording=db.get(Recording, c.recording_id))


def retry(c, db, path):
    user = db.get(User, c.admin["user"]["id"])
    if path == "recording":
        return service.retry_recording(db, user=user, recording_id=c.recording_id)
    return service.retry_meeting_recording(
        db, user=user, recording_id=c.recording_id, meeting=db.get(Meeting, c.meeting_id)
    )


def test_accepted_publish_response_loss_preserves_attempt(dispatch_case, monkeypatch):
    c = dispatch_case

    def accepted(*args):
        c.calls.append(args)
        raise OSError("synthetic broker credential must not escape")

    monkeypatch.setattr(service, "enqueue_recording_pipeline", accepted)
    error = None
    with c.factory() as db:
        try:
            enqueue(c, db)
        except HTTPException as caught:
            error = caught
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.celery_task_id == c.attempt_id
        assert row.transcript_status == row.summary_status == "pending"
        assert row.failure_reason is None and row.audio_status == "saved"
    assert c.calls == [(c.recording_id, c.attempt_id)] and c.revoked == []
    assert error is not None and error.status_code == 500
    assert "credential" not in str(error.detail)


@pytest.mark.parametrize(
    "path,alter", [("recording", "attempt"), ("meeting", "admission"), ("meeting", "owner")]
)
def test_retry_rechecks_after_waiting_for_recording_lock(dispatch_case, path, alter):
    c = dispatch_case
    other_id = str(uuid4())
    with c.factory.begin() as db:
        db.add(
            User(
                id=other_id,
                login_id=other_id,
                email=f"{other_id}@example.invalid",
                full_name="Other",
                password_hash="synthetic",
                status="active",
            )
        )
        db.get(Recording, c.recording_id).transcript_status = "failed"
    entered = Event()
    worker_pid = []

    def waiting():
        with c.factory() as db:
            worker_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            try:
                retry(c, db, path)
            except HTTPException as error:
                return error.status_code
            return 200

    with c.factory() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocked_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        row = blocker.scalar(
            select(Recording).where(Recording.id == c.recording_id).with_for_update()
        )
        future = pool.submit(waiting)
        try:
            assert entered.wait(10)
            wait_for_blockers(c.factory, worker_pid[0], {blocked_pid})
            if alter == "attempt":
                row.celery_task_id = c.attempt_id
            elif alter == "admission":
                blocker.get(CompanyAppControl, path).enabled = False
            else:
                row.owner_id = other_id
                if path == "meeting":
                    blocker.get(Meeting, c.meeting_id).organizer_id = other_id
            blocker.commit()
            assert future.result(timeout=10) == (409 if alter == "attempt" else 403)
        finally:
            blocker.rollback()
    assert c.calls == c.revoked == []


def test_unaccepted_send_exception_also_remains_unknown(dispatch_case, monkeypatch):
    c = dispatch_case

    def disconnected(*args):
        raise ConnectionError("connection failed before synthetic acceptance")

    monkeypatch.setattr(service, "enqueue_recording_pipeline", disconnected)
    with c.factory() as db, pytest.raises(HTTPException):
        enqueue(c, db)
    with c.factory() as db:
        assert db.get(Recording, c.recording_id).celery_task_id == c.attempt_id
        # A repeated same-record observation cannot allocate or send a new chain.
        enqueue(c, db)
    assert c.calls == c.revoked == []


@pytest.mark.parametrize("path", ["meeting"])
def test_retry_reset_and_attempt_have_one_commit_before_publish(dispatch_case, monkeypatch, path):
    c = dispatch_case
    with c.factory.begin() as db:
        db.get(Recording, c.recording_id).transcript_status = "failed"
    commits = []
    with c.factory() as db:
        commit = db.commit

        def observed_commit():
            commit()
            with c.factory() as reader:
                row = reader.get(Recording, c.recording_id)
                commits.append((row.transcript_status, row.celery_task_id))

        def publish(*args):
            assert commits == [("pending", c.attempt_id)]
            c.calls.append(args)

        monkeypatch.setattr(db, "commit", observed_commit)
        monkeypatch.setattr(service, "enqueue_recording_pipeline", publish)
        retry(c, db, path)
    assert commits == [("pending", c.attempt_id)]
    assert c.calls == [(c.recording_id, c.attempt_id)]
