import importlib.util
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def native(monkeypatch):
    root = Path(__file__).resolve().parents[3] / "ops/hermes/plugins/miy_runtime"
    package = ModuleType("miy_native_test")
    package.__path__ = [str(root)]
    current = ContextVar("test_native_run", default="run_first")
    server = {"profile": "first"}
    package.runtime_transport = lambda: (server, current.get())
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(
        "miy_native_test.native_execution", root / "native_execution.py"
    )
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)

    class WorkspaceEnvironment:
        env_type = "miy_sandbox"
        _hermes_backend_name = "miy_sandbox"
        _container = "isolated"
        _closed = False
        _server = server

        def __init__(self):
            self._recovery_lock = threading.Lock()
            self._task_id = "conversation"

        def cleanup(self):
            self._container = None
            self._closed = True

    class MIYSandbox:
        pass

    environment = WorkspaceEnvironment()
    state = SimpleNamespace(environment=environment, provider=MIYSandbox())
    denied = {"approved": False, "outcome": "blocked"}

    def guard(code, env_type, has_host_access=False):
        return dict(denied)

    def get_environment(task_id):
        return state.environment

    modules = {
        "tools.approval": {"check_execute_code_guard": guard},
        "agent.terminal_env_registry": {"get_provider": lambda _: state.provider},
        "tools.terminal_tool_lifecycle": {
            "ensure_task_env": get_environment,
            "get_active_env": lambda _: state.environment,
            "cleanup_vm": lambda _: pytest.fail("Unexpected cache cleanup"),
        },
        "tools.file_tools": {"_get_file_ops": lambda _: SimpleNamespace(env=state.environment)},
        "miy_native_test.sandbox": {
            "WorkspaceEnvironment": WorkspaceEnvironment,
            "MIYSandbox": MIYSandbox,
        },
    }
    tools = ModuleType("tools")
    monkeypatch.setitem(sys.modules, "tools", tools)
    for name, members in modules.items():
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)
        if name.startswith("tools."):
            setattr(tools, name.split(".")[-1], module)
    return SimpleNamespace(
        bridge=bridge,
        state=state,
        server=server,
        current=current,
        approval=tools.approval,
        original_guard=guard,
        environment=environment,
    )


def invoke(native, tool, callback, run="run_first"):
    return native.bridge.execute_native(
        tool, callback, task_id="conversation", server=native.server, run_id=run
    )


def test_native_execution_keeps_upstream_guard_and_cleans_after_timeout(native):
    guard = native.approval.check_execute_code_guard

    def dispatch():
        assert native.approval.check_execute_code_guard is native.original_guard
        assert native.bridge.file_write_environment.get() is None
        return '{"status":"success"}'

    assert json.loads(invoke(native, "execute_code", dispatch))["status"] == "success"
    assert native.approval.check_execute_code_guard is guard

    def dispatch():
        assert native.bridge.file_write_environment.get() is native.environment
        assert not native.approval.check_execute_code_guard("pass", "miy_sandbox")["approved"]
        return "saved"

    assert invoke(native, "patch", dispatch) == "saved"
    assert native.bridge.file_write_environment.get() is None

    def dispatch():
        raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError):
        invoke(native, "execute_code", dispatch)
    assert native.approval.check_execute_code_guard is guard
    result = invoke(native, "execute_code", lambda: '{"status":"timeout"}')
    assert json.loads(result)["status"] == "timeout"
    assert native.environment._container is None


@pytest.mark.parametrize("failure", ["backend", "provider", "missing", "object", "stamp", "profile", "run"])
def test_stale_or_forged_environment_cannot_dispatch(native, failure):
    if failure == "backend":
        native.environment.env_type = "local"
    elif failure == "provider":
        native.state.provider = None
    elif failure == "missing":
        native.state.environment = None
    elif failure == "object":
        native.state.environment = SimpleNamespace(_container="host")
    elif failure == "stamp":
        native.environment._hermes_backend_name = "local"
    elif failure == "profile":
        native.environment._server = {"profile": "second"}
    else:
        native.current.set("run_second")
    with pytest.raises(ValueError):
        invoke(native, "execute_code", lambda: pytest.fail("Dispatch must be blocked"))


def test_parallel_recovery_never_retires_the_replacement(native, monkeypatch):
    previous = native.environment
    previous.cleanup()
    barrier = threading.Barrier(2)
    first_lookup = threading.local()
    retired = []

    def get_active(task_id):
        if not getattr(first_lookup, "done", False):
            first_lookup.done = True
            barrier.wait(timeout=5)
            return previous
        return native.state.environment

    def cleanup(task_id):
        retired.append(native.state.environment)
        native.state.environment = None

    def create(task_id):
        if native.state.environment is None:
            native.state.environment = type(previous)()
        return native.state.environment

    terminal = sys.modules["tools.terminal_tool_lifecycle"]
    monkeypatch.setattr(terminal, "get_active_env", get_active)
    monkeypatch.setattr(terminal, "cleanup_vm", cleanup)
    monkeypatch.setattr(terminal, "ensure_task_env", create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(native, "terminal", lambda: "ok"), [1, 2]))
    assert results == ["ok", "ok"]
    assert retired == [previous]
    assert native.state.environment is not previous and not native.state.environment._closed


def test_file_boundary_is_reset_after_failed_dispatch(native):
    def dispatch():
        assert native.bridge.file_write_environment.get() is native.environment
        raise RuntimeError("synthetic file failure")

    with pytest.raises(RuntimeError):
        invoke(native, "write_file", dispatch)
    assert native.bridge.file_write_environment.get() is None


def test_native_file_environment_must_match_verified_sandbox(native, monkeypatch):
    monkeypatch.setattr(
        sys.modules["tools.file_tools"], "_get_file_ops", lambda _: SimpleNamespace(env=object())
    )
    with pytest.raises(ValueError):
        invoke(native, "patch", lambda: pytest.fail("Dispatch must be blocked"))


def test_missing_task_identity_cannot_dispatch(native):
    with pytest.raises(ValueError):
        native.bridge.execute_native(
            "execute_code", lambda: pytest.fail("Dispatch must be blocked"),
            task_id=None, server=native.server, run_id="run_first",
        )
