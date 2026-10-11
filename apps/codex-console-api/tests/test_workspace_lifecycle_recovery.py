"""Partial native lifecycle recovery uses disposable SQLite/Git and owned doubles."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_environment as environment
from codex_console import workspaces
from codex_console.config import DeliveryGrant
from codex_console.errors import ConsoleError
from codex_console.models import Agent, ResourceLease, Task, WorkbenchWorkspace, WorkspaceOperation
from codex_console.runtime import Runtime
from codex_console.workspace_schemas import WorkspaceAction

# Preserve the real adapters before the managed fixture installs its ready doubles.
NATIVE_ENVIRONMENT_FOR = environment.environment_for
NATIVE_PREPARE = environment.prepare
NATIVE_STOP = environment.stop
NATIVE_CLEANUP = environment.cleanup


def task_history(settings, factory, row, *, status="idle"):
    with factory.begin() as db:
        selected = workspaces.context(settings, db, {"workspace_id": row.id})
        task = Task(
            title="Disposable history",
            workspace_id=row.id,
            context=selected,
            root=selected["source_binding"]["executor_root"],
            status=status,
        )
        db.add(task)
        db.flush()
        return task.id


def stopped_descriptor(monkeypatch, state):
    calls = []

    def helper(settings, selected, action):
        calls.append(action)
        if action == "describe":
            # A stopped SDK has no usable execution descriptor, matching the
            # native operator helper rather than an always-ready Runtime double.
            raise ConsoleError("workspace_environment_unavailable", 409)
        assert action in {"stop", "cleanup", "status"}
        return {"state": "cleaned" if action == "cleanup" else state}

    monkeypatch.setattr(environment, "_helper", helper)
    monkeypatch.setattr(environment, "environment_for", NATIVE_ENVIRONMENT_FOR)
    return calls


@pytest.mark.parametrize("sdk_state", ["stopped", "cleaned"])
def test_partial_cleanup_retries_with_idle_task_history_and_unavailable_descriptor(
    managed, monkeypatch, sdk_state
):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    task_id = task_history(settings, factory, row)
    operation_id = str(uuid4())
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.state = "cleanup_pending"
        saved.admission_open = False
        saved.integration = {"state": "succeeded", "merged_revision": row.source_revision}
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="cleanup",
                state="waiting",
                source_revision=row.source_revision,
                digest="disposable-approved-cleanup",
                receipt={"source_handoff_complete": True},
            )
        )
    calls = stopped_descriptor(monkeypatch, sdk_state)
    runtime = Runtime(settings, factory)
    with pytest.raises(ConsoleError, match="workspace_environment_unavailable"):
        runtime.for_task(task_id)
    assert calls == ["describe"]
    calls.clear()
    monkeypatch.setattr(environment, "stop", NATIVE_STOP)
    monkeypatch.setattr(environment, "cleanup", NATIVE_CLEANUP)
    core_reads = []

    async def core_read(cfg, selected, suffix, body=None, **kwargs):
        assert suffix == "/context" and body is None
        core_reads.append(suffix)
        return {"state": "cleaned", "version": 1, "source_handoff_complete": True}

    removals = []

    async def remove_remote(cfg, item, record):
        removals.append("owned-remote")

    def remove_local(cfg, item):
        removals.append("owned-local")

    monkeypatch.setattr(environment, "_call", core_read)
    monkeypatch.setattr(workspaces.workspace_gitlab, "remove_remote", remove_remote)
    monkeypatch.setattr(workspaces.workspace_git, "remove", remove_local)
    app = SimpleNamespace(
        state=SimpleNamespace(settings=settings, factory=factory, runtime=runtime)
    )
    completed = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "cleanup",
            WorkspaceAction(operation_id=operation_id, expected_version=row.version),
        )
    )
    assert completed.state == "cleaned" and not completed.admission_open
    assert calls == ["stop", "cleanup"] and core_reads == ["/context", "/context"]
    assert removals == ["owned-remote", "owned-local"]
    with factory() as db:
        assert db.get(Task, task_id).status == "idle"
        operation = db.get(WorkspaceOperation, operation_id)
        assert operation.state == "succeeded" and operation.receipt["source_handoff_complete"]
    assert runtime.rpc is None and runtime.app_runtimes == {}


@pytest.mark.parametrize("activity", ["uncertain_task", "active_child", "lease"])
def test_stopped_executor_does_not_remove_active_or_uncertain_cleanup_fences(
    managed, monkeypatch, activity
):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    task_id = task_history(settings, factory, row)
    with factory.begin() as db:
        if activity == "uncertain_task":
            db.get(Task, task_id).status = "uncertain"
        elif activity == "active_child":
            db.add(
                Agent(
                    thread_id="disposable-child",
                    parent_thread_id="disposable-root",
                    task_id=task_id,
                    status="running",
                )
            )
        else:
            db.add(ResourceLease(task_id=task_id, resource="disposable-source"))
        item = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    calls = stopped_descriptor(monkeypatch, "stopped")
    runtime = Runtime(settings, factory)
    app = SimpleNamespace(
        state=SimpleNamespace(settings=settings, factory=factory, runtime=runtime)
    )
    expected = "workspace_busy" if activity == "lease" else "workspace_environment_unavailable"
    with pytest.raises(ConsoleError, match=expected):
        asyncio.run(workspaces.stop_tasks(app, item))
    assert calls == ([] if activity == "lease" else ["describe"])
    with factory() as db:
        assert workspaces.busy(db, row.id)
    assert runtime.rpc is None and runtime.app_runtimes == {}


@pytest.mark.parametrize("has_core_grant", [False, True])
def test_first_sdk_prepare_lost_ack_is_resolved_by_same_create_read_only_evidence(
    managed, monkeypatch, has_core_grant
):
    settings, factory, project_id, _ = managed
    if has_core_grant:
        settings.miy_api_origin = "https://core.invalid"
        settings.app_delivery_grants = [
            DeliveryGrant(
                app_id="equipment-test",
                installation_id=uuid4(),
                token="disposable-server-grant-only",
            )
        ]
    calls, reads = [], []
    sdk_ready = False

    def helper(cfg, selected, action):
        nonlocal sdk_ready
        calls.append(action)
        if action == "prepare":
            sdk_ready = True
            raise ConsoleError("workspace_operation_unknown", 409)
        assert sdk_ready
        if action == "status":
            return {"state": "ready"}
        assert action == "describe"
        return {
            "key": "owned-disposable-executor",
            "source_root": str(Path(selected["worktree_path"]) / selected["app_directory"]),
            "exec_server_url": "ws://127.0.0.1:19999",
            "auth_bearer_token": "disposable-executor-credential-only",
        }

    async def read_core(cfg, grant, suffix, *, body=None, **kwargs):
        assert body is None and suffix.endswith("/context")
        reads.append(suffix)
        return None

    monkeypatch.setattr(environment, "prepare", NATIVE_PREPARE)
    monkeypatch.setattr(environment, "environment_for", NATIVE_ENVIRONMENT_FOR)
    monkeypatch.setattr(environment, "_helper", helper)
    monkeypatch.setattr(environment.delivery_tools, "api_request", read_core)
    failed, body = create(managed)
    assert failed.state == "error" and not failed.admission_open
    with factory() as db:
        operation = db.get(WorkspaceOperation, str(body.operation_id))
        assert operation.state == "unknown" and operation.receipt == {}
        assert operation.source_revision == failed.source_revision
    observed = asyncio.run(workspaces.observe(settings, factory, failed.id))
    assert observed.id == failed.id and observed.source_revision == failed.source_revision
    assert observed.state == "ready" and observed.admission_open
    assert observed.preview.state == "unconfigured" and observed.preview.runtime_revision is None
    assert observed.preview.portal_url is None and observed.preview.installation_id is None
    operation = next(op for op in observed.operations if op.operation_id == str(body.operation_id))
    assert operation.state == "succeeded" and not operation.unknown
    assert calls == ["prepare", "status", "describe"] and len(reads) == int(has_core_grant)
    replay = asyncio.run(workspaces.create(settings, factory, project_id, body))
    assert replay.model_dump() == observed.model_dump()
    assert calls == ["prepare", "status", "describe"] and len(reads) == int(has_core_grant)


@pytest.mark.parametrize("missing", ["sdk_ready", "exact_source", "core_prepare_ack"])
def test_unknown_create_keeps_admission_closed_without_complete_owned_evidence(
    managed, monkeypatch, missing
):
    settings, factory, _, _ = managed

    async def lose_prepare(cfg, selected):
        raise ConsoleError("workspace_operation_unknown", 409)

    monkeypatch.setattr(environment, "prepare", lose_prepare)
    failed, body = create(managed)
    calls = []
    if missing == "core_prepare_ack":
        with factory.begin() as db:
            db.get(WorkspaceOperation, str(body.operation_id)).receipt = {
                "core": {"stage": "/prepare", "acknowledged": False}
            }

    def helper(cfg, selected, action):
        calls.append(action)
        if action == "status":
            return {"state": "unknown" if missing == "sdk_ready" else "ready"}
        if action == "describe" and missing == "sdk_ready":
            raise ConsoleError("workspace_operation_unknown", 409)
        assert action == "describe" and missing == "exact_source"
        return {
            "key": "owned-disposable-executor",
            "source_root": str(settings.workspace),
            "exec_server_url": "ws://127.0.0.1:19999",
            "auth_bearer_token": "disposable-executor-credential-only",
        }

    monkeypatch.setattr(environment, "_helper", helper)
    monkeypatch.setattr(environment, "environment_for", NATIVE_ENVIRONMENT_FOR)
    observed = asyncio.run(workspaces.observe(settings, factory, failed.id))
    assert observed.state == "error" and not observed.admission_open
    assert observed.version == failed.version
    assert next(
        op for op in observed.operations if op.operation_id == str(body.operation_id)
    ).unknown
    assert (
        calls
        == {
            "sdk_ready": ["status", "describe"],
            "exact_source": ["status", "describe"],
            "core_prepare_ack": [],
        }[missing]
    )
