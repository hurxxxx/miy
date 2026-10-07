"""Legacy API dispatch: real source transactions, synthetic broker/storage only."""

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from celery import Celery
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from company_admission_fixture import seed_company_app_access
from miy_api.domains.auth.models import CompanyAppControl, User
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.recording import service
from miy_api.domains.recording.models import Recording, RecordingResult, RecordingTarget
from test_official_writer_fence import change, wait_for_blockers, writer as writer
from test_meeting_recordings import _install_fake_recording_storage

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


@pytest.mark.parametrize("state", ["transcribing", "done", "replacement"])
def test_publish_loss_does_not_overwrite_concurrent_worker(dispatch_case, monkeypatch, state):
    c = dispatch_case
    replacement = str(uuid4())

    def progressed(*args):
        c.calls.append(args)
        with c.factory.begin() as worker:
            row = worker.get(Recording, c.recording_id)
            row.transcript_status = "done" if state == "done" else "transcribing"
            row.summary_status = "done" if state == "done" else "pending"
            row.progress_pct = 100 if state == "done" else 25
            row.celery_task_id = (
                None if state == "done" else replacement if state == "replacement" else c.attempt_id
            )
        raise OSError("lost after accepted")

    monkeypatch.setattr(service, "enqueue_recording_pipeline", progressed)
    with c.factory() as db, pytest.raises(HTTPException) as error:
        enqueue(c, db)
    assert error.value.status_code == 500
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.progress_pct == (100 if state == "done" else 25)
        assert row.celery_task_id == (
            None if state == "done" else replacement if state == "replacement" else c.attempt_id
        )
        assert row.failure_reason is None
    assert len(c.calls) == 1 and c.revoked == []


@pytest.mark.parametrize("path", ["recording", "meeting"])
@pytest.mark.parametrize("state", ["pending", "transcribing", "failed"])
def test_current_attempt_cannot_be_replaced(dispatch_case, path, state):
    c = dispatch_case
    with c.factory.begin() as db:
        row = db.get(Recording, c.recording_id)
        row.celery_task_id = c.attempt_id
        row.transcript_status = state
    with c.factory() as db, pytest.raises(HTTPException) as error:
        retry(c, db, path)
    assert error.value.status_code == 409
    assert c.calls == c.revoked == []
    with c.factory() as db:
        assert db.get(Recording, c.recording_id).celery_task_id == c.attempt_id


@pytest.mark.parametrize("path", ["recording", "meeting"])
def test_known_failure_with_no_attempt_can_retry(dispatch_case, path):
    c = dispatch_case
    with c.factory.begin() as db:
        db.get(Recording, c.recording_id).transcript_status = "failed"
    with c.factory() as db:
        result = retry(c, db, path)
    assert result.id == c.recording_id and result.transcript_status == "pending"
    assert c.calls == [(c.recording_id, c.attempt_id)] and c.revoked == []


@pytest.mark.parametrize("path", ["recording", "meeting"])
def test_preflight_no_send_failure_remains_retryable(dispatch_case, monkeypatch, path):
    c = dispatch_case
    monkeypatch.setattr(service, "_broker_is_reachable", lambda: False)
    with c.factory() as db:
        enqueue(c, db)
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.celery_task_id is None and row.transcript_status == "failed"
        assert row.failure_reason == service.ENQUEUE_FAILURE_REASON
    assert c.calls == []
    monkeypatch.setattr(service, "_broker_is_reachable", lambda: True)
    with c.factory() as db:
        retry(c, db, path)
    assert len(c.calls) == 1


@pytest.mark.parametrize("path", ["recording", "meeting"])
def test_retry_reloads_stale_identity_map(dispatch_case, path):
    c = dispatch_case
    with c.factory() as db:
        stale = db.get(Recording, c.recording_id)
        with c.factory.begin() as other:
            other.get(Recording, c.recording_id).celery_task_id = c.attempt_id
        assert stale.celery_task_id is None
        with pytest.raises(HTTPException) as error:
            retry(c, db, path)
        assert error.value.status_code == 409
    assert c.calls == c.revoked == []


