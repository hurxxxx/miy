"""Overlapping native reads on disposable storage cannot reclaim approved work."""

import asyncio
from uuid import uuid4

import pytest
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_gitlab, workspaces
from codex_console.models import WorkbenchWorkspace, WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction


def saved(factory, workspace_id, operation_id):
    with factory() as db:
        row = db.get(WorkbenchWorkspace, workspace_id)
        operation = db.get(WorkspaceOperation, operation_id)
        return (
            {column.name: getattr(row, column.name) for column in row.__table__.columns},
            {
                column.name: getattr(operation, column.name)
                for column in operation.__table__.columns
            },
        )


@pytest.mark.parametrize("continued_state", ["running", "succeeded", "unknown"])
def test_late_observation_cannot_overwrite_resumed_or_completed_operation(
    managed, monkeypatch, continued_state
):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    operation_id = str(uuid4())
    initial_receipt = {"state": "reviewing", "mr_id": 7, "native_attempt": 1}
    observed_receipt = {
        **initial_receipt,
        "mr_url": "https://git.invalid/team/miy/-/merge_requests/7",
        "source_revision": row.source_revision,
    }
    with factory.begin() as db:
        workspace = db.get(WorkbenchWorkspace, row.id)
        workspace.admission_open = False
        workspace.integration = initial_receipt
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="integrate",
                state="unknown",
                source_revision=row.source_revision,
                digest="synthetic-approved-integration",
                receipt=initial_receipt,
            )
        )

    async def scenario():
        old_read_pending, release_old_read = asyncio.Event(), asyncio.Event()
        read_count = 0

        async def remote_observe(cfg, item, operation):
            nonlocal read_count
            assert operation.id == operation_id and operation.receipt == initial_receipt
            read_count += 1
            if read_count == 1:
                old_read_pending.set()
                await release_old_read.wait()
            return observed_receipt

        monkeypatch.setattr(workspace_gitlab, "observe", remote_observe)
        old_read = asyncio.create_task(workspaces.observe(settings, factory, row.id))
        await old_read_pending.wait()
        try:
            # The current unknown observation still works: it records exact evidence
            # as waiting and permits the owner's explicit same-operation continuation.
            current = await workspaces.observe(settings, factory, row.id)
            operation = next(op for op in current.operations if op.operation_id == operation_id)
            assert operation.state == "waiting" and operation.continuable
            assert not current.admission_open
            assert saved(factory, row.id, operation_id)[1]["receipt"] == observed_receipt
            _, selected, claimed = workspaces.reserve(
                factory,
                row.id,
                "integrate",
                WorkspaceAction(operation_id=operation_id, expected_version=current.version),
            )
            assert selected == operation_id and claimed
            if continued_state != "running":
                workspaces.persist(
                    factory,
                    row.id,
                    operation_id,
                    receipt={**observed_receipt, "native_attempt": 2},
                    operation_state=continued_state,
                    integration={
                        **observed_receipt,
                        "state": "succeeded" if continued_state == "succeeded" else "merged",
                        "merged_revision": "b" * 40,
                    },
                    admission_open=False,
                )
            before = saved(factory, row.id, operation_id)
            release_old_read.set()
            stale_response = await old_read
            assert saved(factory, row.id, operation_id) == before
            operation = next(
                op for op in stale_response.operations if op.operation_id == operation_id
            )
            assert operation.state == continued_state and not operation.continuable
            assert stale_response.version == before[0]["version"]
            assert not stale_response.admission_open
            assert read_count == 2
        finally:
            release_old_read.set()
            await old_read

    asyncio.run(scenario())
