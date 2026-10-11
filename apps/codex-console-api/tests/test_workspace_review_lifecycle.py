"""Actual reservation/persistence keeps a review intent across stop and resume."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_gitlab, workspaces
from codex_console.errors import ConsoleError
from codex_console.models import WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction


@pytest.fixture
def review_waiting(managed, monkeypatch):
    current, _ = create(managed)
    settings, factory, _, sdk_calls = managed
    review_id = str(uuid4())
    receipt = {
        "state": "reviewing",
        "source_revision": current.source_revision,
        "target_revision": current.base_revision,
        "mr_id": 7,
        "mr_url": "https://git.invalid/team/miy/-/merge_requests/7",
        "pushed": True,
    }
    reviews = []

    async def review(cfg, item, operation, persist):
        assert operation.id == review_id and item.source_revision == current.source_revision
        with factory() as db:
            assert db.get(WorkspaceOperation, review_id).state == "running"
        if reviews:
            assert operation.receipt == receipt
        reviews.append(operation.id)
        persist(receipt, "running")
        return receipt

    def no_task_runtime(_):
        raise AssertionError("This disposable workspace has no native Task")

    monkeypatch.setattr(workspace_gitlab, "integrate", review)
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=settings,
            factory=factory,
            runtime=SimpleNamespace(for_task=no_task_runtime),
        )
    )
    current = asyncio.run(
        workspaces.action(
            app,
            current.id,
            "integrate",
            WorkspaceAction(operation_id=review_id, expected_version=current.version),
        )
    )
    assert current.integration.state == "reviewing" and current.admission_open
    yield app, current, review_id, receipt, reviews, sdk_calls


def preserved_review(factory, review_id):
    with factory() as db:
        operation = db.get(WorkspaceOperation, review_id)
        return operation.state, operation.source_revision, operation.receipt, operation.updated_at


def test_actual_review_waiting_stop_resume_and_same_intent_continue_preserve_receipt(
    review_waiting,
):
    app, reviewing, review_id, receipt, reviews, sdk_calls = review_waiting
    factory = app.state.factory
    before = preserved_review(factory, review_id)
    stop_id, resume_id = str(uuid4()), str(uuid4())
    stopped = asyncio.run(
        workspaces.action(
            app,
            reviewing.id,
            "stop",
            WorkspaceAction(operation_id=stop_id, expected_version=reviewing.version),
        )
    )
    assert stopped.state == "stopped" and not stopped.admission_open
    assert stopped.version == reviewing.version + 2
    assert stopped.preview.state == "stopped"
    assert preserved_review(factory, review_id) == before
    with pytest.raises(ConsoleError, match="workspace_stopped"):
        workspaces.reserve(
            factory,
            stopped.id,
            "integrate",
            WorkspaceAction(operation_id=review_id, expected_version=stopped.version),
        )
    assert preserved_review(factory, review_id) == before
    resumed = asyncio.run(
        workspaces.action(
            app,
            stopped.id,
            "resume",
            WorkspaceAction(operation_id=resume_id, expected_version=stopped.version),
        )
    )
    assert resumed.state == "ready" and resumed.admission_open
    assert resumed.version == stopped.version + 2
    assert resumed.preview.state == "unconfigured"
    assert resumed.source_revision == reviewing.source_revision
    assert preserved_review(factory, review_id) == before
    continued = asyncio.run(
        workspaces.action(
            app,
            resumed.id,
            "integrate",
            WorkspaceAction(operation_id=review_id, expected_version=resumed.version),
        )
    )
    assert continued.state == "ready" and continued.integration.state == "reviewing"
    assert continued.source_revision == reviewing.source_revision
    assert reviews == [review_id, review_id] and sdk_calls == ["prepare", "stop", "resume"]
    with factory() as db:
        review = db.get(WorkspaceOperation, review_id)
        assert review.state == "waiting" and review.receipt == receipt
        assert db.get(WorkspaceOperation, stop_id).state == "succeeded"
        assert db.get(WorkspaceOperation, resume_id).state == "succeeded"
    assert continued.integration.merged_revision is None


@pytest.mark.parametrize("uncertain_state", ["pending", "running", "unknown"])
def test_actual_resume_does_not_bypass_an_unresolved_operation(review_waiting, uncertain_state):
    app, reviewing, review_id, _, reviews, sdk_calls = review_waiting
    factory = app.state.factory
    stopped = asyncio.run(
        workspaces.action(
            app,
            reviewing.id,
            "stop",
            WorkspaceAction(operation_id=uuid4(), expected_version=reviewing.version),
        )
    )
    unknown_id = str(uuid4())
    with factory.begin() as db:
        db.add(
            WorkspaceOperation(
                id=unknown_id,
                workspace_id=stopped.id,
                kind="refresh",
                state=uncertain_state,
                source_revision=stopped.source_revision,
                digest="disposable-uncertain-operation",
            )
        )
    before = workspaces.read(factory, stopped.id).model_dump()
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        asyncio.run(
            workspaces.action(
                app,
                stopped.id,
                "resume",
                WorkspaceAction(operation_id=uuid4(), expected_version=stopped.version),
            )
        )
    assert workspaces.read(factory, stopped.id).model_dump() == before
    assert reviews == [review_id] and sdk_calls == ["prepare", "stop"]
