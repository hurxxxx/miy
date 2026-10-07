import asyncio
from types import SimpleNamespace

import pytest

from codex_console.errors import ConsoleError
from codex_console.runtime import Runtime


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
