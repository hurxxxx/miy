from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from miy_api.domains.hermes import maintenance as hermes_maintenance
from miy_api.domains.hermes import mcp_router
from miy_api.domains.hermes import router as hermes_router
from miy_api.domains.hermes import service as hermes_service
from miy_api.domains.hermes.client import (
    HermesClientError,
)
from miy_api.domains.hermes.model_policy import HermesModelPolicy
from miy_api.domains.hermes.models import (
    HermesMaintenanceState,
)
from miy_api.domains.hermes.repository import (
    sanitize_event_payload,
    utcnow_naive,
)
from miy_api.domains.hermes.research_sources import DEFAULT_RESEARCH_SOURCE_POLICY
from miy_api.domains.hermes.schemas import HermesApprovalDecision
from miy_api.domains.hermes.service import (
    ensure_job_profile,
    internal_mcp_server_name,
    job_profile_name,
    mcp_profile_bearer_secret,
)

HERMES_MODEL = "test/configured-model"

pytestmark = pytest.mark.anyio


async def test_headless_maintenance_skips_while_another_lease_is_live(
    application_postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(application_postgres_dsn)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(hermes_maintenance, "get_session_factory", lambda: factory)
    lease_started_at = utcnow_naive()
    try:
        with Session(engine) as db:
            db.add(
                HermesMaintenanceState(
                    component="headless",
                    counters={"previous": 1},
                    lease_token="active-maintenance-lease",
                    lease_expires_at=lease_started_at + timedelta(minutes=1),
                    last_started_at=lease_started_at,
                )
            )
            db.commit()

        assert await hermes_maintenance.maintain_headless_hermes_once(limit=1) == {
            "maintenance_skipped": 1,
            "errors": 0,
        }

        with Session(engine) as db:
            state = db.get(HermesMaintenanceState, "headless")
            assert state is not None
            assert state.lease_token == "active-maintenance-lease"
            assert state.counters == {"previous": 1}
            assert state.last_started_at == lease_started_at
    finally:
        engine.dispose()


def test_revoked_run_scan_advances_past_authorized_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(run_scan_cursor=None)
    authorized = [
        SimpleNamespace(
            id=f"00000000-0000-0000-0000-{index:012d}",
            user_id=f"allowed-{index}",
            owner_app_id="chatbot",
            status="running",
            execution_claim_token=None,
            execution_claim_expires_at=None,
            hermes_run_id=f"remote-{index}",
            profile_binding_id=f"profile-{index}",
        )
        for index in range(1, 6)
    ]
    revoked = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000006",
        user_id="revoked-user",
        owner_app_id="chatbot",
        status="running",
        execution_claim_token=None,
        execution_claim_expires_at=None,
        hermes_run_id="remote-revoked",
        profile_binding_id="profile-revoked",
    )
    pages = iter([authorized, [revoked]])
    appended: list[str] = []

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def scalars(self, _statement):
            return iter(next(pages))

        def get(self, _model, binding_id: str):
            return SimpleNamespace(profile_name=f"name-{binding_id}")

        def add(self, _value):
            return None

        def commit(self):
            return None

    class FakeRepository:
        def __init__(self, _db):
            pass

        def append_event(self, run_id: str, _payload):
            appended.append(run_id)

    monkeypatch.setattr(
        hermes_maintenance,
        "get_session_factory",
        lambda: lambda: FakeDb(),
    )
    monkeypatch.setattr(
        hermes_maintenance,
        "_maintenance_state_for_update",
        lambda _db: state,
    )
    monkeypatch.setattr(
        hermes_maintenance,
        "can_use_app",
        lambda _db, **kwargs: kwargs["user_id"] != "revoked-user",
    )
    monkeypatch.setattr(
        hermes_maintenance,
        "HermesRunRepository",
        FakeRepository,
    )

    assert hermes_maintenance._claim_revoked_runs(limit=1) == []
    assert state.run_scan_cursor == authorized[-1].id
    assert hermes_maintenance._claim_revoked_runs(limit=1) == [
        (revoked.id, "name-profile-revoked", "remote-revoked")
    ]
    assert appended == [revoked.id]


