"""Pinned native tools + real sandbox smoke; no inference or application data.

Run in the dev gateway as documented in docs/domains/ai/hermes.md. Only the
authenticated context/file RPC and profile configuration use synthetic data.
Native dispatch, middleware chain, approvals, code kernel and file tools run.
"""

import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, "/opt/hermes/plugins")
import hermes_constants
import miy_runtime
import model_tools
from agent.terminal_env_registry import register_provider
from hermes_cli import config, plugins
from miy_runtime.sandbox import MIYSandbox
from tools import approval
from tools.approval_context import set_current_session_key
from tools.interrupt import set_interrupt
from tools.terminal_tool_lifecycle import cleanup_vm, get_active_env

logging.disable(logging.CRITICAL)
manager = plugins.PluginManager()
manager._discovered = True
context = plugins.PluginContext(plugins.PluginManifest(name="miy_runtime"), manager)
context.register_middleware("tool_execution", miy_runtime.execute_tool)
image = sys.argv[1]
profile = "miy-" + uuid4().hex
server_name = "miy-mcp-" + hashlib.sha256(profile.encode()).hexdigest()[:20] + "-internal"
server = {"url": "http://synthetic.invalid", "headers": {"Authorization": "Bearer synthetic"}}
current = ContextVar("native_check_conversation", default="first")
snapshots = {"first": {}, "second": {}}
tasks = {key: "native-check-" + uuid4().hex for key in snapshots}
settings = {
    "mcp_servers": {server_name: server},
    "terminal": {"backend": "miy_sandbox", "cwd": "/workspace", "container_persistent": False},
    "approvals": {"unattended_mode": "deny", "mode": "manual"},
    "code_execution": {"timeout": 10},
}


def transport():
    return server, "run_" + tasks[current.get()]


def rpc(configured, run_id, method, params):
    assert configured == server and run_id == transport()[1]
    files = snapshots[current.get()]
    if method == "miy/context":
        return {"allow_native_tools": True, "sandbox": {"image": image, "no_proxy": "localhost"}}
    if method == "miy/files/list":
        return {"files": list(files.values())}
    if method == "miy/files/read":
        return files[params["id"]]
    if method == "miy/files/write":
        path = params["path"]
        files[path] = {
            "id": path, "relative_path": path,
            "sha256": hashlib.sha256(base64.b64decode(params["data"])).hexdigest(),
            "data": params["data"],
        }
        return {}
    if method == "miy/files/checkpoint":
        return {"previews": 0}
    raise AssertionError("Unexpected synthetic RPC")


def call(tool, args, conversation="first"):
    current.set(conversation)
    set_current_session_key(transport()[1])
    result = model_tools.handle_function_call(
        tool, args, task_id=tasks[conversation],
        enabled_tools=["execute_code", "terminal", "read_file", "write_file", "patch"],
    )
    return json.loads(result)


def content(path, conversation="first"):
    return base64.b64decode(snapshots[conversation][path]["data"]).decode()


def absent(container):
    return subprocess.run(
        ["docker", "inspect", container], capture_output=True, check=False,
    ).returncode != 0


