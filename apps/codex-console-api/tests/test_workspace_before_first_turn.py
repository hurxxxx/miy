"""A failed pre-submission root projection cannot permanently block owned stop."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspaces
from codex_console.models import (
    Agent,
    Operation,
    PendingRequest,
    ResourceLease,
    Task,
    WorkbenchWorkspace,
    WorkspaceOperation,
)
from codex_console.workspace_schemas import WorkspaceAction


def failed_before_first_turn(managed):
    workspace, _ = create(managed)
    _, factory, _, _ = managed
    with factory.begin() as db:
        owner = db.get(WorkbenchWorkspace, workspace.id)
        task = Task(
            title="Pre-submission failure",
            root=str(Path(owner.worktree_root) / owner.source_directory),
            workspace_id=workspace.id,
            status="failed",
            error_code="workspace_environment_unavailable",
            thread_id=str(uuid4()),
            current_operation_id=str(uuid4()),
        )
        db.add(task)
        db.flush()
        db.add(
            Operation(
                id=task.current_operation_id,
                task_id=task.id,
                kind="message",
                state="failed",
                digest="f" * 64,
            )
        )
        db.add(Agent(thread_id=task.thread_id, task_id=task.id, status="idle", flags=[]))
        task_id, root_id = task.id, task.thread_id
    return workspace, task_id, root_id


def test_waiting_stop_reuses_original_intent_after_known_pre_first_turn_failure(managed):
    workspace, task_id, root_id = failed_before_first_turn(managed)
    settings, factory, _, calls = managed
    stop_id = str(uuid4())
    with factory.begin() as db:
        row = db.get(WorkbenchWorkspace, workspace.id)
        row.state, row.admission_open = "stopping", False
        db.add(
            WorkspaceOperation(
                id=stop_id,
                workspace_id=row.id,
                kind="stop",
                state="waiting",
                digest="s" * 64,
                source_revision=row.source_revision,
            )
        )
    before = workspaces.read(factory, workspace.id)
    assert before.operations[0].continuable

    def no_native(task_id):
        raise AssertionError("No controller connect, SDK describe, interruption or lease release")

    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=settings, factory=factory, runtime=SimpleNamespace(for_task=no_native)
        )
    )
    after = asyncio.run(
        workspaces.action(
            app,
            workspace.id,
            "stop",
            WorkspaceAction(operation_id=stop_id, expected_version=before.version),
        )
    )
    assert after.state == "stopped" and not after.admission_open
    assert after.operations[0].operation_id == stop_id
    assert after.operations[0].state == "succeeded"
    assert calls == ["prepare", "stop"]
    with factory() as db:
        task, root = db.get(Task, task_id), db.get(Agent, root_id)
        assert (task.status, task.turn_id, task.runtime_generation) == ("failed", None, None)
        assert (root.status, root.turn_id) == ("idle", None)
        assert db.get(Operation, task.current_operation_id).state == "failed"
        assert list(db.scalars(select(ResourceLease))) == []


@pytest.mark.parametrize(
    "boundary",
    (
        "ordinary-idle-task",
        "root-not-loaded",
        "root-active",
        "root-system-error",
        "task-turn",
        "root-turn",
        "runtime-generation",
        "root-flags",
        "missing-failed-operation",
        "accepted",
        "pending",
        "preparing",
        "submitting",
        "uncertain",
        "previous-accepted",
        "pending-request",
        "answering-request",
        "lease",
        "idle-child",
        "unknown-child",
        "different-root",
        "missing-root-identity",
    ),
)
def test_pre_first_turn_exception_preserves_execution_and_unknown_fences(managed, boundary):
    workspace, task_id, root_id = failed_before_first_turn(managed)
    _, factory, _, _ = managed
    with factory.begin() as db:
        task, root = db.get(Task, task_id), db.get(Agent, root_id)
        if boundary == "ordinary-idle-task":
            task.status = "idle"
        elif boundary.startswith("root-") and boundary in (
            "root-not-loaded",
            "root-active",
            "root-system-error",
        ):
            root.status = {
                "root-not-loaded": "notLoaded",
                "root-active": "active",
                "root-system-error": "systemError",
            }[boundary]
        elif boundary == "task-turn":
            task.turn_id = "native-turn"
        elif boundary == "root-turn":
            root.turn_id = "native-turn"
        elif boundary == "runtime-generation":
            task.runtime_generation = str(uuid4())
        elif boundary == "root-flags":
            root.flags = ["waitingOnApproval"]
        elif boundary == "missing-failed-operation":
            task.current_operation_id = None
        elif boundary in ("accepted", "pending", "preparing", "submitting", "uncertain"):
            db.get(Operation, task.current_operation_id).state = boundary
        elif boundary == "previous-accepted":
            db.add(
                Operation(
                    id=str(uuid4()),
                    task_id=task.id,
                    kind="message",
                    state="accepted",
                    digest="a" * 64,
                )
            )
        elif boundary in ("pending-request", "answering-request"):
            db.add(
                PendingRequest(
                    task_id=task.id,
                    thread_id=root_id,
                    turn_id="native-turn",
                    rpc_id="7",
                    generation=str(uuid4()),
                    method="item/commandExecution/requestApproval",
                    payload={},
                    state="answering" if boundary == "answering-request" else "pending",
                )
            )
        elif boundary == "lease":
            db.add(ResourceLease(task_id=task.id, resource="/disposable/app"))
        elif boundary in ("idle-child", "unknown-child"):
            db.add(
                Agent(
                    thread_id=str(uuid4()),
                    task_id=task.id,
                    parent_thread_id=root_id,
                    status="idle" if boundary == "idle-child" else "unknown",
                    flags=[],
                )
            )
        elif boundary == "different-root":
            task.thread_id = str(uuid4())
        elif boundary == "missing-root-identity":
            task.thread_id = None
    with factory() as db:
        assert workspaces.busy(db, workspace.id)
