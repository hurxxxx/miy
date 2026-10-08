import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from codex_console import remote_environments
from codex_console.errors import ConsoleError
from codex_console.models import Task
from codex_console.runtime import Runtime
from conftest import FakeRPC, complete, send_message
from test_app_sources import app_checkout as app_checkout
from test_app_sources import bind, launch


@pytest.mark.parametrize(
    "context",
    [
        {"app_execution_boundary": "planning_only"},
        {"project_id": "historical", "reuse_decision": "new"},
    ],
)
def test_unbound_app_plan_does_not_gain_host_write_authority(context):
    runtime = Runtime(None, None)
    task = SimpleNamespace(context=context)
    runtime.require_stage(task, "plan")
    with pytest.raises(ConsoleError, match="app_source_planning_only"):
        runtime.require_stage(task, "implement")


def test_native_runtime_ownership_distinguishes_core_and_each_app_task():
    core = Runtime(None, None)
    first = Runtime(None, None, remote_task_id="app-one")
    second = Runtime(None, None, remote_task_id="app-two")
    host_task = SimpleNamespace(id="core", context=None)
    first_task = SimpleNamespace(id="app-one", context={"source_binding": {"version": 1}})
    second_task = SimpleNamespace(id="app-two", context={"source_binding": {"version": 1}})
    assert core.owns(host_task) and not core.owns(first_task)
    assert first.owns(first_task) and not first.owns(host_task) and not first.owns(second_task)
    assert second.owns(second_task) and not second.owns(first_task)


def test_child_shutdown_failure_does_not_keep_siblings_or_core_transport_alive():
    closed = []

    async def failing():
        closed.append("failing-child")
        raise RuntimeError("synthetic durable failure")

    async def sibling():
        closed.append("sibling")

    async def transport():
        closed.append("core-rpc")

    async def disconnected():
        closed.append("core-state")

    root = Runtime(None, None)
    root.app_runtimes = {
        "first": SimpleNamespace(close=failing),
        "second": SimpleNamespace(close=sibling),
    }
    root.rpc = SimpleNamespace(close=transport)
    root.on_disconnect = disconnected
    with pytest.raises(RuntimeError, match="synthetic durable failure"):
        asyncio.run(root.close())
    assert closed == ["failing-child", "sibling", "core-rpc", "core-state"]


def test_remote_attachments_are_rejected_before_any_host_or_executor_access():
    runtime = Runtime(None, None, remote_task_id="app-one")
    with pytest.raises(ConsoleError, match="app_executor_attachments_unsupported"):
        asyncio.run(
            runtime.submit(
                "app-one", "request", "inspect", "plan", attachment_ids=["selected-attachment"]
            )
        )


@pytest.fixture
def native_task(client, app_checkout):
    # Keep the existing secured Task/source/SQLite lifecycle. Only public native
    # RPC replies are synthetic; actual startup confinement has separate tests.
    threads = {}
    fallback_roots = {}

    class NativeRPC(FakeRPC):
        def __init__(self, *args):
            super().__init__(*args)
            self.threads = threads
            self.fallback_roots = fallback_roots
            self.loaded = set()
            self.change_reply = None

        async def call(self, method, params):
            result = await super().call(method, params)
            if method in {"thread/start", "thread/resume"}:
                result = deepcopy(result)
                thread_id = result["thread"]["id"]
                if method == "thread/start":
                    self.fallback_roots[thread_id] = list(params.get("runtimeWorkspaceRoots", []))
                if method == "thread/resume" and thread_id not in self.loaded:
                    # Pinned 0.160.1 cold resume restores no sticky selection
                    # with this app-server's disabled default environment.
                    result["thread"]["environments"] = []
                self.loaded.add(thread_id)
                # The pinned response projects the primary selected environment,
                # not the request or separately retained fallback-root metadata.
                selected = result["thread"].get("environments") or []
                result["runtimeWorkspaceRoots"] = (
                    list(selected[0]["runtimeWorkspaceRoots"]) if selected else []
                )
                if self.change_reply:
                    self.change_reply(result)
            elif method == "turn/start":
                self.threads[params["threadId"]]["environments"] = params["environments"]
            return result

    client.app.state.runtime.rpc_factory = NativeRPC
    assert bind(client, app_checkout).status_code == 200
    response = launch(client)
    assert response.status_code == 200
    task = response.json()
    return task, client.app.state.runtime.for_task(task["id"])


def native_plan(client, task):
    response = send_message(client, task)
    assert response.status_code == 200
    return complete(client, response.json())