def _mcp_approval_payload(
    profile_name: str, tool_name: str, arguments: dict | None = None
) -> dict[str, Any]:
    return {
        "command": (
            f"MCP tool '{tool_name}' on UNTRUSTED server "
            f"'{internal_mcp_server_name(profile_name)}' wants to run. This tool is "
            "write-capable (no readOnlyHint=true annotation) and may modify external "
            "state."
        ),
        "description": f"Approve this call once. Arguments SHA-256: {mcp_router._arguments_sha256(arguments or {})}",
        "pattern_key": "mcp_elicitation",
        "pattern_keys": ["mcp_elicitation"],
        "request_id": "approval-1",
    }


def test_mcp_write_approval_is_consumed_once_and_bound_to_arguments() -> None:
    approval = SimpleNamespace(
        id="approval-row-1",
        request_payload=_mcp_approval_payload(
            "miy-profile-a", "tasks.create", {"title": "Ship Hermes", "priority": 2}
        ),
        consumed_at=None,
        consumed_tool_name=None,
        consumed_arguments_sha256=None,
        external_call_id=None,
    )

    class FakeDb:
        def __init__(self) -> None:
            self.commits = 0

        def scalars(self, _query):
            return [approval]

        def add(self, row):
            assert row is approval

        def commit(self):
            self.commits += 1

    db = FakeDb()
    arguments = {"title": "Ship Hermes", "priority": 2}

    external_call_id = mcp_router._consume_external_tool_approval(
        db,
        run_id="run-1",
        profile_name="miy-profile-a",
        tool_name="tasks.create",
        arguments=arguments,
    )

    assert external_call_id is not None
    assert approval.external_call_id == external_call_id
    assert approval.consumed_tool_name == "tasks.create"
    assert approval.consumed_arguments_sha256 == mcp_router._arguments_sha256(arguments)
    assert approval.consumed_at is not None
    assert db.commits == 1
    assert (
        mcp_router._consume_external_tool_approval(
            db,
            run_id="run-1",
            profile_name="miy-profile-a",
            tool_name="tasks.create",
            arguments=arguments,
        )
        is None
    )
    assert db.commits == 1


async def test_approval_is_committed_before_hermes_resumes(monkeypatch) -> None:
    run = SimpleNamespace(
        id="run-1",
        hermes_run_id="hermes-run-1",
        profile_binding_id="profile-1",
        owner_app_id="chatbot",
    )
    approval = SimpleNamespace(
        id="approval-1",
        status="pending",
        choice=None,
        decided_by_user_id=None,
        decided_at=None,
        consumed_at=None,
    )
    commits: list[str] = []
    events: list[dict[str, Any]] = []

    class FakeDb:
        def scalar(self, _query):
            return approval

        def add(self, _row):
            return None

        def commit(self):
            commits.append(approval.status)

        def rollback(self):
            raise AssertionError("The successful approval path must not roll back")

    class FakeRepository:
        def get_owned(self, *_args, **_kwargs):
            return run

        def append_event(self, _run_id, payload):
            events.append(payload)

        def get(self, _run_id):
            return run

    class FakeRuntimeClient:
        async def resolve_approval(self, *_args, **_kwargs):
            assert commits == ["approved"]
            assert approval.choice == "once"
            assert approval.decided_by_user_id == "user-1"
            assert approval.decided_at is not None
            return {"status": "running", "request_id": "request-1"}

    class FakeResponse:
        @classmethod
        def model_validate(cls, value):
            return value

    async def fake_profile_for_request(*_args, **_kwargs):
        return SimpleNamespace(profile_name="profile-1")

    monkeypatch.setattr(hermes_router, "HermesRunRepository", lambda _db: FakeRepository())
    monkeypatch.setattr(hermes_router, "can_use_app", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        hermes_router,
        "_bound_profile",
        lambda *_args, **_kwargs: SimpleNamespace(profile_name="profile-1"),
    )
    monkeypatch.setattr(hermes_router, "runtime_client", lambda: FakeRuntimeClient())
    monkeypatch.setattr(hermes_router, "HermesRunResponse", FakeResponse)

    result = await hermes_router.resolve_approval(
        "run-1",
        HermesApprovalDecision(request_id="request-1", choice="once"),
        db=FakeDb(),
        current_user=SimpleNamespace(id="user-1"),
    )

    assert result is run
    assert commits == ["approved", "approved"]
    assert events == [
        {
            "event": "approval.responded",
            "status": "running",
            "request_id": "request-1",
        }
    ]