@pytest.mark.parametrize("path", ["enqueue", "recording", "meeting"])
@pytest.mark.parametrize("accepted", [False, True])
def test_commit_unknown_has_no_followup(dispatch_case, monkeypatch, path, accepted):
    c = dispatch_case
    with c.factory.begin() as db:
        db.get(Recording, c.recording_id).transcript_status = "failed"
        db.add(
            RecordingResult(
                recording_id=c.recording_id,
                transcript_text="Original",
                summary_text="Old summary",
                verifier_note="Old verification",
                version=1,
            )
        )
    with c.factory() as db:
        commit, count = db.commit, 0

        def uncertain():
            nonlocal count
            count += 1
            if accepted:
                commit()
            raise OSError("unknown source commit credential")

        monkeypatch.setattr(db, "commit", uncertain)
        with pytest.raises(HTTPException) as error:
            enqueue(c, db) if path == "enqueue" else retry(c, db, path)
        assert error.value.status_code == 500
        assert "credential" not in str(error.value.detail)
        assert count == 1
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.audio_status == "saved" and row.storage_key
        assert row.celery_task_id == (c.attempt_id if accepted else None)
        expected_state = "pending" if accepted else "failed"
        assert row.transcript_status == expected_state
        assert row.result.summary_text == (
            None if accepted and path != "enqueue" else "Old summary"
        )
        assert row.result.version == 1
    assert c.calls == c.revoked == []


@pytest.mark.parametrize("path", ["recording", "meeting"])
@pytest.mark.parametrize("alter", ["attempt", "admission", "owner"])
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


@pytest.mark.parametrize("path", ["recording", "meeting"])
def test_drain_prevents_retry_without_revoke_or_publish(dispatch_case, path):
    c = dispatch_case
    with c.factory.begin() as controller:
        change(controller, c.admin)
    with c.factory() as db, pytest.raises(DBAPIError) as error:
        retry(c, db, path)
    assert error.value.orig.sqlstate == "55000"
    assert c.calls == c.revoked == []


@pytest.mark.parametrize("path", ["recording", "meeting"])
def test_completed_recording_cannot_be_restarted(dispatch_case, path):
    c = dispatch_case
    with c.factory.begin() as db:
        row = db.get(Recording, c.recording_id)
        row.transcript_status = row.summary_status = "done"
    with c.factory() as db, pytest.raises(HTTPException) as error:
        retry(c, db, path)
    assert error.value.status_code == 409 and c.calls == c.revoked == []


@pytest.mark.parametrize("accepted", [False, True])
def test_rollback_failure_after_commit_unknown_does_not_resubmit(
    dispatch_case, monkeypatch, accepted
):
    c = dispatch_case
    with c.factory() as db:
        commit = db.commit

        def uncertain():
            if accepted:
                commit()
            raise OSError("commit acknowledgement lost")

        def failed_rollback():
            raise OSError("rollback connection lost")

        monkeypatch.setattr(db, "commit", uncertain)
        monkeypatch.setattr(db, "rollback", failed_rollback)
        with pytest.raises(HTTPException) as error:
            enqueue(c, db)
        assert error.value.status_code == 500
    with c.factory() as db:
        assert db.get(Recording, c.recording_id).celery_task_id == (
            c.attempt_id if accepted else None
        )
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


@pytest.mark.parametrize("locale,fragment", [("ko-KR", "원본 음성"), ("en-US", "original audio")])
def test_http_unknown_is_localized_and_preserves_original_bytes(
    dispatch_case, client, monkeypatch, tmp_path, locale, fragment
):
    c = dispatch_case
    storage = _install_fake_recording_storage(monkeypatch, tmp_path)

    def accepted(*args):
        c.calls.append(args)
        raise OSError("do not expose provider-secret")

    monkeypatch.setattr(service, "enqueue_recording_pipeline", accepted)
    response = client.post(
        "/api/v1/recording/recordings/import",
        headers={"Authorization": "Bearer " + c.admin["token"], "Accept-Language": locale},
        files={"file": ("synthetic.wav", b"original synthetic audio", "audio/wav")},
        data={"title": "Unknown dispatch"},
    )
    assert response.status_code == 500, response.text
    assert fragment in response.text and "provider-secret" not in response.text
    assert len(c.calls) == 1 and storage.removed == []
    with c.factory() as db:
        saved = db.get(Recording, c.calls[0][0])
        assert saved.celery_task_id == c.calls[0][1] and saved.transcript_status == "pending"
        assert storage.objects[saved.storage_key] == b"original synthetic audio"
        saved_id = saved.id
    observed = client.get(
        f"/api/v1/recording/recordings/{saved_id}",
        headers={"Authorization": "Bearer " + c.admin["token"]},
    )
    assert observed.status_code == 200 and observed.json()["audio_status"] == "saved"
    again = client.post(
        f"/api/v1/recording/recordings/{saved_id}/retry",
        headers={"Authorization": "Bearer " + c.admin["token"]},
    )
    assert again.status_code == 409 and len(c.calls) == 1 and storage.removed == []


