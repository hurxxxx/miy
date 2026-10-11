"""Disposable intent/Core/SDK doubles; observations never replay cleanup."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_environment as environment
from codex_console import workspaces
from codex_console.models import Task, WorkbenchWorkspace, WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction

MERGED = "d" * 40


@pytest.fixture
def completed_before_cleanup(managed, monkeypatch):
    current, _ = create(managed)
    settings, factory, _, _ = managed
    operation_id, installation_id = str(uuid4()), str(uuid4())
    receipt = {
        "state": "merged",
        "source_revision": current.source_revision,
        "merged_revision": MERGED,
        "merge_attempted": True,
        "mr_id": 7,
        "core": {
            "stage": "/complete",
            "acknowledged": True,
            "permanent": False,
            "source_revision": current.source_revision,
        },
    }
    core = {
        "id": current.id,
        "app_id": current.app_id,
        "profile_id": current.profile,
        "source_revision": current.source_revision,
        "state": "ready",
        "version": 3,
        "installation": {"id": installation_id},
        "integration_revision": MERGED,
        "integration_deployment_id": environment._id(
            {"id": current.id}, operation_id, "dev-deploy"
        ),
        "source_handoff_complete": True,
    }
    with factory.begin() as db:
        row = db.get(WorkbenchWorkspace, current.id)
        row.state, row.admission_open = "cleanup_pending", False
        row.preview = {"state": "ready", "installation_id": installation_id}
        row.integration = {
            "state": "succeeded",
            "source_revision": current.source_revision,
            "merged_revision": MERGED,
            "dev_runtime_revision": MERGED,
        }
        row.cleanup = {"state": "cleanup_pending"}
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="integrate",
                state="unknown",
                source_revision=current.source_revision,
                digest="approved-original-intent",
                receipt=receipt,
                failure_code="workspace_busy",
            )
        )
    calls, sdk = [], {"state": "ready"}

    async def request(cfg, selected, suffix, body=None, **kwargs):
        calls.append(("core", suffix, body))
        if body is not None:
            assert suffix in {"/stop", "/cleanup"}
            core["state"] = "stopped" if suffix == "/stop" else "cleaned"
        else:
            assert suffix == "/context"
        return dict(core)

    def helper(cfg, selected, action):
        calls.append(("sdk", action, None))
        if action in {"stop", "cleanup"}:
            sdk["state"] = "stopped" if action == "stop" else "cleaned"
        return dict(sdk)

    describe = environment.environment_for

    def environment_for(cfg, selected):
        calls.append(("sdk", "describe", None))
        return describe(cfg, selected)

    async def stop(cfg, selected):
        return await environment._transition(cfg, selected, "stop")

    async def remove_remote(cfg, item, record):
        calls.append(("git", "remove_remote", None))
        assert item.integration["merged_revision"] == MERGED
        record(True)

    monkeypatch.setattr(environment, "_call", request)
    monkeypatch.setattr(environment, "_helper", helper)
    monkeypatch.setattr(environment, "environment_for", environment_for)
    monkeypatch.setattr(environment, "stop", stop)
    monkeypatch.setattr(workspaces.workspace_gitlab, "remove_remote", remove_remote)
    return settings, factory, current, operation_id, receipt, core, sdk, calls


@pytest.mark.parametrize("sdk_state", ["ready", "stopped"])
def test_acknowledged_handoff_recovers_same_cleanup_only_after_explicit_continuation(
    completed_before_cleanup, sdk_state
):
    settings, factory, current, operation_id, receipt, _, sdk, calls = completed_before_cleanup
    sdk["state"] = sdk_state
    observed = asyncio.run(workspaces.observe(settings, factory, current.id))
    selected = next(op for op in observed.operations if op.operation_id == operation_id)
    assert selected.state == "waiting" and selected.continuable and not selected.unknown
    assert observed.state == "cleanup_pending" and not observed.admission_open
    assert calls == [("core", "/context", None), ("sdk", "status", None)] + (
        [("sdk", "describe", None)] if sdk_state == "ready" else []
    )
    with factory() as db:
        assert db.get(WorkspaceOperation, operation_id).receipt == receipt
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    completed = asyncio.run(
        workspaces.action(
            app,
            current.id,
            "integrate",
            WorkspaceAction(operation_id=operation_id, expected_version=observed.version),
        )
    )
    selected = next(op for op in completed.operations if op.operation_id == operation_id)
    assert selected.state == "succeeded" and completed.state == "cleaned"
    assert completed.cleanup.state == "cleaned" and not completed.admission_open
    assert not (settings.worktree_root / "managed" / current.id).exists()
    assert [
        action for owner, action, _ in calls if owner == "sdk" and action in {"stop", "cleanup"}
    ] == ["stop", "cleanup"]


@pytest.mark.parametrize(
    "missing",
    [
        "unacknowledged",
        "cleanup_dispatched",
        "source_changed",
        "merge_changed",
        "deployment_changed",
        "identity_missing",
        "sdk_unknown",
        "task_active",
        "operation_pending",
    ],
)
def test_incomplete_cleanup_preflight_evidence_keeps_original_unknown_intent(
    completed_before_cleanup, missing
):
    settings, factory, current, operation_id, receipt, core, sdk, calls = completed_before_cleanup
    if missing == "unacknowledged":
        receipt["core"]["acknowledged"] = False
    elif missing == "cleanup_dispatched":
        receipt["core"]["stage"] = "/cleanup"
    elif missing == "source_changed":
        receipt["source_revision"] = "e" * 40
    elif missing == "merge_changed":
        core["integration_revision"] = "e" * 40
    elif missing == "deployment_changed":
        core["integration_deployment_id"] = str(uuid4())
    elif missing == "identity_missing":
        core.pop("installation")
    elif missing == "sdk_unknown":
        sdk["state"] = "unknown"
    with factory.begin() as db:
        db.get(WorkspaceOperation, operation_id).receipt = receipt
        if missing == "task_active":
            db.add(
                Task(
                    title="Disposable active Task",
                    workspace_id=current.id,
                    root=str(Path(settings.worktree_root) / "managed" / current.id),
                    status="running",
                )
            )
        elif missing == "operation_pending":
            db.add(
                WorkspaceOperation(
                    id=str(uuid4()),
                    workspace_id=current.id,
                    kind="stop",
                    state="pending",
                    source_revision=current.source_revision,
                    digest="other-intent",
                )
            )
    before = workspaces.read(factory, current.id)
    observed = asyncio.run(workspaces.observe(settings, factory, current.id))
    selected = next(op for op in observed.operations if op.operation_id == operation_id)
    assert selected.unknown and not selected.continuable
    assert observed.version == before.version and not observed.admission_open
    assert all(body is None for _, _, body in calls)
    assert not any(action in {"stop", "cleanup", "remove_remote"} for _, action, _ in calls)
    with factory() as db:
        assert db.get(WorkspaceOperation, operation_id).receipt == receipt
