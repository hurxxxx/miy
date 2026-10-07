"""Real gateway/authority/audit and PG transactions; synthetic native HTTP only."""

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from celery.exceptions import Ignore, Retry
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, TimeoutError as SqlAlchemyTimeoutError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from company_admission_fixture import seed_company_app_access
from miy_api.core.settings import get_settings
from miy_api.domains.ai import audit
from miy_api.domains.ai.model_settings_models import AiModelPolicyDefault
from miy_api.domains.auth.models import AuditLog, User
from miy_api.domains.hermes import execution, mcp_router, service as hermes_service, workloads
from miy_api.domains.hermes.models import HermesRunProjection
from miy_api.domains.hermes.service import mcp_profile_bearer_secret
from miy_api.domains.recording.models import Recording, RecordingResult
from test_llm_connection_policies import seed as seed_model
from test_official_writer_fence import change, wait_for_blockers, writer as writer


@pytest.fixture
def summary(writer, monkeypatch):
    factory, admin, _ = writer
    task = importlib.import_module("miy_worker.tasks.recording")
    # Existing Hermes dispatcher and validated callback need extra connections;
    # no separate source-fence connection is introduced by the worker.
    engine = create_engine(factory.kw["bind"].url, pool_size=3, max_overflow=0, pool_timeout=0.3)
    runtime_factory = sessionmaker(engine)
    recording_id, attempt_id = str(uuid4()), str(uuid4())
    with factory.begin() as db:
        seed_company_app_access(db, ["recording"])
        connection, _ = seed_model(db, "recording-synthetic")
        db.merge(
            AiModelPolicyDefault(
                model_family="generation",
                app_id="recording",
                route_mode="local",
                provider_id=connection.provider_id,
                max_output_tokens=8192,
            )
        )
        db.add(
            Recording(
                id=recording_id,
                owner_id=admin["user"]["id"],
                title="Synthetic",
                storage_key=f"recording/synthetic/{recording_id}",
                audio_status="saved",
                transcript_status="done",
                summary_status="pending",
                progress_pct=60,
                celery_task_id=attempt_id,
            )
        )
        db.flush()
        db.add(
            RecordingResult(
                recording_id=recording_id,
                transcript_text="Synthetic transcript",
                summary_text="Original summary",
                version=1,
            )
        )
    cfg = get_settings().model_copy(
        update={
            "hermes_enabled": True,
            "hermes_mcp_shared_secret": SecretStr("synthetic-worker-mcp"),
            "hermes_mcp_server_url": "http://platform.example.test/api/v1/hermes/mcp",
        }
    )
    for module in (workloads, hermes_service, mcp_router):
        monkeypatch.setattr(module, "get_settings", lambda: cfg)
    monkeypatch.setattr(workloads, "get_session_factory", lambda: runtime_factory)
    monkeypatch.setattr(audit, "get_session_factory", lambda: runtime_factory)
    sessions = []

    def worker_session():
        db = runtime_factory()
        sessions.append(db)
        return db

    monkeypatch.setattr(task, "_db_session", worker_session)
    c = SimpleNamespace(
        factory=factory,
        runtime_factory=runtime_factory,
        admin=admin,
        task=task,
        recording_id=recording_id,
        attempt_id=attempt_id,
        calls=[],
        sessions=sessions,
        on_provider=lambda: None,
        after_provider=lambda: None,
        reply="Synthetic summary",
        failure=False,
    )

    class Management:
        profiles = {}

        async def list_profiles(self):
            return {"profiles": list(self.profiles)}

        async def create_profile(self, *, profile_name, **kwargs):
            self.profiles[profile_name] = {}
            return {}

        async def update_profile_env(self, *args):
            return {}

        async def update_profile_config(self, *args):
            return {}

        async def list_mcp_servers(self, profile):
            return {"servers": list(self.profiles[profile].values())}

        async def add_mcp_server(self, profile, server):
            self.profiles[profile][server["name"]] = server
            return {}

        async def set_profile_mcp_trust(self, *args):
            return {}

    management = Management()
    monkeypatch.setattr(hermes_service, "management_client", lambda *_: management)

    class NativeRuntime:
        def __init__(self, **kwargs):
            pass

        async def create_run(self, profile, **kwargs):
            c.calls.append(kwargs["idempotency_key"])
            c.on_provider()
            if c.failure:
                from miy_api.domains.hermes.client import HermesClientError

                raise HermesClientError(
                    operation="create_run",
                    status_code=503,
                    code="synthetic.unavailable",
                    message="Synthetic failure",
                )
            return {"run_id": "native_" + kwargs["idempotency_key"], "status": "running"}

        async def iter_run_events(self, profile, run_id):
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "miy/submit",
                    "params": {"result": {"content": c.reply}},
                }
            ).encode()

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(
                {"type": "http", "method": "POST", "path": "/", "headers": []}, receive
            )
            with runtime_factory() as db:
                response = await mcp_router.handle_mcp_request(
                    request,
                    profile=profile,
                    authorization="Bearer " + mcp_profile_bearer_secret(cfg, profile),
                    mcp_session_id=None,
                    hermes_run_id=run_id,
                    db=db,
                )
                result = json.loads(response.body)["result"]
                assert not result.get("isError"), "Synthetic native result rejected"
            c.after_provider()
            yield {
                "event": "run.completed",
                "output": "done",
                "usage": {"input_tokens": 7, "output_tokens": 3},
            }

    monkeypatch.setattr(execution, "HermesRuntimeClient", NativeRuntime)
    try:
        yield c
    finally:
        for db in sessions:
            db.close()
        engine.dispose()


