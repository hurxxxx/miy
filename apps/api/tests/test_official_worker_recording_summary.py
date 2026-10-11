"""Real gateway/authority/audit and PG transactions; synthetic native HTTP only."""

import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from company_admission_fixture import seed_company_app_access
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from test_llm_connection_policies import seed as seed_model
from test_official_writer_fence import writer as writer

from miy_api.core.settings import get_settings
from miy_api.domains.ai import audit
from miy_api.domains.ai.model_settings_models import AiModelPolicyDefault
from miy_api.domains.auth.models import AuditLog
from miy_api.domains.hermes import execution, mcp_router, workloads
from miy_api.domains.hermes import service as hermes_service
from miy_api.domains.hermes.models import HermesRunProjection
from miy_api.domains.hermes.service import mcp_profile_bearer_secret
from miy_api.domains.recording.models import Recording, RecordingResult


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


def test_real_gateway_and_authoritative_audit_are_retained(summary):
    c = summary
    analyzed = run(c, "analyze")
    assert analyzed["result_version"] == 1 and analyzed["attempt_id"] == c.attempt_id
    verified = c.task.verify_transcript_summary.run(analyzed)
    assert verified["result_version"] == 1 and verified["attempt_id"] == c.attempt_id
    assert len(c.calls) == 2
    with c.factory() as db:
        row = db.get(RecordingResult, c.recording_id)
        assert row.summary_text == c.reply and row.verifier_note == c.reply
        runs = list(db.scalars(select(HermesRunProjection)))
        assert len(runs) == 2 and all(run.status == "completed" for run in runs)
        logs = list(db.scalars(select(AuditLog).where(AuditLog.action == "llm_call")))
        assert len(logs) == 2
        assert all(
            log.payload["status"] == "ok" and log.payload["workload_id"] == "meeting_summary"
            for log in logs
        )


@pytest.mark.parametrize(
    "phase,at_commit,accepted", [("analyze", 1, False), ("analyze", 2, True), ("verify", 1, True)]
)
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
