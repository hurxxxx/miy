"""Files worker source fence on an owned PostgreSQL, synthetic object store only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import importlib
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from miy_api.domains.files.models import FileManagerStorageCleanupJob
from test_official_writer_fence import change, wait_for_blockers, writer as writer


@pytest.fixture
def cleanup(writer, monkeypatch):
    factory, admin, _ = writer
    tasks = importlib.import_module("miy_worker.tasks.file_storage_cleanup")
    # One worker connection: an outer fence connection would exhaust this pool.
    engine = create_engine(factory.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=1)
    worker_factory = sessionmaker(bind=engine)
    sessions, calls = [], []

    def session():
        value = worker_factory()
        sessions.append(value)
        return value

    job_id, key = str(uuid4()), f"files/synthetic/{uuid4()}"
    with factory.begin() as db:
        db.add(FileManagerStorageCleanupJob(id=job_id, storage_key=key, attempts=1))
    store = SimpleNamespace(remove_object=lambda bucket, name: calls.append((bucket, name)))
    monkeypatch.setattr(tasks, "_db_session", session)
    monkeypatch.setattr(tasks, "_minio_client", lambda: store)
    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(minio_bucket="synthetic"))
    try:
        yield SimpleNamespace(
            tasks=tasks, factory=factory, admin=admin, sessions=sessions, calls=calls,
            job_id=job_id, key=key, store=store, worker_factory=worker_factory,
        )
    finally:
        for value in sessions:
            value.close()
        engine.dispose()


@pytest.mark.parametrize("when", ["before_claim", "after_claim"])
def test_drain_denies_delete_before_effect(cleanup, monkeypatch, when):
    c = cleanup
    if when == "before_claim":
        with c.factory.begin() as db:
            change(db, c.admin)
    else:
        original = c.tasks._claim_cleanup_job

        def claim(*args, **kwargs):
            result = original(*args, **kwargs)
            with c.factory.begin() as db:
                change(db, c.admin)
            return result

        monkeypatch.setattr(c.tasks, "_claim_cleanup_job", claim)
    with pytest.raises(DBAPIError) as error:
        c.tasks.cleanup_file_storage_object.run(c.job_id)
    assert error.value.orig.sqlstate == "55000"
    assert c.calls == []
    with c.factory() as db:
        job = db.get(FileManagerStorageCleanupJob, c.job_id)
        assert job.status == "pending" and job.attempts == (1 if when == "before_claim" else 2)


def test_drain_waits_for_inflight_delete_and_exact_result_with_one_worker_connection(cleanup):
    c = cleanup
    entered, finish, controller_entered = Event(), Event(), Event()
    pids = {}

    def remove(bucket, key):
        c.calls.append((bucket, key))
        pids["worker"] = c.sessions[0].scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert finish.wait(15)

    c.store.remove_object = remove

    def drain():
        with c.factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            controller_entered.set()
            return change(db, c.admin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pool.submit(c.tasks.cleanup_file_storage_object.run, c.job_id)
        try:
            assert entered.wait(8)
            controller = pool.submit(drain)
            assert controller_entered.wait(8)
            wait_for_blockers(c.factory, pids["controller"], {pids["worker"]})
            assert not controller.done()
            finish.set()
            assert result.result(timeout=8) == "succeeded"
            assert controller.result(timeout=8)["state"] == "draining"
        finally:
            finish.set()
    assert c.calls == [("synthetic", c.key)]
    with c.factory() as db:
        assert db.get(FileManagerStorageCleanupJob, c.job_id).status == "succeeded"


@pytest.mark.parametrize("changed", ["attempt", "key", "deadline", "expired", "status"])
def test_effect_rechecks_immutable_claim_after_commit(cleanup, monkeypatch, changed):
    c = cleanup
    original = c.tasks._claim_cleanup_job

    def claim(*args, **kwargs):
        result = original(*args, **kwargs)
        with c.factory.begin() as db:
            job = db.get(FileManagerStorageCleanupJob, c.job_id)
            if changed == "attempt":
                job.attempts += 1
            elif changed == "key":
                job.storage_key += "-replacement"
            elif changed == "deadline":
                job.next_retry_at += timedelta(seconds=30)
            elif changed == "expired":
                expired = job.next_retry_at + timedelta(seconds=1)
                monkeypatch.setattr(c.tasks, "_utcnow", lambda: expired)
            else:
                job.status = "succeeded"
        return result

    monkeypatch.setattr(c.tasks, "_claim_cleanup_job", claim)
    assert c.tasks.cleanup_file_storage_object.run(c.job_id) == "lost_lease"
    assert c.calls == []


def test_expiry_during_locked_effect_does_not_discard_its_outcome(cleanup, monkeypatch):
    c = cleanup

    def remove(bucket, key):
        c.calls.append((bucket, key))
        expired = c.tasks._utcnow() + c.tasks.CLAIM_LEASE + timedelta(seconds=1)
        monkeypatch.setattr(c.tasks, "_utcnow", lambda: expired)
        with c.factory() as contender:
            status, claim = c.tasks._claim_cleanup_job(contender, job_id=c.job_id)
            assert status == "leased" and claim is None

    c.store.remove_object = remove
    assert c.tasks.cleanup_file_storage_object.run(c.job_id) == "succeeded"
    assert c.calls == [("synthetic", c.key)]


@pytest.mark.parametrize("at_commit,accepted", [(1, False), (1, True), (2, False), (2, True)])
def test_commit_unknown_never_reexecutes_delete_or_writes_new_retry(cleanup, monkeypatch, at_commit, accepted):
    c = cleanup
    session = c.worker_factory()
    c.sessions.append(session)
    monkeypatch.setattr(c.tasks, "_db_session", lambda: session)
    commit = session.commit
    count = 0

    def uncertain():
        nonlocal count
        count += 1
        if count == at_commit:
            if accepted:
                commit()
            raise OSError("synthetic commit acknowledgement lost")
        commit()

    monkeypatch.setattr(session, "commit", uncertain)
    with pytest.raises(OSError, match="synthetic commit"):
        c.tasks.cleanup_file_storage_object.run(c.job_id)
    assert count == at_commit
    assert len(c.calls) == (0 if at_commit == 1 else 1)
    with c.factory() as db:
        job = db.get(FileManagerStorageCleanupJob, c.job_id)
        assert job.status == ("succeeded" if at_commit == 2 and accepted else "pending")
        assert job.attempts == (1 if at_commit == 1 and not accepted else 2)
        assert job.last_error is None