def run(c, phase):
    payload = {
        "recording_id": c.recording_id,
        "attempt_id": c.attempt_id,
        "result_version": 1,
        "summary": "Original summary",
    }
    task = c.task.analyze_transcript if phase == "analyze" else c.task.verify_transcript_summary
    return task.run(payload)


@pytest.mark.parametrize("phase", ["analyze", "verify"])
def test_real_gateway_and_authoritative_audit_are_retained(summary, phase):
    c = summary
    result = run(c, phase)
    assert result["result_version"] == 1 and result["attempt_id"] == c.attempt_id
    assert len(c.calls) == 1
    with c.factory() as db:
        row = db.get(RecordingResult, c.recording_id)
        assert (row.summary_text if phase == "analyze" else row.verifier_note) == c.reply
        runs = list(db.scalars(select(HermesRunProjection)))
        assert len(runs) == 1 and runs[0].status == "completed"
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "llm_call")))
        assert len(logs) == 1
        assert logs[0].payload["status"] == "ok"
        assert logs[0].payload["workload_id"] == "meeting_summary"


@pytest.mark.parametrize("phase", ["analyze", "verify"])
def test_drain_before_gateway_refuses_remote_admission(summary, monkeypatch, phase):
    c = summary
    if phase == "analyze":
        original = c.task._heartbeat

        def heartbeat(*args, **kwargs):
            original(*args, **kwargs)
            with c.factory.begin() as db:
                change(db, c.admin)

        monkeypatch.setattr(c.task, "_heartbeat", heartbeat)
    else:
        with c.factory.begin() as db:
            change(db, c.admin)
    with pytest.raises(DBAPIError):
        run(c, phase)
    assert c.calls == []


@pytest.mark.parametrize("phase", ["analyze", "verify"])
def test_source_drain_waits_for_real_gateway_and_audit_phase(summary, phase):
    c = summary
    entered, finish, draining = Event(), Event(), Event()
    pids = {}

    def remote():
        pids["worker"] = c.sessions[0].scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert finish.wait(20)

    c.on_provider = remote

    def drain():
        with c.factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            draining.set()
            return change(db, c.admin)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = pool.submit(run, c, phase)
        try:
            assert entered.wait(8)
            controller = pool.submit(drain)
            assert draining.wait(8)
            wait_for_blockers(c.factory, pids["controller"], {pids["worker"]})
            assert not controller.done()
            finish.set()
            assert result.result(timeout=10)["result_version"] == 1
            assert controller.result(timeout=10)["state"] == "draining"
        finally:
            finish.set()
    with c.factory() as db:
        assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "llm_call")))) == 1


@pytest.mark.parametrize("changed", ["attempt", "version"])
@pytest.mark.parametrize("when", ["loaded", "heartbeat"])
def test_analysis_does_not_adopt_replaced_attempt_or_version(summary, monkeypatch, changed, when):
    c = summary
    target = "_load_active_recording" if when == "loaded" else "_heartbeat"
    original = getattr(c.task, target)

    def replaced(*args, **kwargs):
        result = original(*args, **kwargs)
        with c.factory.begin() as db:
            if changed == "attempt":
                db.get(Recording, c.recording_id).celery_task_id = "replacement"
            else:
                row = db.get(RecordingResult, c.recording_id)
                row.version = 2
                row.transcript_text = "New transcript"
        return result

    monkeypatch.setattr(c.task, target, replaced)
    with pytest.raises(Ignore):
        run(c, "analyze")
    assert c.calls == []
    with c.factory() as db:
        assert db.get(Recording, c.recording_id).failure_reason is None


def test_verifier_rejects_payload_summary_drift_in_same_version(summary):
    c = summary
    with c.factory.begin() as db:
        db.get(RecordingResult, c.recording_id).summary_text = "Different current summary"
    with pytest.raises(Ignore):
        run(c, "verify")
    assert c.calls == []