with (
    tempfile.TemporaryDirectory() as home,
    patch.dict(os.environ, {
        "HERMES_HOME": str(Path(home) / profile),
        "HERMES_WRITE_SAFE_ROOT": "/workspace",
        "HERMES_SESSION_PLATFORM": "api_server",
        "TERMINAL_ENV": "miy_sandbox",
        "TERMINAL_CWD": "/workspace",
        "TERMINAL_CONTAINER_PERSISTENT": "false",
    }),
    patch.object(config, "load_config", lambda *a, **kw: settings),
    patch.object(config, "load_config_readonly", lambda *a, **kw: settings),
    patch.object(config, "read_raw_config", lambda *a, **kw: {"code_execution": settings["code_execution"]}),
    patch.object(hermes_constants, "get_hermes_home", lambda: Path(home) / profile),
    patch.object(miy_runtime, "_rpc", rpc),
    patch.object(miy_runtime, "runtime_transport", transport),
    patch.object(plugins, "get_plugin_manager", lambda: manager),
):
    register_provider(MIYSandbox())
    original_guard = approval.check_execute_code_guard
    try:
        # Official classification handles isolated code and command approval.
        # MIY admission is tested at dispatch, not by patching this native guard.
        assert original_guard("pass", "miy_sandbox")["approved"]
        assert not original_guard("pass", "local")["approved"]
        # The built-in Docker backend examines has_host_access. Custom
        # providers declare their isolation through skip_container_guards;
        # check_sandbox verifies MIY creates no host bind mounts.
        assert not original_guard("pass", "docker", has_host_access=True)["approved"]
        blocked = miy_runtime.execute_tool(
            tool_name="execute_code", args={"code": "pass"},
            next_call=lambda: (_ for _ in ()).throw(AssertionError("Unadmitted dispatch")),
            task_id=tasks["first"],
        )
        assert "Trusted Hermes run context" in json.loads(blocked)["error"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda name: call("execute_code", {"code": "print('MIY_NATIVE_CODE_OK')"}, name),
                ["first", "second"],
            ))
        assert all(row.get("status") == "success" for row in results), results
        assert all("MIY_NATIVE_CODE_OK" in row.get("output", "") for row in results), results
        first = get_active_env(tasks["first"])
        second = get_active_env(tasks["second"])
        assert first._container != second._container
        print("PASS: unattended execute_code and concurrent conversation isolation", flush=True)
        shell = call("terminal", {
            "command": "mkdir -p /workspace/disposable; rm -rf /workspace/disposable; printf MIY_OFFICIAL_GUARD_OK",
        })
        assert shell.get("exit_code") == 0 and "MIY_OFFICIAL_GUARD_OK" in shell.get("output", ""), shell
        assert approval.check_execute_code_guard is original_guard
        print("PASS: official sandbox command/code approval and unadmitted dispatch denial", flush=True)

        write = call("write_file", {"path": "/workspace/proof.txt", "content": "before\n"})
        assert content("proof.txt") == "before\n", write
        changed = call("patch", {"path": "/workspace/proof.txt", "old_string": "before", "new_string": "after"})
        assert content("proof.txt") == "after\n", changed
        added = call("patch", {"mode": "patch", "patch": "*** Begin Patch\n*** Add File: /workspace/v4a.txt\n+v4a-before\n*** End Patch"})
        assert "v4a.txt" in snapshots["first"], added
        assert content("v4a.txt").rstrip("\n") == "v4a-before", added
        moved = call("patch", {"mode": "patch", "patch": "*** Begin Patch\n*** Move File: /workspace/v4a.txt -> /workspace/v4a-moved.txt\n*** End Patch"})
        assert "v4a-moved.txt" in snapshots["first"] and content("v4a-moved.txt").rstrip("\n") == "v4a-before", moved
        # Native code RPC must retain this call's middleware and run context.
        nested = call("execute_code", {"code": "from hermes_tools import write_file\nprint(write_file(path='/workspace/rpc.txt', content='rpc-ok'))"})
        assert nested.get("status") == "success" and content("rpc.txt") == "rpc-ok", nested
        assert not snapshots["second"]
        print("PASS: native write/patch, code tool RPC and durable file binding", flush=True)

        current.set("first")
        set_current_session_key(transport()[1])
        first.execute("mkdir -p /tmp/outside; printf unchanged > /tmp/outside/target; ln -s /tmp/outside /workspace/escape; ln -s /tmp/outside/target /workspace/leaf")
        for path in ("/tmp/outside/target", "/workspace/escape/target", "/workspace/leaf", "/workspace/escape/new"):
            result = call("write_file", {"path": path, "content": "forbidden"})
            assert "error" in result or result.get("success") is False, (path, result)
        for patch_body in (
            "*** Delete File: /workspace/escape/target",
            "*** Move File: /workspace/v4a-moved.txt -> /workspace/escape/moved",
        ):
            result = call("patch", {"mode": "patch", "patch": "*** Begin Patch\n" + patch_body + "\n*** End Patch"})
            assert "error" in result or result.get("success") is False, result
        probe = first.execute("test ! -e /tmp/outside/new && test \"$(cat /tmp/outside/target)\" = unchanged")
        assert probe["returncode"] == 0, probe
        print("PASS: outside-root and parent/leaf symlink writes denied", flush=True)

        # Deadline must kill detached descendants, then a fresh native call
        # must restore previously persisted files in the same conversation.
        previous = first._container
        settings["code_execution"]["timeout"] = 2
        timed_out = call("execute_code", {"code": "import subprocess, time\nsubprocess.Popen(['sh', '-c', 'sleep 8; echo late > /workspace/late.txt'], start_new_session=True)\ntime.sleep(30)"})
        assert timed_out.get("status") == "timeout", timed_out
        assert absent(previous), "Timed-out sandbox still exists"
        settings["code_execution"]["timeout"] = 10
        fresh = call("execute_code", {"code": "print(open('/workspace/proof.txt').read())"})
        assert fresh.get("status") == "success" and "after" in fresh.get("output", ""), fresh
        assert "late.txt" not in snapshots["first"]
        print("PASS: timeout removes descendants; next call restores saved files", flush=True)

        environment = get_active_env(tasks["first"])
        previous = environment._container
        worker = []

        def cancellable():
            worker.append(threading.get_ident())
            return call("execute_code", {"code": "import subprocess, time\nsubprocess.Popen(['sh', '-c', 'sleep 8; echo late > /workspace/cancel-late.txt'], start_new_session=True)\nopen('/tmp/miy-cancel-ready', 'w').close()\ntime.sleep(60)"})

        settings["code_execution"]["timeout"] = 30
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(cancellable)
            deadline = time.monotonic() + 15
            ready = False
            while time.monotonic() < deadline and not pending.done():
                ready = subprocess.run(
                    ["docker", "exec", previous, "test", "-f", "/tmp/miy-cancel-ready"],
                    capture_output=True, timeout=3, check=False,
                ).returncode == 0
                if ready:
                    break
                time.sleep(0.1)
            assert ready, "Synthetic cancellation script did not start"
            set_interrupt(True, thread_id=worker[0], reason="synthetic cancellation check")
            try:
                stopped = pending.result(timeout=20)
            finally:
                set_interrupt(False, thread_id=worker[0])
        assert stopped.get("status") in {"interrupted", "error"}, stopped
        assert absent(previous), "Cancelled sandbox still exists"
        assert "cancel-late.txt" not in snapshots["first"]
        other = call("execute_code", {"code": "print('other-still-works')"}, "second")
        assert other.get("status") == "success", other
        print("PASS: cancellation removes detached children and preserves the other conversation", flush=True)
    finally:
        for name, task in tasks.items():
            current.set(name)
            set_current_session_key(transport()[1])
            environment = get_active_env(task)
            if environment is not None:
                cleanup_vm(environment._task_id)
