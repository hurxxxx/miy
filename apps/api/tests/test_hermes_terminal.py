from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from miy_api.core.settings import (
    HERMES_PROVIDER,
    Settings,
)
from miy_api.domains.auth.models import User, utcnow_naive
from miy_api.domains.hermes.models import HermesProfileBinding
from miy_api.domains.hermes_terminal import (
    lifecycle,
    maintenance,
    mcp_router,
)
from miy_api.domains.hermes_terminal.broker_runtime import (
    HermesTerminalBrokerRuntime,
    build_profile_sanitize_commands,
)
from miy_api.domains.hermes_terminal.legacy_policy import HERMES_MODEL
from miy_api.domains.hermes_terminal.models import HermesTerminalSession
from miy_api.domains.hermes_terminal.schemas import HermesTerminalSessionCreateRequest


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"postgres_dsn": "sqlite://"}
    values.update(overrides)
    with patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_yolo_requires_a_fresh_explicit_acknowledgement() -> None:
    assert HermesTerminalSessionCreateRequest().mode == "standard"
    with pytest.raises(ValidationError, match="explicit risk acknowledgement"):
        HermesTerminalSessionCreateRequest(mode="yolo")
    request = HermesTerminalSessionCreateRequest(mode="yolo", risk_acknowledged=True)
    assert request.mode == "yolo"
    assert request.risk_acknowledged is True


def test_broker_reconciles_only_old_namespaced_orphan_workspaces() -> None:
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    class FakeVolume:
        name = "miy-hermes-terminal-dev-workspace-orphan"
        attrs = {
            "CreatedAt": old,
            "Labels": {
                "miy.hermes-terminal.managed": "true",
                "miy.hermes-terminal.namespace": "dev",
                "miy.hermes-terminal.resource-kind": "workspace",
                "miy.hermes-terminal.session-id": str(uuid4()),
            },
        }

        def __init__(self) -> None:
            self.removed = False

        def remove(self, *, force: bool) -> None:
            assert force is True
            self.removed = True

    volume = FakeVolume()
    runtime = object.__new__(HermesTerminalBrokerRuntime)
    runtime.resource_namespace = "dev"
    runtime._forced_failure_codes = {}
    runtime.client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_kwargs: []),
        volumes=SimpleNamespace(list=lambda **_kwargs: [volume]),
    )

    result = runtime.reconcile_resources(known_session_ids=set())

    assert result == {
        "removed_runners": 0,
        "removed_workspaces": 1,
        "removed_utilities": 0,
    }
    assert volume.removed is True


def test_profile_export_removes_only_ephemeral_session_credentials() -> None:
    assert build_profile_sanitize_commands() == [
        [
            "/opt/hermes/.venv/bin/hermes",
            "config",
            "unset",
            "OPENROUTER_API_KEY",
        ],
        [
            "/opt/hermes/.venv/bin/hermes",
            "config",
            "unset",
            "MCP_MIY_API_KEY",
        ],
    ]


