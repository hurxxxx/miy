from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
NETWORK_KEY = "MIY_HERMES_TERMINAL_SANDBOX_NETWORK"
VOLUME_KEY = "MIY_HERMES_TERMINAL_EGRESS_CLIENT_VOLUME"


@pytest.fixture
def sandbox(monkeypatch):
    class BaseEnvironment:
        def __init__(self, **kwargs):
            pass

    class EnvironmentConnectionError(RuntimeError):
        def __init__(self, reason, *, retry_hint=""):
            super().__init__(reason)
            self.reason, self.retry_hint = reason, retry_hint

    for name, members in {
        "agent.terminal_env_provider": {"TerminalEnvironmentProvider": object},
        "tools.environments.base": {
            "BaseEnvironment": BaseEnvironment,
            "EnvironmentConnectionError": EnvironmentConnectionError,
        },
    }.items():
        module = ModuleType(name)
        module.__dict__.update(members)
        monkeypatch.setitem(sys.modules, name, module)
    directory = ROOT / "ops/hermes/plugins/miy_runtime"
    package = ModuleType("miy_sandbox_test")
    package.__path__ = [str(directory)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(
        "miy_sandbox_test.sandbox", directory / "sandbox.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(NETWORK_KEY, "deployment-network")
    monkeypatch.setenv(VOLUME_KEY, "deployment-ca")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/docker")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.WorkspaceEnvironment, "restore_files", lambda _: None)

    def create():
        return module.WorkspaceEnvironment(
            policy={
                "image": "pinned-image",
                "no_proxy": "localhost",
                # Older APIs can still send these during a rolling update.
                "network": "database-namespace-network",
                "ca_volume": "database-namespace-ca",
            },
            server={},
            run_id="synthetic-run",
            timeout=120,
        )

    return SimpleNamespace(
        module=module, create=create, calls=calls, error=EnvironmentConnectionError
    )


def test_failed_removal_keeps_exact_container_for_retry_and_closes_execution(sandbox, monkeypatch):
    environment = sandbox.create()
    container = environment._container
    original = sandbox.module.subprocess.run
    monkeypatch.setattr(
        sandbox.module.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1),
    )
    with pytest.raises(sandbox.error, match="sandbox.cleanup_failed"):
        environment.cleanup()
    assert environment._closed and environment._container == container
    monkeypatch.setattr(sandbox.module.subprocess, "run", original)
    environment.cleanup()
    assert environment._container is None


def test_preview_uses_an_offline_container_and_preserves_outer_isolation(sandbox):
    environment = sandbox.module.WorkspaceEnvironment(
        policy={"image": "pinned-image", "no_proxy": "localhost"},
        server={},
        run_id="synthetic-run",
        timeout=30,
        preview=True,
    )
    try:
        args = next(args for args in sandbox.calls if args[1] == "run")
        assert "--network=none" in args
        assert "--cap-drop=ALL" in args and "--security-opt=no-new-privileges" in args
        assert "--read-only" in args and "--user=10000:10000" in args
        assert any(value.endswith("chromium-seccomp.json") for value in args)
        assert not any(
            "unconfined" in value or "--cap-add" in value or "--ipc=host" in value for value in args
        )
    finally:
        environment.cleanup()


def test_provider_uses_admitted_policy_and_accepts_future_factory_options(sandbox, monkeypatch):
    package = sys.modules["miy_sandbox_test"]
    monkeypatch.setattr(package, "runtime_transport", lambda: ({}, "run_synthetic"), raising=False)
    monkeypatch.setattr(
        package, "_rpc", lambda *args: {
            "allow_native_tools": True,
            "sandbox": {"image": "admitted-image", "no_proxy": "localhost"},
        }, raising=False,
    )
    environment = sandbox.module.MIYSandbox().create_environment(
        cwd="/host", timeout=120, task_id="conversation", image="untrusted-image",
        container_config={"docker_volumes": ["/host:/workspace"]}, future_option=True,
    )
    try:
        args = next(args for args in sandbox.calls if args[1] == "run")
        assert "admitted-image" in args and "untrusted-image" not in args
        assert not any("/host" in value for value in args)
        assert "--user=10000:10000" in args and "--cap-drop=ALL" in args
        assert environment._task_id == "conversation"
    finally:
        environment.cleanup()


def test_provider_cannot_create_an_environment_without_native_admission(sandbox, monkeypatch):
    package = sys.modules["miy_sandbox_test"]
    monkeypatch.setattr(package, "runtime_transport", lambda: ({}, "run_synthetic"), raising=False)
    monkeypatch.setattr(package, "_rpc", lambda *args: {"allow_native_tools": False}, raising=False)
    with pytest.raises(RuntimeError, match="cannot execute code"):
        sandbox.module.MIYSandbox().create_environment(cwd="/workspace", timeout=120)
    assert not sandbox.calls


@pytest.mark.parametrize(
    "failure,code,cleanup_fails",
    [
        (
            subprocess.CalledProcessError(
                127,
                ["docker", "private-argument"],
                stderr=b"cannot access path /private/ca.crt: no such file or directory",
            ),
            "sandbox.egress_ca_missing",
            False,
        ),
        (
            subprocess.CalledProcessError(
                125, ["docker", "private-argument"], stderr=b"private daemon detail"
            ),
            "sandbox.start_failed",
            True,
        ),
        (
            subprocess.TimeoutExpired(["docker", "private-argument"], 120),
            "sandbox.start_timeout",
            True,
        ),
        (FileNotFoundError("private docker path"), "sandbox.docker_unavailable", False),
    ],
)
def test_start_failure_is_safe_actionable_and_survives_cleanup_failure(
    sandbox, monkeypatch, failure, code, cleanup_fails
):
    def run(args, **kwargs):
        sandbox.calls.append(args)
        if args[1] == "run":
            raise failure
        if args[1] == "rm" and cleanup_fails:
            raise OSError("private cleanup detail")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(sandbox.module.subprocess, "run", run)
    with pytest.raises(sandbox.error, match=code) as error:
        sandbox.create()
    assert "private" not in str(error.value)
    assert "administrator" in error.value.retry_hint.lower()
    assert any(args[1] == "rm" for args in sandbox.calls)
