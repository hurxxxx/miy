"""Real source transactions and ASR adapter; synthetic storage/HTTP only."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from celery.exceptions import Ignore
from company_admission_fixture import seed_company_app_access
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from test_official_writer_fence import change, wait_for_blockers
from test_official_writer_fence import writer as writer

from miy_api.core import asr
from miy_api.domains.recording.models import Recording, RecordingResult


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


def test_live_http_holds_source_until_callback_handoff(recording_phase):
    c = recording_phase
    entered, finish, draining = Event(), Event(), Event()
    ready = Event()
    pids = {}

    def remote():
        pids["worker"] = c.sessions[0].scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        ready.set()
        assert finish.wait(20)

    c.on_post = remote

    def drain():
        with c.factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            draining.set()
            return change(db, c.admin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pool.submit(run, c)
        result.add_done_callback(lambda _: ready.set())
        try:
            assert ready.wait(8)
            if not entered.is_set():
                result.result()
                pytest.fail("ASR worker completed before entering synthetic HTTP")
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


@pytest.mark.parametrize("at_commit,accepted", [(1, False), (1, True), (4, False), (4, True)])
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


@pytest.mark.parametrize("changed", ["attempt", "version"])
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