def test_missing_live_runtime_quarantines_workspace_instead_of_deleting_it(monkeypatch) -> None:
    row = SimpleNamespace(
        id="session-1",
        status="running",
        mode="standard",
        user_id="user-1",
        failure_code=None,
        archive_target_status=None,
        archive_started_at=None,
        archive_claim_token=None,
        archive_claim_expires_at=None,
        workspace_retained=False,
        quarantine_reason=None,
        ended_at=None,
        updated_at=None,
    )

    class FakeDb:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def scalar(self, _statement):
            return row

        def add(self, _value):
            return None

        def commit(self):
            return None

    class UnexpectedBrokerClient:
        async def forget_session(self, _session_id: str):
            raise AssertionError("A quarantined workspace must not be deleted")

    monkeypatch.setattr(lifecycle, "get_session_factory", lambda: lambda: FakeDb())
    monkeypatch.setattr(lifecycle, "record_audit_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(lifecycle, "HermesTerminalBrokerClient", UnexpectedBrokerClient)
    row.status = "starting"
    row.runtime_handle = None
    row.broker_instance_id = None
    row.started_at = None
    lifecycle._adopt_terminal_runtime(
        "session-1",
        SimpleNamespace(
            runtime_handle="container-1", broker_instance_id="broker-1", status="running"
        ),
    )
    assert row.status == "running" and row.runtime_handle == "container-1"
    assert row.broker_instance_id == "broker-1" and row.started_at is not None
    assert row.failure_code is None
    changed = asyncio.run(lifecycle.fail_missing_terminal_runtime("session-1", actor_user_id=None))
    assert changed is True
    assert row.status == "failed"
    assert row.failure_code == "hermes_terminal.runtime_missing"
    assert row.workspace_retained is True
    assert row.quarantine_reason == "hermes_terminal.runtime_missing"


@pytest.mark.parametrize("admission_retained", [True, False])
def test_write_tool_access_is_revalidated_after_approval(monkeypatch, admission_retained) -> None:
    identity = SimpleNamespace(
        session=SimpleNamespace(id="session-1", allowed_app_ids=["tasks"]),
        user=SimpleNamespace(id="user-1"),
    )
    tool = SimpleNamespace(
        descriptor=SimpleNamespace(
            name="tasks.create",
            approval_policy="required",
            owner_app_id="tasks",
        ),
        mcp_tool={"name": "tasks.create"},
    )
    resolve_calls: list[str] = []
    list_calls: list[str] = []
    tool_calls: list[str] = []

    def resolve_identity(_db, *, session_id, authorization):
        assert authorization == "Bearer session-token"
        resolve_calls.append(session_id)
        return identity

    def available_tools(_db, resolved_identity):
        assert resolved_identity is identity
        list_calls.append(resolved_identity.session.id)
        return SimpleNamespace(kind="user"), [tool]

    async def await_approval(_approval_id):
        return "external-call-1", "approved"

    class FakeMcpClient:
        def call_tool(self, _db, **kwargs):
            tool_calls.append(kwargs["tool_name"])
            assert kwargs["externally_approved_call_id"] == "external-call-1"
            return {"ok": True}

    class FakeDb:
        def expire_all(self):
            return None

        def get(self, model, _identifier):
            if model.__name__ == "User":
                return identity.user
            return None

        def commit(self):
            return None

        def rollback(self):
            raise AssertionError("The successful tool path must not roll back")

    class FakeRequest:
        async def json(self):
            return {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {
                    "name": "tasks.create",
                    "arguments": {"title": "Ship"},
                },
            }

    admission_calls = []

    def admitted(_db, *, user_id, app_id):
        admission_calls.append((user_id, app_id))
        return admission_retained

    monkeypatch.setattr(mcp_router, "can_use_app", admitted)
    monkeypatch.setattr(mcp_router, "_resolve_identity", resolve_identity)
    monkeypatch.setattr(mcp_router, "_available_tools", available_tools)
    monkeypatch.setattr(
        mcp_router,
        "_approval_for_call",
        lambda *_args, **_kwargs: SimpleNamespace(id="approval-1"),
    )
    monkeypatch.setattr(mcp_router, "_await_approval", await_approval)
    monkeypatch.setattr(mcp_router, "AiMcpClient", FakeMcpClient)

    response = asyncio.run(
        mcp_router.handle_mcp_request(
            FakeRequest(),  # type: ignore[arg-type]
            session="session-1",
            authorization="Bearer session-token",
            mcp_session_id=None,
            db=FakeDb(),  # type: ignore[arg-type]
        )
    )
    payload = json.loads(bytes(response.body))

    assert resolve_calls == ["session-1", "session-1"]
    assert list_calls == ["session-1", "session-1"]
    assert admission_calls == [("user-1", "hermes-terminal")]
    assert tool_calls == (["tasks.create"] if admission_retained else [])
    assert payload["result"]["isError"] is (not admission_retained)
    if not admission_retained:
        assert "hermes_terminal.identity_unavailable" in json.dumps(payload)


def test_archive_recovery_reclaims_stale_sessions_without_releasing_early(
    application_postgres_dsn: str,
    monkeypatch,
) -> None:
    engine = create_engine(application_postgres_dsn)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(maintenance, "get_session_factory", lambda: session_factory)
    now = utcnow_naive()
    stale = now - timedelta(minutes=15)
    suffix = uuid4().hex
    user = User(
        id=str(uuid4()),
        login_id=f"hermes-terminal-{suffix[:16]}",
        email=f"hermes-terminal-{suffix[:16]}@example.test",
        full_name="Hermes Terminal Recovery",
        password_hash="not-used",
    )
    binding = HermesProfileBinding(
        id=str(uuid4()),
        user_id=user.id,
        profile_name=f"miy-terminal-{suffix[:24]}",
        status="active",
        provider=HERMES_PROVIDER,
        model=HERMES_MODEL,
    )
    row = HermesTerminalSession(
        id=str(uuid4()),
        profile_binding_id=binding.id,
        user_id=user.id,
        title="Recovery session",
        mode="standard",
        status="archiving",
        allowed_app_ids=[],
        runtime_handle=f"runtime-{suffix}",
        broker_instance_id="test-broker",
        mcp_token_digest="a" * 64,
        cols=120,
        rows=32,
        archive_target_status="terminated",
        archive_attempts=1,
        archive_started_at=stale,
        last_activity_at=stale,
        idle_expires_at=stale,
        created_at=stale,
        updated_at=stale,
    )
    row_id = row.id
    user_id = user.id
    runtime_handle = row.runtime_handle
    try:
        with Session(engine) as db:
            db.add_all([user, binding, row])
            db.commit()

        claimed = maintenance._claim_archive_retries(limit=1)

        assert len(claimed) == 1
        assert claimed[0][:4] == (row_id, "terminated", None, user_id)
        assert len(claimed[0][4]) == 32
        with Session(engine) as db:
            stored = db.get(HermesTerminalSession, row_id)
            assert stored is not None
            assert stored.status == "archiving"
            assert stored.runtime_handle == runtime_handle
            assert stored.archive_claim_token == claimed[0][4]
            assert stored.archive_claim_expires_at is not None

        assert maintenance._claim_archive_retries(limit=1) == []
        with Session(engine) as db:
            stored = db.get(HermesTerminalSession, row_id)
            assert stored is not None
            stored.archive_attempts = 3
            stored.archive_failure_code = maintenance.HERMES_TERMINAL_ARCHIVE_FAILURE
            stored.updated_at = stale
            db.add(stored)
            db.commit()

        assert maintenance._abandon_exhausted_archives(limit=1) == 0
        with Session(engine) as db:
            stored = db.get(HermesTerminalSession, row_id)
            assert stored is not None
            stored.archive_claim_expires_at = stale
            stored.updated_at = stale - timedelta(seconds=1)
            db.add(stored)
            db.commit()

        assert maintenance._abandon_exhausted_archives(limit=1) == 1
        assert maintenance._runtime_release_candidates(limit=1) == []
        with Session(engine) as db:
            stored = db.get(HermesTerminalSession, row_id)
            assert stored is not None
            assert stored.status == "terminated"
            assert stored.archive_failure_code == "hermes_terminal.archive_failed"
            assert stored.workspace_retained is True
            assert stored.quarantine_reason == "hermes_terminal.archive_exhausted"
    finally:
        engine.dispose()
