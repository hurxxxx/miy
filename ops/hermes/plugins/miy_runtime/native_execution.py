"""Run-bound sandbox verification around Hermes' native tool dispatch.

The official provider classification owns command/code approval. MIY verifies
execution identity before dispatch and retains file confinement and cleanup.
"""

import json
from contextvars import ContextVar

file_write_environment = ContextVar("miy_file_write_environment", default=None)


def verified_environment(task_id, server, run_id):
    from agent.terminal_env_registry import get_provider
    from tools.terminal_tool_lifecycle import (
        cleanup_vm,
        ensure_task_env,
        get_active_env,
    )

    from . import runtime_transport
    from .sandbox import MIYSandbox, WorkspaceEnvironment

    if not task_id or runtime_transport() != (server, run_id):
        raise ValueError("Current native execution identity required")
    if type(get_provider("miy_sandbox")) is not MIYSandbox:
        raise ValueError("miy sandbox provider required")
    previous = get_active_env(task_id)
    if type(previous) is WorkspaceEnvironment and previous._closed:
        # A fresh admitted call, never a late callback from the old execution,
        # retires the dead environment via native lifecycle/cache cleanup.
        with previous._recovery_lock:
            if get_active_env(task_id) is previous:
                # A previous unconfirmed removal must succeed first.
                previous.cleanup()
                cleanup_vm(previous._task_id)
            environment = ensure_task_env(task_id)
    else:
        environment = ensure_task_env(task_id)
    if (
        type(environment) is not WorkspaceEnvironment
        or getattr(environment, "env_type", None) != "miy_sandbox"
        or getattr(environment, "_hermes_backend_name", None) != "miy_sandbox"
        or environment._server != server
        or not environment._container
        or environment._closed
    ):
        raise ValueError("Verified live miy sandbox required")
    return environment


def execute_native(tool_name, next_call, *, task_id, server, run_id):
    environment = verified_environment(task_id, server, run_id)
    token = None
    if tool_name in {"write_file", "patch"}:
        from tools.file_tools import _get_file_ops

        if _get_file_ops(task_id).env is not environment:
            raise ValueError("Native file environment does not match this execution")
        token = file_write_environment.set(environment)
    try:
        result = next_call()
        if tool_name == "execute_code":
            payload = json.loads(result) if isinstance(result, str) else result
            if isinstance(payload, dict) and (
                payload.get("status") == "timeout"
                or payload.get("kernel", {}).get("state_lost")
                and payload.get("kernel", {}).get("ended")
            ):
                # Native kernel timeout kills its Python process but may leave
                # detached grandchildren. Dispose the entire owned sandbox.
                environment.cleanup()
        return result
    finally:
        if token is not None:
            file_write_environment.reset(token)