async def test_failed_hermes_resume_restores_unconsumed_approval(monkeypatch) -> None:
    run = SimpleNamespace(
        id="run-1",
        hermes_run_id="hermes-run-1",
        profile_binding_id="profile-1",
        owner_app_id="chatbot",
    )
    approval = SimpleNamespace(
        id="approval-1",
        status="pending",
        choice=None,
        decided_by_user_id=None,
        decided_at=None,
        consumed_at=None,
    )
    commits: list[str] = []
    rollbacks = 0

    class FakeDb:
        def scalar(self, _query):
            return approval

        def add(self, _row):
            return None

        def commit(self):
            commits.append(approval.status)

        def rollback(self):
            nonlocal rollbacks
            rollbacks += 1

    class FakeRepository:
        def get_owned(self, *_args, **_kwargs):
            return run

    class FailingRuntimeClient:
        async def resolve_approval(self, *_args, **_kwargs):
            raise HermesClientError(
                operation="resolve approval",
                status_code=503,
                code="hermes.unavailable",
                message="Hermes unavailable",
            )

    async def fake_profile_for_request(*_args, **_kwargs):
        return SimpleNamespace(profile_name="profile-1")

    monkeypatch.setattr(hermes_router, "HermesRunRepository", lambda _db: FakeRepository())
    monkeypatch.setattr(hermes_router, "can_use_app", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        hermes_router,
        "_bound_profile",
        lambda *_args, **_kwargs: SimpleNamespace(profile_name="profile-1"),
    )
    monkeypatch.setattr(hermes_router, "runtime_client", lambda: FailingRuntimeClient())

    with pytest.raises(HTTPException) as error:
        await hermes_router.resolve_approval(
            "run-1",
            HermesApprovalDecision(request_id="request-1", choice="once"),
            db=FakeDb(),
            current_user=SimpleNamespace(id="user-1"),
        )

    assert error.value.status_code == 502
    assert commits == ["approved", "pending"]
    assert rollbacks == 1
    assert approval.choice is None
    assert approval.decided_by_user_id is None
    assert approval.decided_at is None


async def test_scheduled_jobs_use_a_separate_profile_without_any_mcp() -> None:
    binding = SimpleNamespace(profile_name="miy-owner-profile")
    removed: list[tuple[str, str]] = []
    servers = {"miy", "third-party"}

    class FakeManagementClient:
        async def update_profile_config(self, *_args, **_kwargs):
            return {"ok": True}

        async def update_profile_env(self, *_args, **_kwargs):
            return {"ok": True}

        async def list_profiles(self):
            return {"profiles": [{"name": "miy-owner-profile-jobs"}]}

        async def set_profile_model(self, profile_name, **_kwargs):
            assert profile_name == "miy-owner-profile-jobs"
            return {"ok": True}

        async def list_mcp_servers(self, profile_name):
            assert profile_name == "miy-owner-profile-jobs"
            return {"servers": [{"name": name} for name in sorted(servers)]}

        async def remove_mcp_server(self, profile_name, server_name):
            removed.append((profile_name, server_name))
            servers.discard(server_name)
            return {"ok": True}

    settings = SimpleNamespace(hermes_enabled=True)
    profile_name = await ensure_job_profile(
        binding,
        model_policy=HermesModelPolicy(
            "external", "openai", "test-model", "https://example.test/v1", "test-key", 1024
        ),
        settings=settings,
        client=FakeManagementClient(),
    )

    assert profile_name == job_profile_name(binding)
    assert removed == [
        ("miy-owner-profile-jobs", "miy"),
        ("miy-owner-profile-jobs", "third-party"),
    ]