@pytest.mark.parametrize("phase", ["analyze", "verify"])
def test_current_actor_revocation_discards_provider_result(summary, phase):
    c = summary

    def revoked():
        with c.factory.begin() as db:
            db.get(User, c.admin["user"]["id"]).login_blocked = True

    c.after_provider = revoked
    with pytest.raises(Ignore):
        run(c, phase)
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.summary_status == "failed" and row.celery_task_id is None
        result = db.get(RecordingResult, c.recording_id)
        assert result.summary_text == "Original summary" and result.verifier_note is None


@pytest.mark.parametrize("phase,at_commit", [("analyze", 1), ("analyze", 2), ("verify", 1)])
@pytest.mark.parametrize("accepted", [False, True])
def test_commit_ack_unknown_cannot_fail_or_retry_summary(
    summary, monkeypatch, phase, at_commit, accepted
):
    c = summary
    session = c.runtime_factory()
    c.sessions.append(session)
    monkeypatch.setattr(c.task, "_db_session", lambda: session)
    commit, count = session.commit, 0

    def uncertain():
        nonlocal count
        count += 1
        if count == at_commit:
            if accepted:
                commit()
            raise OSError("Synthetic lost commit acknowledgement")
        commit()

    monkeypatch.setattr(session, "commit", uncertain)
    with pytest.raises(c.task.RecordingSummaryCommitUnknown):
        run(c, phase)
    assert count == at_commit
    assert len(c.calls) == (0 if phase == "analyze" and at_commit == 1 else 1)
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.celery_task_id == c.attempt_id and row.failure_reason is None
        result = db.get(RecordingResult, c.recording_id)
        if phase == "analyze":
            assert result.summary_text == (
                c.reply if at_commit == 2 and accepted else "Original summary"
            )
        else:
            assert result.verifier_note == (c.reply if accepted else None)


@pytest.mark.parametrize("phase", ["analyze", "verify"])
@pytest.mark.parametrize("terminal", [False, True])
def test_known_provider_failure_keeps_existing_retry_and_terminal_policy(
    summary, monkeypatch, phase, terminal
):
    c = summary
    c.failure = True
    task = c.task.analyze_transcript if phase == "analyze" else c.task.verify_transcript_summary
    retries = []

    def retry(**kwargs):
        retries.append(kwargs["countdown"])
        raise Retry()

    monkeypatch.setattr(task, "retry", retry)
    task.push_request(retries=3 if terminal else 0)
    try:
        with pytest.raises(Ignore if terminal else Retry):
            run(c, phase)
    finally:
        task.pop_request()
    assert retries == ([] if terminal else [2])
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.summary_status == (
            "failed" if terminal else "analyzing" if phase == "analyze" else "pending"
        )
        assert (row.celery_task_id is None) is terminal
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "llm_call")))
        assert len(logs) == 1 and logs[0].payload["status"] == "error"


@pytest.mark.parametrize("changed", ["attempt", "version", "drain"])
def test_failed_provider_cannot_finalize_or_retry_replaced_claim(summary, monkeypatch, changed):
    c = summary
    c.failure = True
    session = c.runtime_factory()
    c.sessions.append(session)
    monkeypatch.setattr(c.task, "_db_session", lambda: session)
    original, replaced = session.rollback, False

    def rollback():
        nonlocal replaced
        original()
        if replaced:
            return
        replaced = True
        with c.factory.begin() as db:
            if changed == "attempt":
                db.get(Recording, c.recording_id).celery_task_id = "replacement"
            elif changed == "version":
                db.get(RecordingResult, c.recording_id).version = 2
            else:
                change(db, c.admin)

    monkeypatch.setattr(session, "rollback", rollback)
    with pytest.raises(DBAPIError if changed == "drain" else Ignore):
        run(c, "analyze")
    with c.factory() as db:
        row = db.get(Recording, c.recording_id)
        assert row.summary_status == "analyzing" and row.failure_reason is None


def test_single_connection_is_insufficient_for_existing_gateway_sessions_and_does_not_retry(
    summary, monkeypatch
):
    c = summary
    engine = create_engine(c.factory.kw["bind"].url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    factory = sessionmaker(engine)
    monkeypatch.setattr(c.task, "_db_session", lambda: factory())
    monkeypatch.setattr(workloads, "get_session_factory", lambda: factory)
    monkeypatch.setattr(audit, "get_session_factory", lambda: factory)
    try:
        with pytest.raises(SqlAlchemyTimeoutError):
            run(c, "analyze")
        assert c.calls == []
        with c.factory() as db:
            row = db.get(Recording, c.recording_id)
            assert row.summary_status == "analyzing" and row.failure_reason is None
            assert list(db.scalars(select(HermesRunProjection))) == []
    finally:
        engine.dispose()
