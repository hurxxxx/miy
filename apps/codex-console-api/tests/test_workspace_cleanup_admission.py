"""Cleanup admission rejects unintegrated work without closing development."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspaces
from codex_console.errors import ConsoleError
from codex_console.models import WorkbenchWorkspace, WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction


def saved_state(factory, workspace_id):
    with factory() as db:
        row = db.get(WorkbenchWorkspace, workspace_id)
        return (
            {
                column.name: getattr(row, column.name)
                for column in WorkbenchWorkspace.__table__.columns
            },
            [
                {
                    column.name: getattr(op, column.name)
                    for column in WorkspaceOperation.__table__.columns
                }
                for op in db.scalars(
                    select(WorkspaceOperation)
                    .where(WorkspaceOperation.workspace_id == workspace_id)
                    .order_by(WorkspaceOperation.id)
                )
            ],
        )


def test_rejected_cleanup_preserves_environment_and_history_then_allows_development(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    waiting_id = str(uuid4())
    with factory.begin() as db:
        db.add(
            WorkspaceOperation(
                id=waiting_id,
                workspace_id=row.id,
                kind="integrate",
                state="waiting",
                source_revision="a" * 40,
                digest="synthetic-stale-intent",
                receipt={"mr_id": 42, "source_revision": "a" * 40},
            )
        )
    before = saved_state(factory, row.id)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    with pytest.raises(ConsoleError, match="workspace_not_integrated"):
        asyncio.run(
            workspaces.action(
                app,
                row.id,
                "cleanup",
                WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
            )
        )
    assert saved_state(factory, row.id) == before
    assert calls == ["prepare"]
    item, _, claimed = workspaces.reserve(
        factory,
        row.id,
        "refresh",
        WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
    )
    assert claimed and item.state == "ready"


def test_verified_partial_cleanup_can_continue_same_intent_with_receipt_unchanged(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    operation_id = str(uuid4())
    receipt = {"cleanup_remote_attempted": True, "source_handoff_complete": True}
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.integration = {
            "state": "succeeded",
            "source_revision": row.source_revision,
            "merged_revision": "b" * 40,
            "dev_runtime_revision": "b" * 40,
        }
        saved.state = "cleanup_pending"
        saved.admission_open = False
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="cleanup",
                state="waiting",
                source_revision=row.source_revision,
                digest="synthetic-owned-cleanup",
                receipt=receipt,
            )
        )
    item, selected, claimed = workspaces.reserve(
        factory,
        row.id,
        "cleanup",
        WorkspaceAction(operation_id=operation_id, expected_version=row.version),
    )
    assert selected == operation_id and claimed and item.continuing
    assert item.state == "cleanup_pending" and not item.admission_open
    with factory() as db:
        operation = db.get(WorkspaceOperation, operation_id)
        assert operation.state == "running" and operation.receipt == receipt


def test_unknown_cleanup_stays_read_only_and_rejects_a_new_cleanup_intent(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    operation_id = str(uuid4())
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.state = "cleanup_pending"
        saved.admission_open = False
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="cleanup",
                state="unknown",
                source_revision=row.source_revision,
                digest="synthetic-unknown-cleanup",
                receipt={"cleanup_remote_attempted": True},
            )
        )
    before = saved_state(factory, row.id)
    _, selected, claimed = workspaces.reserve(
        factory,
        row.id,
        "cleanup",
        WorkspaceAction(operation_id=operation_id, expected_version=row.version),
    )
    assert selected == operation_id and not claimed
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        workspaces.reserve(
            factory,
            row.id,
            "cleanup",
            WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
        )
    assert saved_state(factory, row.id) == before
