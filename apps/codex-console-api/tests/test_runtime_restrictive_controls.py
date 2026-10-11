"""Original live controller may reduce authority despite SDK readiness failure."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import FakeRPC
from sqlalchemy import select
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import store, workspace_environment
from codex_console.errors import ConsoleError
from codex_console.models import Operation, PendingRequest, ResourceLease, Task


@pytest.fixture
def waiting_task(client, managed, monkeypatch):
    workspace, _ = create(managed)
    result = client.post(
        "/api/tasks",
        json={
            "title": "Synthetic restrictive control",
            "context": {
                "workspace_id": workspace.id,
                "purpose": "development",
            },
        },
    )
    assert result.status_code == 200
    task = result.json()
    runtime = client.app.state.runtime.for_task(task["id"])

    async def ignored(*_):
        pass

    rpc = FakeRPC("synthetic", Path(task["root"]), ignored, ignored)
    rpc.connected = True
    rpc.remote_environment = workspace_environment.environment_for(
        client.app.state.settings, task["context"]["source_binding"]["managed_workspace"]
    )
    runtime.rpc = rpc
    request_id = str(uuid4())
    with client.app.state.factory.begin() as db:
        current = db.get(Task, task["id"])
        current.stage, current.status, current.permissions = "implement", "waiting", "ask"
        current.thread_id, current.turn_id = str(uuid4()), str(uuid4())
        current.runtime_generation = rpc.generation
        current.current_operation_id = str(uuid4())
        db.add(
            Operation(
                id=current.current_operation_id,
                task_id=current.id,
                kind="execute",
                state="accepted",
                digest="synthetic-accepted-execution",
            )
        )
        db.add(
            PendingRequest(
                id=request_id,
                task_id=current.id,
                thread_id=current.thread_id,
                turn_id=current.turn_id,
                rpc_id=json.dumps(17),
                generation=rpc.generation,
                method="item/commandExecution/requestApproval",
                payload={"availableDecisions": ["accept", "decline", "cancel"]},
            )
        )
        store.lease(db, current.id, workspace=workspace.id, stage="implement")

    def unavailable(*_):
        raise ConsoleError("workspace_environment_unavailable", 503)

    monkeypatch.setattr(workspace_environment, "environment_for", unavailable)
    # This app-local metadata invalidates SDK readiness, but must not retarget
    # the already-owned outer linked worktree or prevent reducing authority.
    (Path(task["root"]) / ".git").mkdir(mode=0o755)
    return task["id"], request_id, runtime, rpc


def preserved(client, task_id, request_id):
    with client.app.state.factory() as db:
        task = db.get(Task, task_id)
        request = db.get(PendingRequest, request_id)
        leases = list(db.scalars(select(ResourceLease).where(ResourceLease.task_id == task_id)))
        return task.status, request.state, len(leases)


@pytest.mark.parametrize(
    "method,decision",
    [
        ("item/commandExecution/requestApproval", "decline"),
        ("item/commandExecution/requestApproval", "cancel"),
        ("item/fileChange/requestApproval", "decline"),
        ("item/permissions/requestApproval", "cancel"),
    ],
)
def test_existing_native_negative_request_survives_readiness_failure_and_retains_lease(
    client, waiting_task, method, decision
):
    task_id, request_id, _, rpc = waiting_task
    with client.app.state.factory.begin() as db:
        db.get(PendingRequest, request_id).method = method
    response = client.post(
        f"/api/tasks/{task_id}/requests/{request_id}", json={"decision": decision}
    )
    assert response.status_code == 200
    assert preserved(client, task_id, request_id) == ("running", "answered", 1)
    assert len(rpc.responses) == 1 and rpc.responses[0][0] == 17
    if method == "item/permissions/requestApproval":
        assert rpc.responses[0][1]["permissions"] == {}
        assert [name for name, _ in rpc.calls] == ["turn/interrupt"]
    else:
        assert rpc.responses[0][1] == {"decision": decision}
        assert rpc.calls == []


def test_original_native_interrupt_survives_readiness_failure_without_connect_or_lease_release(
    client, waiting_task
):
    task_id, request_id, _, rpc = waiting_task
    response = client.post(f"/api/tasks/{task_id}/interrupt")
    assert response.status_code == 200
    assert [name for name, _ in rpc.calls] == ["turn/interrupt"]
    with client.app.state.factory() as db:
        task = db.get(Task, task_id)
        assert rpc.calls[0][1] == {"threadId": task.thread_id, "turnId": task.turn_id}
    assert preserved(client, task_id, request_id) == ("waiting", "pending", 1)
    assert rpc.responses == []


@pytest.mark.parametrize("body", [{"decision": "accept"}, {"answers": {"q": ["yes"]}}])
def test_accept_and_new_question_input_still_require_sdk_readiness(client, waiting_task, body):
    task_id, request_id, _, rpc = waiting_task
    response = client.post(f"/api/tasks/{task_id}/requests/{request_id}", json=body)
    assert response.status_code == 503
    assert response.json()["code"] == "workspace_environment_unavailable"
    assert preserved(client, task_id, request_id) == ("waiting", "pending", 1)
    assert rpc.responses == [] and rpc.calls == []


@pytest.mark.parametrize(
    "change",
    [
        "no_rpc",
        "disconnected",
        "generation",
        "unknown_generation",
        "runtime_owner",
        "fingerprint",
        "endpoint",
        "workspace",
        "source_root",
    ],
)
def test_restrictive_control_holds_changed_or_missing_original_controller_identity(
    client, waiting_task, change
):
    task_id, request_id, runtime, rpc = waiting_task
    if change == "no_rpc":
        runtime.rpc = None
    elif change == "disconnected":
        rpc.connected = False
    elif change == "runtime_owner":
        runtime.remote_task_id = str(uuid4())
    elif change == "endpoint":
        rpc.remote_environment = rpc.remote_environment.model_copy(
            update={"exec_server_url": "ws://127.0.0.1:19998"}
        )
    else:
        with client.app.state.factory.begin() as db:
            task = db.get(Task, task_id)
            if change in {"generation", "unknown_generation"}:
                task.runtime_generation = str(uuid4()) if change == "generation" else None
            else:
                context = deepcopy(task.context)
                if change == "fingerprint":
                    context["source_binding"]["remote_environment_digest"] = "0" * 64
                elif change == "workspace":
                    context["workspace_id"] = str(uuid4())
                else:
                    context["source_binding"]["executor_root"] += "/different"
                task.context = context
    for suffix, body in ((f"requests/{request_id}", {"decision": "decline"}), ("interrupt", {})):
        response = client.post(f"/api/tasks/{task_id}/{suffix}", json=body)
        assert response.status_code in (409, 503)
    assert preserved(client, task_id, request_id) == ("waiting", "pending", 1)
    assert rpc.responses == [] and rpc.calls == []


@pytest.mark.parametrize("change", ["generation", "thread", "turn", "not_pending"])
def test_negative_answer_retains_original_pending_request_currentness(client, waiting_task, change):
    task_id, request_id, _, rpc = waiting_task
    with client.app.state.factory.begin() as db:
        request = db.get(PendingRequest, request_id)
        if change == "generation":
            request.generation = str(uuid4())
        elif change == "thread":
            request.thread_id = str(uuid4())
        elif change == "turn":
            request.turn_id = str(uuid4())
        else:
            request.state = "sending"
    before = preserved(client, task_id, request_id)
    response = client.post(
        f"/api/tasks/{task_id}/requests/{request_id}", json={"decision": "decline"}
    )
    assert response.status_code == 409 and response.json()["code"] == "request_expired"
    assert preserved(client, task_id, request_id) == before
    assert rpc.responses == [] and rpc.calls == []
