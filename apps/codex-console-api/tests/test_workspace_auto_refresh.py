"""Automatic checkpoints preserve an already verified runtime without redeploying."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_environment, workspace_git, workspaces
from codex_console.models import Task, WorkbenchWorkspace, WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction


def ready_preview(managed, row, state="ready"):
    _, factory, _, _ = managed
    preview = {
        "state": state,
        "installation_id": str(uuid4()),
        "portal_url": "https://dev.invalid/apps/equipment-test",
        "source_revision": row.source_revision,
        "runtime_revision": row.source_revision,
        "failure_code": None,
    }
    with factory.begin() as db:
        current = db.get(WorkbenchWorkspace, row.id)
        current.preview = preview
        current.environment = {"state": "ready", "owned_execution": "synthetic-execution"}
        creation = db.scalar(
            select(WorkspaceOperation).where(WorkspaceOperation.workspace_id == row.id)
        )
        creation.receipt = {"core": {"generation": 7, "source_revision": row.source_revision}}
    return preview


def queue(managed, row):
    _, factory, _, _ = managed
    with factory.begin() as db:
        task = Task(title="Completed", root="/disposable", workspace_id=row.id, status="idle")
        db.add(task)
        db.flush()
        workspaces.queue_refresh(db, task, "unchanged-native-turn")
        workspaces.queue_refresh(db, task, "unchanged-native-turn")
        db.flush()
        operation = db.scalar(
            select(WorkspaceOperation).where(
                WorkspaceOperation.workspace_id == row.id,
                WorkspaceOperation.kind == "auto_refresh",
            )
        )
        return operation.id, dict(operation.receipt), task.id


def test_unchanged_completed_turn_keeps_runtime_and_receipts_without_refresh(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    preview = ready_preview(managed, row)
    operation_id, receipt, _ = queue(managed, row)
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    assert calls == ["prepare"]
    with factory() as db:
        current = db.get(WorkbenchWorkspace, row.id)
        operation = db.get(WorkspaceOperation, operation_id)
        assert current.state == "ready" and current.admission_open
        assert current.source_revision == row.source_revision
        assert current.preview == preview
        assert current.environment == {"state": "ready", "owned_execution": "synthetic-execution"}
        assert operation.state == "succeeded" and operation.failure_code is None
        assert operation.source_revision == row.source_revision
        assert operation.receipt == {**receipt, "checkpoint_pending": False}
        creation = db.scalar(
            select(WorkspaceOperation).where(
                WorkspaceOperation.workspace_id == row.id,
                WorkspaceOperation.kind == "create",
            )
        )
        assert creation.receipt == {
            "core": {"generation": 7, "source_revision": row.source_revision}
        }


@pytest.mark.parametrize("state", ["configured", "stopped", "unknown", "unconfigured", "failed"])
def test_same_revision_without_ready_runtime_still_requests_refresh(managed, state):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    ready_preview(managed, row, state)
    operation_id, _, _ = queue(managed, row)
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    assert calls == ["prepare", "refresh"]
    with factory() as db:
        assert db.get(WorkspaceOperation, operation_id).state == "blocked"
        assert db.get(WorkbenchWorkspace, row.id).preview["state"] == "failed"


def test_changed_checkpoint_refreshes_only_new_source(managed, monkeypatch):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    ready_preview(managed, row)
    with factory() as db:
        item = db.get(WorkbenchWorkspace, row.id)
        source = Path(item.worktree_root) / item.source_directory
    (source / "business.py").write_text(
        (source / "business.py").read_text() + "\n# New candidate\n"
    )
    operation_id, _, _ = queue(managed, row)
    revisions = []

    async def refresh(cfg, snapshot, selected_operation, revision):
        assert selected_operation == operation_id
        assert snapshot["preview"]["state"] == "preparing"
        revisions.append(revision)
        return {"state": "ready", "preview": {"state": "ready", "runtime_revision": revision}}

    monkeypatch.setattr(workspace_environment, "refresh", refresh)
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    current = workspaces.read(factory, row.id)
    assert revisions == [current.source_revision]
    assert current.source_revision != row.source_revision
    assert current.preview.runtime_revision == current.source_revision and current.admission_open
    assert calls == ["prepare"]


@pytest.mark.parametrize(
    "transition",
    ["stopped", "unknown", "busy", "source_changed", "operation_changed", "other_unknown"],
)
def test_checkpoint_cannot_reopen_admission_after_current_binding_changes(
    managed, monkeypatch, transition
):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    preview = ready_preview(managed, row)
    operation_id, _, task_id = queue(managed, row)
    native_checkpoint = workspace_git.checkpoint
    guarded_row = {}
    guarded_receipt = {}

    def checkpoint(cfg, item):
        saved = native_checkpoint(cfg, item)
        with factory.begin() as db:
            current = db.get(WorkbenchWorkspace, row.id)
            if transition == "stopped":
                current.state = "stopped"
                current.preview = {**preview, "state": "stopped"}
            elif transition == "unknown":
                db.get(WorkspaceOperation, operation_id).state = "unknown"
            elif transition == "busy":
                db.get(Task, task_id).status = "running"
            elif transition == "operation_changed":
                db.get(WorkspaceOperation, operation_id).source_revision = "b" * 40
            elif transition == "other_unknown":
                db.add(
                    WorkspaceOperation(
                        id=str(uuid4()),
                        workspace_id=row.id,
                        kind="integrate",
                        state="unknown",
                        source_revision=row.source_revision,
                        digest="uncertain-native-integration",
                    )
                )
            else:
                current.source_revision = "b" * 40
            current.admission_open = False
        with factory() as db:
            current = db.get(WorkbenchWorkspace, row.id)
            guarded_row.update(
                {column.name: getattr(current, column.name) for column in current.__table__.columns}
            )
            guarded_receipt.update(db.get(WorkspaceOperation, operation_id).receipt)
        return saved

    monkeypatch.setattr(workspace_git, "checkpoint", checkpoint)
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    assert calls == ["prepare"]
    with factory() as db:
        current = db.get(WorkbenchWorkspace, row.id)
        operation = db.get(WorkspaceOperation, operation_id)
        assert not current.admission_open
        assert operation.state != "succeeded"
        assert {
            column.name: getattr(current, column.name) for column in current.__table__.columns
        } == guarded_row
        assert operation.receipt == guarded_receipt
        if transition not in {"unknown", "operation_changed"}:
            assert operation.state == "blocked" and operation.failure_code is not None
        if transition == "stopped":
            assert current.state == "stopped" and current.preview["state"] == "stopped"
        elif transition == "unknown":
            assert operation.state == "unknown"
        elif transition == "source_changed":
            assert current.source_revision == "b" * 40
        elif transition == "operation_changed":
            assert operation.state == "running" and operation.source_revision == "b" * 40


def test_busy_task_leaves_queued_checkpoint_pending(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    preview = ready_preview(managed, row)
    operation_id, _, task_id = queue(managed, row)
    with factory.begin() as db:
        db.get(Task, task_id).status = "running"
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    assert calls == ["prepare"]
    with factory() as db:
        assert db.get(WorkspaceOperation, operation_id).state == "pending"
        current = db.get(WorkbenchWorkspace, row.id)
        assert current.preview == preview and not current.admission_open


def test_manual_refresh_rebuilds_even_when_runtime_revision_matches(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    ready_preview(managed, row)
    current = workspaces.read(factory, row.id)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    updated = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "refresh",
            WorkspaceAction(operation_id=uuid4(), expected_version=current.version),
        )
    )
    assert calls == ["prepare", "refresh"]
    assert updated.preview.state == "failed" and updated.admission_open