@pytest.mark.parametrize("roots_case", ["legacy-empty", "selected-empty", "compatible-root"])
def test_cold_native_resume_preserves_approved_task_and_reselects_only_remote(
    client, native_task, roots_case
):
    task, runtime = native_task
    task = native_plan(client, task)
    revision = task["revisions"][-1]["id"]
    response = client.post(
        f"/api/tasks/{task['id']}/implement",
        json={"operation_id": str(uuid4()), "revision_id": revision, "permissions": "ask"},
    )
    assert response.status_code == 200
    task = complete(client, response.json(), "Synthetic implementation completed")
    if roots_case == "legacy-empty":
        # A retained Task created before top-level roots were sent has empty
        # fallback metadata; the resume request must not masquerade as a reply.
        runtime.rpc.fallback_roots[task["thread_id"]] = []
    retained_roots = list(runtime.rpc.fallback_roots[task["thread_id"]])
    previous_generation = runtime.rpc.generation
    client.portal.call(runtime.rpc.close)
    rpc = client.portal.call(runtime.connect)
    assert rpc.generation != previous_generation
    observed_roots = []

    def observe_reply(result):
        assert result["thread"]["environments"] == []
        assert result["runtimeWorkspaceRoots"] == []
        if roots_case == "compatible-root":
            # An exact root is also within the explicitly admitted response
            # contract; do not claim this overrides the pinned empty projection.
            result["runtimeWorkspaceRoots"] = [task["root"]]
        observed_roots.append(result["runtimeWorkspaceRoots"])

    rpc.change_reply = observe_reply

    response = send_message(client, task, text="Explain the approved result")
    assert response.status_code == 200
    resumed = response.json()
    assert resumed["id"] == task["id"] and resumed["thread_id"] == task["thread_id"]
    assert resumed["revisions"] == task["revisions"]
    assert resumed["approved_revision"] == revision
    assert resumed["items"][: len(task["items"])] == task["items"]
    calls = [(method, params) for method, params in rpc.calls if method.startswith("thread/")]
    assert calls[0][0] == "thread/resume"
    assert calls[0][1]["threadId"] == task["thread_id"]
    assert calls[0][1]["runtimeWorkspaceRoots"] == [task["root"]]
    assert "environments" not in calls[0][1]
    assert rpc.fallback_roots[task["thread_id"]] == retained_roots
    assert observed_roots == ([[task["root"]]] if roots_case == "compatible-root" else [[]])
    turns = [params for method, params in rpc.calls if method == "turn/start"]
    assert len(turns) == 1
    assert turns[0]["environments"] == remote_environments.selectors(
        SimpleNamespace(root=task["root"])
    )
    assert turns[0]["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}


@pytest.mark.parametrize(
    "boundary",
    [
        "new-empty",
        "warm-empty",
        "cold-missing",
        "cold-null",
        "cold-local",
        "cold-other",
        "cold-extra",
        "cold-selector-cwd",
        "cold-selector-roots",
        "cold-cwd",
        "cold-roots",
        "cold-other-root",
        "cold-missing-roots",
        "cold-null-roots",
        "cold-thread",
        "cold-no-generation",
    ],
)
def test_native_resume_cannot_gain_an_unverified_execution_environment(
    client, native_task, boundary
):
    task, runtime = native_task
    if boundary != "new-empty":
        task = native_plan(client, task)
    if boundary.startswith("cold-"):
        client.portal.call(runtime.rpc.close)
    rpc = client.portal.call(runtime.connect)
    if boundary == "cold-no-generation":
        with client.app.state.factory.begin() as db:
            db.get(Task, task["id"]).runtime_generation = None

    def change_reply(result):
        selected = remote_environments.selectors(SimpleNamespace(root=task["root"]))
        if boundary in {"new-empty", "warm-empty"}:
            result["thread"]["environments"] = []
        elif boundary == "cold-missing":
            result["thread"].pop("environments")
        elif boundary == "cold-null":
            result["thread"]["environments"] = None
        elif boundary in {"cold-local", "cold-other"}:
            selected[0]["environmentId"] = "local" if boundary == "cold-local" else "other"
            result["thread"]["environments"] = selected
        elif boundary == "cold-extra":
            result["thread"]["environments"] = selected + deepcopy(selected)
        elif boundary in {"cold-selector-cwd", "cold-selector-roots"}:
            selected[0]["cwd" if boundary.endswith("cwd") else "runtimeWorkspaceRoots"] = (
                "/" if boundary.endswith("cwd") else ["/"]
            )
            result["thread"]["environments"] = selected
        elif boundary == "cold-cwd":
            result["cwd"] = "/"
        elif boundary == "cold-roots":
            result["runtimeWorkspaceRoots"] = [task["root"], "/"]
        elif boundary == "cold-other-root":
            result["runtimeWorkspaceRoots"] = ["/"]
        elif boundary == "cold-missing-roots":
            result.pop("runtimeWorkspaceRoots")
        elif boundary == "cold-null-roots":
            result["runtimeWorkspaceRoots"] = None
        elif boundary == "cold-thread":
            result["thread"]["id"] = "another-thread"

    rpc.change_reply = change_reply
    before = sum(method == "turn/start" for method, _ in rpc.calls)
    response = send_message(client, task, text="A retained unsent followup")
    assert response.status_code == 409
    assert response.json()["code"] == "app_executor_changed"
    assert sum(method == "turn/start" for method, _ in rpc.calls) == before
    saved = client.get(f"/api/tasks/{task['id']}").json()
    assert saved["failed_request_text"] == "A retained unsent followup"
    assert saved["thread_id"] == task["thread_id"]