@pytest.mark.parametrize(
    "route,profile_exists,reject_config",
    [
        ("local", False, False),
        ("external", True, False),
        ("local", True, True),
    ],
)
async def test_profile_reconciliation_enforces_compression_before_activation(
    monkeypatch,
    route,
    profile_exists,
    reject_config,
) -> None:
    profile_name = f"miy-{uuid4().hex}" + ("-local" if route == "local" else "")
    binding = SimpleNamespace(
        profile_name=profile_name,
        status="active" if profile_exists else "pending",
        last_error_code=None,
        last_reconciled_at=None,
        provisioned_at=None,
    )
    monkeypatch.setattr(
        hermes_service,
        "get_or_create_profile_binding",
        lambda _db, **_kwargs: binding,
    )
    reconciled_cache = {}
    monkeypatch.setattr(hermes_service, "_profile_reconciled_until", reconciled_cache)
    configs: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []

    class FakeManagementClient:
        async def list_profiles(self):
            return {"profiles": [{"name": profile_name}] if profile_exists else []}

        async def create_profile(self, **kwargs):
            created.append(kwargs)
            return {"ok": True}

        async def update_profile_env(self, *_args):
            return {"ok": True}

        async def update_profile_config(self, resolved_profile_name, config):
            assert resolved_profile_name == profile_name
            configs.append(config)
            if reject_config:
                raise HermesClientError(
                    operation="update_profile_config",
                    status_code=503,
                    code="hermes.config_unavailable",
                    message="Configuration unavailable.",
                )
            return {"ok": True}

        async def list_mcp_servers(self, _profile_name):
            return {"servers": []}

    db = SimpleNamespace(
        add=lambda _row: None,
        commit=lambda: None,
        refresh=lambda _row: None,
    )
    settings = SimpleNamespace(
        hermes_enabled=True,
        hermes_api_key=SimpleNamespace(get_secret_value=lambda: "test-api-server-key"),
        hermes_mcp_server_url="",
    )
    kwargs = {
        "model_policy": HermesModelPolicy(
            route,
            "openai",
            "test-model",
            "http://model.test/v1",
            "test-key",
            1024,
        ),
        "user": SimpleNamespace(),
        "settings": settings,
        "client": FakeManagementClient(),
        "research_sources": dict(DEFAULT_RESEARCH_SOURCE_POLICY),
        "research_policy_revision": 1,
    }
    if reject_config:
        with pytest.raises(HermesClientError):
            await hermes_service.ensure_profile_binding(db, **kwargs)
        assert binding.status == "error"
        assert not reconciled_cache
    else:
        assert await hermes_service.ensure_profile_binding(db, **kwargs) is binding
        assert binding.status == "active"
        assert reconciled_cache

    assert len(created) == (0 if profile_exists else 1)
    if created:
        assert created[0]["clone_from"] is None
    policy_config = configs[0]
    assert policy_config["compression"] == {
        "enabled": True,
        "threshold": 0.50,
        "threshold_tokens": 100_000,
        "target_ratio": 0.20,
        "protect_last_n": 20,
        "proactive_prune_tokens": 48_000,
        "proactive_prune_min_result_chars": 8_000,
        "proactive_prune_min_reclaim_tokens": 4_096,
    }
    assert policy_config["auxiliary"]["compression"]["provider"] == "main"
    assert policy_config["fallback_providers"] == []
    assert "session_search" not in policy_config["platform_toolsets"]["api_server"]


def test_mcp_profile_secret_is_scoped_and_event_payloads_are_redacted() -> None:
    settings = SimpleNamespace(
        hermes_mcp_shared_secret=SimpleNamespace(
            get_secret_value=lambda: "mcp-root-secret-00000000000000000001"
        )
    )
    first = mcp_profile_bearer_secret(settings, "profile-a")
    second = mcp_profile_bearer_secret(settings, "profile-b")

    assert len(first) == 64
    assert first != second
    assert first == mcp_profile_bearer_secret(settings, "profile-a")
    assert sanitize_event_payload(
        {
            "event": "tool.result",
            "Authorization": "Bearer secret",
            "nested": {"api-key": "secret", "safe": "visible"},
        }
    ) == {
        "event": "tool.result",
        "Authorization": "[REDACTED]",
        "nested": {"api-key": "[REDACTED]", "safe": "visible"},
    }
