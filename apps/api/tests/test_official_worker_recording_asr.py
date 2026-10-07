"""Real source transactions and ASR adapter; synthetic storage/HTTP only."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from celery.exceptions import Ignore, Retry
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from company_admission_fixture import seed_company_app_access
from miy_api.core import asr
from miy_api.domains.auth.models import User
from miy_api.domains.recording.models import Recording, RecordingResult
from test_official_writer_fence import change, wait_for_blockers, writer as writer


@pytest.fixture
def recording_phase(writer, monkeypatch):
    factory, admin, _ = writer
    task = importlib.import_module("miy_worker.tasks.recording")
    engine = create_engine(factory.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    runtime_factory = sessionmaker(engine)
    recording_id, attempt_id = str(uuid4()), str(uuid4())
    with factory.begin() as db:
        seed_company_app_access(db, ["recording"])
        db.add(
            Recording(
                id=recording_id,
                owner_id=admin["user"]["id"],
                title="Synthetic",
                storage_key=f"synthetic/{recording_id}.wav",
                audio_status="saved",
                transcript_status="pending",
                summary_status="pending",
                progress_pct=0,
                celery_task_id=attempt_id,
            )
        )
        db.flush()
        db.add(
            RecordingResult(
                recording_id=recording_id,
                transcript_text="",
                summary_text="Original summary",
                version=1,
            )
        )
    c = SimpleNamespace(
        factory=factory,
        admin=admin,
        task=task,
        runtime_factory=runtime_factory,
        recording_id=recording_id,
        attempt_id=attempt_id,
        sessions=[],
        health=[],
        downloads=[],
        posts=[],
        paths=[],
        on_post=lambda: None,
        response_status=200,
    )

    def session():
        db = runtime_factory()
        c.sessions.append(db)
        return db

    def health(*args, **kwargs):
        c.health.append(True)
        return httpx.Response(200, json={"ready": True})

    def post(url, **kwargs):
        c.posts.append(url)
        assert kwargs["files"]["file"][1].read() == b"synthetic audio"
        c.on_post()
        return httpx.Response(c.response_status, json={"text": "Transcript", "duration_sec": 3.0})

    class Storage:
        def fget_object(self, bucket, key, path):
            c.downloads.append(key)
            c.paths.append(Path(path))
            Path(path).write_bytes(b"synthetic audio")

    backend = asr.InferenceGatewayASRBackend(
        base_url="http://asr.invalid", api_key="synthetic", model="synthetic", timeout_seconds=2.0
    )
    monkeypatch.setattr(task, "_db_session", session)
    monkeypatch.setattr(task, "_minio_client", lambda: Storage())
    monkeypatch.setattr(task, "check_asr_health", backend.healthcheck)
    monkeypatch.setattr(task, "get_asr_backend", lambda: backend)
    monkeypatch.setattr(asr.httpx, "get", health)
    monkeypatch.setattr(asr.httpx, "post", post)
    try:
        yield c
    finally:
        for db in c.sessions:
            db.close()
        for path in c.paths:
            path.unlink(missing_ok=True)
        engine.dispose()


def run(c, phase="transcribe"):
    if phase == "transcribe":
        return c.task.transcribe_recording.run(c.recording_id, c.attempt_id)
    return c.task.persist_recording_result.run(
        {
            "recording_id": c.recording_id,
            "attempt_id": c.attempt_id,
            "result_version": 1,
            "summary": "Original summary",
            "verifier_note": "Verified",
        }
    )


@pytest.mark.parametrize("phase", ["transcribe", "persist"])
def test_normal_source_phase_uses_single_worker_connection(recording_phase, phase):
    c = recording_phase
    result = run(c, phase)
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        if phase == "transcribe":
            assert result == {"recording_id": c.recording_id, "attempt_id": c.attempt_id}
            assert row.transcript_status == "done" and row.result.version == 2
            assert row.result.transcript_text == "Transcript" and row.result.summary_text is None
            assert len(c.posts) == 1 and all(not path.exists() for path in c.paths)
        else:
            assert result == c.recording_id and row.summary_status == "done"
            assert row.celery_task_id is None and row.result.verifier_note == "Verified"


@pytest.mark.parametrize("at_commit", [1, 2])
def test_drain_after_durable_progress_denies_next_external_step(
    recording_phase, monkeypatch, at_commit
):
    c = recording_phase
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit, count = db.commit, 0

    def committed():
        nonlocal count
        commit()
        count += 1
        if count == at_commit:
            with c.factory.begin() as controller:
                change(controller, c.admin)

    monkeypatch.setattr(db, "commit", committed)
    with pytest.raises(DBAPIError):
        run(c)
    assert c.posts == []
    if at_commit == 1:
        assert c.health == [] and c.downloads == []


def test_persist_fence_rejection_is_not_broker_retry(recording_phase, monkeypatch):
    c = recording_phase
    with c.factory.begin() as controller:
        change(controller, c.admin)

    def retry(**kwargs):
        raise AssertionError("Database fence became broker retry")

    monkeypatch.setattr(c.task.persist_recording_result, "retry", retry)
    with pytest.raises(DBAPIError):
        run(c, "persist")


def handoff(c, monkeypatch, at_commit, action):
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit, count = db.commit, 0

    def committed():
        nonlocal count
        commit()
        count += 1
        if count == at_commit:
            with c.factory.begin() as controller:
                action(controller)

    monkeypatch.setattr(db, "commit", committed)


@pytest.mark.parametrize("at_commit", [1, 2, 3])
@pytest.mark.parametrize("changed", ["attempt", "version", "storage", "audio"])
def test_every_progress_handoff_preserves_original_source_claim(
    recording_phase, monkeypatch, at_commit, changed
):
    c = recording_phase

    def replace(db):
        row = db.get(Recording, c.recording_id)
        if changed == "attempt":
            row.celery_task_id = "replacement"
        elif changed == "version":
            row.result.version = 9
        elif changed == "storage":
            row.storage_key = "replacement.wav"
        else:
            row.audio_status = "failed"

    handoff(c, monkeypatch, at_commit, replace)
    with pytest.raises(Ignore):
        run(c)
    assert len(c.posts) == (1 if at_commit == 3 else 0)
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.failure_reason is None and row.transcript_status != "done"
        assert row.result.transcript_text == ""


def test_live_http_holds_source_until_callback_handoff(recording_phase):
    c = recording_phase
    entered, finish, draining = Event(), Event(), Event()
    pids = {}

    def remote():
        pids["worker"] = c.sessions[0].scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert finish.wait(20)

    c.on_post = remote

    def drain():
        with c.factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            draining.set()
            return change(db, c.admin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pool.submit(run, c)
        try:
            assert entered.wait(8)
            controller = pool.submit(drain)
            assert draining.wait(8)
            wait_for_blockers(c.factory, pids["controller"], {pids["worker"]})
            assert not controller.done()
            finish.set()
            with pytest.raises(DBAPIError):
                result.result(timeout=10)
            assert controller.result(timeout=10)["state"] == "draining"
        finally:
            finish.set()
    assert len(c.posts) == 1
    with c.factory() as db:
        assert db.get(Recording, c.recording_id).transcript_status != "done"


@pytest.mark.parametrize("value", [0.5, 0.1])
def test_repeated_or_lower_progress_still_rechecks_current_actor(
    recording_phase, monkeypatch, value
):
    c = recording_phase
    continued = []

    class Backend:
        def transcribe(self, path, *, on_progress):
            on_progress(0.5)
            with c.factory.begin() as db:
                db.get(User, c.admin["user"]["id"]).login_blocked = True
            on_progress(value)
            continued.append(True)
            return asr.TranscriptResult("Discard", [], None, None)

    monkeypatch.setattr(c.task, "get_asr_backend", lambda: Backend())
    with pytest.raises(Ignore):
        run(c)
    assert continued == []
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.transcript_status == "failed" and row.celery_task_id is None
        assert row.result.transcript_text == ""


@pytest.mark.parametrize("at_commit", [1, 2, 3, 4])
@pytest.mark.parametrize("accepted", [False, True])
def test_transcribe_commit_unknown_stops_without_failure_or_retry(
    recording_phase, monkeypatch, at_commit, accepted
):
    c = recording_phase
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit, count = db.commit, 0

    def uncertain():
        nonlocal count
        count += 1
        if count == at_commit:
            if accepted:
                commit()
            raise OSError("Synthetic lost acknowledgement")
        commit()

    monkeypatch.setattr(db, "commit", uncertain)

    def retry(**kwargs):
        raise AssertionError("Unknown COMMIT cannot retry")

    monkeypatch.setattr(c.task.transcribe_recording, "retry", retry)
    with pytest.raises(c.task.RecordingPhaseCommitUnknown):
        run(c)
    assert count == at_commit and len(c.posts) == (0 if at_commit < 3 else 1)
    with c.factory() as observer:
        row = observer.get(Recording, c.recording_id)
        assert row.failure_reason is None and row.celery_task_id == c.attempt_id
        assert (row.transcript_status == "done") == (at_commit == 4 and accepted)


@pytest.mark.parametrize("accepted", [False, True])
def test_persist_commit_unknown_has_no_retry_or_replacement_failure(
    recording_phase, monkeypatch, accepted
):
    c = recording_phase
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit = db.commit
    calls = []

    def uncertain():
        calls.append(True)
        if accepted:
            commit()
        raise OSError("Synthetic lost acknowledgement")

    monkeypatch.setattr(db, "commit", uncertain)

    def retry(**kwargs):
        raise AssertionError("Unknown COMMIT cannot retry")

    monkeypatch.setattr(c.task.persist_recording_result, "retry", retry)
    with pytest.raises(c.task.RecordingPhaseCommitUnknown):
        run(c, "persist")
    assert calls == [True]
    with c.factory() as observer:
        row = observer.get(Recording, c.recording_id)
        assert row.failure_reason is None
        assert (row.summary_status == "done") == accepted


def test_completed_persist_replay_is_read_only_and_does_not_adopt_claim(
    recording_phase, monkeypatch
):
    c = recording_phase
    assert run(c, "persist") == c.recording_id
    with c.factory.begin() as db:
        change(db, c.admin)
    assert run(c, "persist") == c.recording_id
    assert c.posts == []


@pytest.mark.parametrize("had_result", [False, True])
def test_result_absence_or_version_is_frozen_before_heartbeat(
    recording_phase, monkeypatch, had_result
):
    c = recording_phase
    if not had_result:
        with c.factory.begin() as db:
            db.delete(db.get(RecordingResult, c.recording_id))

    def replace(db):
        if had_result:
            db.delete(db.get(RecordingResult, c.recording_id))
        else:
            db.add(
                RecordingResult(
                    recording_id=c.recording_id, transcript_text="Replacement", version=1
                )
            )

    handoff(c, monkeypatch, 1, replace)
    with pytest.raises(Ignore):
        run(c)
    assert c.posts == [] and c.downloads == []


@pytest.mark.parametrize("phase", ["transcribe", "persist"])
def test_database_error_is_not_provider_failure(recording_phase, monkeypatch, phase):
    from sqlalchemy.exc import TimeoutError

    c = recording_phase

    def fail(*args, **kwargs):
        raise TimeoutError("Synthetic checkout failure")

    monkeypatch.setattr(c.task, "_load_active_recording", fail)

    def retry(**kwargs):
        raise AssertionError("Database error cannot retry")

    target = (
        c.task.transcribe_recording if phase == "transcribe" else c.task.persist_recording_result
    )
    monkeypatch.setattr(target, "retry", retry)
    with pytest.raises(TimeoutError):
        run(c, phase)


@pytest.mark.parametrize("terminal", [False, True])
def test_known_provider_error_retains_existing_exact_claim_policy(
    recording_phase, monkeypatch, terminal
):
    c = recording_phase
    c.response_status = 503
    retried = []
    task = c.task.transcribe_recording

    def retry(**kwargs):
        retried.append(kwargs["countdown"])
        raise Retry()

    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=3 if terminal else 0)
    try:
        with pytest.raises(Ignore if terminal else Retry):
            run(c)
    finally:
        task.pop_request()
    assert retried == ([] if terminal else [2])
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert (row.transcript_status == "failed") == terminal
        assert (row.celery_task_id is None) == terminal


@pytest.mark.parametrize("changed", ["attempt", "version", "drain"])
def test_provider_failure_cannot_finalize_replaced_source_claim(
    recording_phase, monkeypatch, changed
):
    c = recording_phase
    c.response_status = 503
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    rollback, replaced = db.rollback, False

    def replace():
        nonlocal replaced
        rollback()
        if replaced:
            return
        replaced = True
        with c.factory.begin() as controller:
            if changed == "drain":
                change(controller, c.admin)
            elif changed == "version":
                controller.get(RecordingResult, c.recording_id).version = 9
            else:
                controller.get(Recording, c.recording_id).celery_task_id = "replacement"

    monkeypatch.setattr(db, "rollback", replace)
    task = c.task.transcribe_recording
    task.push_request(retries=3)
    try:
        with pytest.raises(DBAPIError if changed == "drain" else Ignore):
            run(c)
    finally:
        task.pop_request()
    with c.factory() as controller:
        row = controller.get(Recording, c.recording_id)
        assert row.transcript_status == "transcribing" and row.failure_reason is None


def test_transcribe_with_no_result_creates_version_one(recording_phase):
    c = recording_phase
    with c.factory.begin() as db:
        db.delete(db.get(RecordingResult, c.recording_id))
    assert run(c)["attempt_id"] == c.attempt_id
    with c.factory() as db:
        result = db.get(RecordingResult, c.recording_id)
        assert result.version == 1 and result.transcript_text == "Transcript"


def test_owner_change_after_progress_does_not_adopt_new_actor(recording_phase, monkeypatch):
    c = recording_phase
    new_id = str(uuid4())

    def replace(db):
        db.add(
            User(
                id=new_id,
                login_id=new_id,
                email="synthetic@example.invalid",
                full_name="Synthetic",
                password_hash="unusable",
            )
        )
        db.flush()
        db.get(Recording, c.recording_id).owner_id = new_id

    handoff(c, monkeypatch, 2, replace)
    with pytest.raises(Ignore):
        run(c)
    assert c.posts == []
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.owner_id == new_id and row.failure_reason is None


@pytest.mark.parametrize("accepted", [False, True])
def test_terminal_failure_commit_unknown_does_not_rewrite_failure(
    recording_phase, monkeypatch, accepted
):
    c = recording_phase
    c.response_status = 503
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit, count = db.commit, 0

    def uncertain():
        nonlocal count
        count += 1
        if count == 3:
            if accepted:
                commit()
            raise OSError("Synthetic failure acknowledgement lost")
        commit()

    monkeypatch.setattr(db, "commit", uncertain)
    task = c.task.transcribe_recording
    task.push_request(retries=3)
    try:
        with pytest.raises(c.task.RecordingPhaseCommitUnknown):
            run(c)
    finally:
        task.pop_request()
    assert count == 3 and len(c.posts) == 1
    with c.factory() as observer:
        row = observer.get(Recording, c.recording_id)
        assert (row.transcript_status == "failed") == accepted


@pytest.mark.parametrize("accepted", [False, True])
def test_commit_unknown_survives_rollback_failure(recording_phase, monkeypatch, accepted):
    c = recording_phase
    db = c.runtime_factory()
    c.sessions.append(db)
    monkeypatch.setattr(c.task, "_db_session", lambda: db)
    commit = db.commit

    def uncertain():
        if accepted:
            commit()
        raise OSError("Synthetic commit acknowledgement lost")

    def rollback():
        raise RuntimeError("Synthetic rollback failure")

    monkeypatch.setattr(db, "commit", uncertain)
    monkeypatch.setattr(db, "rollback", rollback)
    with pytest.raises(c.task.RecordingPhaseCommitUnknown):
        run(c)
    assert c.posts == [] and c.health == []
    with c.factory() as observer:
        row = observer.get(Recording, c.recording_id)
        assert row.failure_reason is None and row.celery_task_id == c.attempt_id


def test_finished_replay_rechecks_actor_without_writing(recording_phase):
    c = recording_phase
    assert run(c, "persist") == c.recording_id
    with c.factory.begin() as db:
        change(db, c.admin)
        db.get(User, c.admin["user"]["id"]).login_blocked = True
    with pytest.raises(Ignore):
        run(c, "persist")
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert (
            row.summary_status == "done"
            and row.failure_reason is None
            and row.celery_task_id is None
        )
