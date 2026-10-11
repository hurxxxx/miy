from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from miy_api.core.settings import Settings
from miy_api.domains.agent_terminal.runtime import AgentTerminalRuntime
from miy_api.domains.agent_terminal.service import (
    AgentTerminalConfigurationError,
    build_codex_environment,
    configured_roots,
    resolve_root,
)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "postgres_dsn": "sqlite://",
        "agent_terminal_allowed_roots": {"test-project": str(tmp_path)},
        "agent_terminal_codex_bin": "/bin/sh",
        "agent_terminal_enabled": True,
    }
    values.update(overrides)
    with patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )


def _git_output(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _initialize_git_repository(root: Path) -> None:
    _git(root, "init", "--initial-branch=dev")
    _git(root, "config", "user.email", "agent-terminal@example.test")
    _git(root, "config", "user.name", "Agent Terminal Test")
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    (root / "staged.txt").write_text("before staging\n", encoding="utf-8")
    _git(root, "add", "tracked.txt", "staged.txt")
    _git(root, "commit", "-m", "initial")


def test_configured_roots_only_resolve_server_allowlist(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    roots = configured_roots(settings)

    assert roots[0].key == "test-project"
    assert roots[0].path == tmp_path.resolve()
    assert resolve_root(settings, "test-project") == roots[0]
    with pytest.raises(
        AgentTerminalConfigurationError,
        match="agent_terminal.root_not_found",
    ):
        resolve_root(settings, "unlisted-project")


def test_codex_process_environment_does_not_inherit_api_secrets() -> None:
    environment = build_codex_environment(
        {
            "HOME": "/srv/agent",
            "PATH": "/usr/bin",
            "CODEX_HOME": "/srv/agent/.codex",
            "MIY_POSTGRES_DSN": "secret-dsn",
            "THIRD_PARTY_TOKEN": "secret-key",
        }
    )

    assert environment["HOME"] == "/srv/agent"
    assert environment["CODEX_HOME"] == "/srv/agent/.codex"
    assert environment["TERM"] == "xterm-256color"
    assert "MIY_POSTGRES_DSN" not in environment
    assert "THIRD_PARTY_TOKEN" not in environment


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_runtime_keeps_tmux_session_across_api_runtime_restart(tmp_path: Path) -> None:
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        "#!/bin/sh\n"
        "printf 'ready\\n'\n"
        "while IFS= read -r line; do printf 'echo:%s\\n' \"$line\"; done\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o700)
    settings = _settings(
        tmp_path,
        agent_terminal_codex_bin=str(fake_codex),
        instance_id=f"agent-terminal-test-{uuid4().hex}",
    )
    runtime = AgentTerminalRuntime(settings, sessionmaker())
    runtime._mark_started = lambda _session_id, _pid: None  # type: ignore[method-assign]
    runtime._mark_finished = (  # type: ignore[method-assign]
        lambda _session_id, _status, _exit_code: None
    )

    async def wait_for_pane_size(
        active_runtime: AgentTerminalRuntime,
        expected: tuple[int, int],
    ) -> None:
        pane = None
        for _attempt in range(50):
            pane = await active_runtime._inspect_tmux_session("session-1")
            if pane is not None and (pane.cols, pane.rows) == expected:
                return
            await asyncio.sleep(0.02)
        assert pane is not None
        assert (pane.cols, pane.rows) == expected

    async def exercise() -> None:
        await runtime.start(
            session_id="session-1",
            owner_id="admin-1",
            root_path=tmp_path,
            cols=100,
            rows=30,
        )
        await runtime.resize("session-1", cols=140, rows=40)
        await wait_for_pane_size(runtime, (140, 40))
        queue, replay, active = runtime.subscribe("session-1")
        assert active is True
        output = bytearray(replay)
        while b"ready" not in output:
            chunk = await asyncio.wait_for(queue.get(), timeout=2)
            assert chunk is not None
            output.extend(chunk)

        await runtime.write("session-1", b"hello\n")
        while b"hello" not in output:
            chunk = await asyncio.wait_for(queue.get(), timeout=2)
            assert chunk is not None
            output.extend(chunk)

        reconnect_queue, reconnect_replay, reconnect_active = runtime.subscribe("session-1")
        assert reconnect_active is True
        assert b"ready" in reconnect_replay
        assert b"hello" in reconnect_replay
        runtime.unsubscribe("session-1", reconnect_queue)
        runtime.unsubscribe("session-1", queue)

        return_code, _output = await runtime._run_tmux(
            "set-window-option",
            "-t",
            runtime._tmux_target("session-1"),
            "window-size",
            "manual",
        )
        assert return_code == 0
        await runtime.shutdown()
        assert runtime.is_active("session-1") is False

        restarted_runtime = AgentTerminalRuntime(settings, sessionmaker())
        restarted_runtime._load_active_sessions = (  # type: ignore[method-assign]
            lambda: (("session-1", "admin-1"),)
        )
        restarted_runtime._mark_recovered = (  # type: ignore[method-assign]
            lambda _session_id, _pid: None
        )
        restarted_runtime._mark_finished = (  # type: ignore[method-assign]
            lambda _session_id, _status, _exit_code: None
        )
        await restarted_runtime.startup()
        return_code, output = await restarted_runtime._run_tmux(
            "show-window-options",
            "-v",
            "-t",
            restarted_runtime._tmux_target("session-1"),
            "window-size",
        )
        assert return_code == 0
        assert output.strip() == b"latest"
        queue, replay, active = restarted_runtime.subscribe("session-1")
        assert active is True
        output = bytearray(replay)
        await restarted_runtime.write("session-1", b"after-restart\n")
        while b"after-restart" not in output:
            chunk = await asyncio.wait_for(queue.get(), timeout=2)
            assert chunk is not None
            output.extend(chunk)

        restarted_runtime.unsubscribe("session-1", queue)
        await restarted_runtime.terminate("session-1")
        assert restarted_runtime.is_active("session-1") is False
        await restarted_runtime.shutdown()

    try:
        asyncio.run(exercise())
    finally:
        # shutdown intentionally preserves tmux sessions; even a failed assertion must
        # remove this test's unique server so subsequent runs cannot attach to it.
        subprocess.run(
            runtime._tmux_prefix("kill-server"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