def test_default_api_uses_unchanged_legacy_chain(dispatch_case, monkeypatch):
    c = dispatch_case
    signatures, published = [], []
    publisher = Celery("synthetic", broker="memory://", backend="cache+memory://")

    def chain(*tasks):
        signatures.extend(tasks)
        return SimpleNamespace(apply_async=lambda **kwargs: published.append(kwargs))

    monkeypatch.setattr(service, "_get_celery_client", lambda: publisher)
    monkeypatch.setattr(service, "chain", chain)
    monkeypatch.setattr(service, "enqueue_recording_pipeline", legacy_enqueue)
    with c.factory() as db:
        enqueue(c, db)
    assert [item.task for item in signatures] == [
        "recording.transcribe",
        "recording.analyze_transcript",
        "recording.verify_transcript_summary",
        "recording.persist_result",
    ]
    assert signatures[0].args == (c.recording_id, c.attempt_id)
    assert signatures[0].immutable is True
    assert all(item.args == () and item.kwargs == {} for item in signatures[1:])
    assert signatures[-1].options == {"task_id": c.attempt_id}
    assert published == [{"queue": "meeting_transcribe", "retry": False}]
    assert c.revoked == []


@pytest.mark.parametrize(
    "case",
    [
        "recording_admission",
        "recording_owner",
        "recording_done",
        "meeting_admission",
        "meeting_owner",
        "meeting_done",
        "meeting_target",
        "meeting_membership",
    ],
)
def test_retry_preflight_handoff_denial_leaves_source_unmodified(dispatch_case, monkeypatch, case):
    c = dispatch_case
    path, alteration = case.split("_")
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
        db.add(
            RecordingResult(
                recording_id=c.recording_id,
                transcript_text="Original",
                summary_text="Old summary",
                verifier_note="Old verification",
                version=1,
            )
        )
        if alteration == "membership":
            db.get(Meeting, c.meeting_id).organizer_id = other_id
            db.add(
                MeetingAttendee(
                    id=str(uuid4()), meeting_id=c.meeting_id, user_id=c.admin["user"]["id"]
                )
            )

    def probe():
        with c.factory.begin() as other:
            row = other.get(Recording, c.recording_id)
            assert row.transcript_status == "failed" and row.celery_task_id is None
            if alteration == "admission":
                other.get(CompanyAppControl, path).enabled = False
            elif alteration == "owner":
                row.owner_id = other_id
                other.get(Meeting, c.meeting_id).organizer_id = other_id
            elif alteration == "done":
                row.transcript_status = row.summary_status = "done"
            elif alteration == "target":
                other.delete(
                    other.scalar(
                        select(RecordingTarget).where(RecordingTarget.recording_id == row.id)
                    )
                )
            else:
                other.delete(
                    other.scalar(
                        select(MeetingAttendee).where(MeetingAttendee.meeting_id == c.meeting_id)
                    )
                )
        return True

    monkeypatch.setattr(service, "_broker_is_reachable", probe)
    with c.factory() as db, pytest.raises(HTTPException) as error:
        retry(c, db, path)
    assert error.value.status_code == (
        409 if alteration == "done" else 404 if alteration == "target" else 403
    )
    assert c.calls == c.revoked == []
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.celery_task_id is None
        assert row.transcript_status == ("done" if alteration == "done" else "failed")
        assert (
            row.result.summary_text == "Old summary"
            and row.result.verifier_note == "Old verification"
        )


@pytest.mark.parametrize("path", ["recording", "meeting"])
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
