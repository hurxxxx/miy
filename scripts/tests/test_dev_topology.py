"""Stopped namespace restart and fail-closed opposite-mode launch boundaries."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def stopped_first_party_checkout(tmp_path):
    checkout = tmp_path / "dev"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "dev.sh", checkout / "dev.sh")
    shutil.copyfile(ROOT / "scripts/dev-topology.py", scripts / "dev-topology.py")
    shutil.copyfile(
        ROOT / "scripts/dev-worker-processes.py", scripts / "dev-worker-processes.py"
    )
    # No dotenv, database, broker, Nx, or service from the real checkout is used.
    (scripts / "dev-env.sh").write_text("# Synthetic development environment.\n")
    commands = tmp_path / "commands"
    commands.mkdir()
    for name, body in (
        ("pgrep", "exit 1\n"),
        ("lsof", "exit 1\n"),
        ("pnpm", 'printf "%s\\n" "$*" >> "$DEV_TOPOLOGY_TEST_NX_LOG"\n'),
        ("uv", 'printf "%s\\n" \'{"api_prefix":"/api/v1","official_patterns":[]}\'\n'),
    ):
        executable = commands / name
        executable.write_text("#!/bin/sh\n" + body)
        executable.chmod(0o755)
    log = tmp_path / "nx.log"
    environment = {
        # Keep the same pinned interpreter available to the real shell entry;
        # os.defpath alone omits non-system CI Python installations.
        "PATH": f"{commands}:{Path(sys.executable).parent}:{os.defpath}",
        "MIY_SKIP_DOTENV": "1",
        "MIY_ENV_PROFILE": "dev",
        "MIY_DEV_API_MIGRATION_PREFLIGHT": "0",
        "DEV_TOPOLOGY_TEST_NX_LOG": str(log),
    }
    subprocess.run(
        [
            sys.executable,
            str(scripts / "dev-topology.py"),
            "--select",
            "first-party",
            "--expect",
            "unselected",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return checkout, environment, log


def test_stopped_selected_first_party_restarts_same_native_namespace(tmp_path):
    checkout, environment, log = stopped_first_party_checkout(tmp_path)
    result = subprocess.run(
        ["bash", str(checkout / "dev.sh"), "--first-party", "--restart", "--no-infra"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    command = log.read_text()
    assert "--projects=web,api,official-suite,worker" in command
    assert "--configuration=first-party" in command
    assert (checkout / ".runtime/dev-topology").read_text() == "first-party\n"
    assert (checkout / ".runtime/dev-topology").stat().st_mode & 0o777 == 0o600
    assert "drain" not in command


def test_stopped_opposite_namespace_holds_without_live_consumer_evidence(tmp_path):
    checkout, environment, log = stopped_first_party_checkout(tmp_path)
    result = subprocess.run(
        ["bash", str(checkout / "dev.sh"), "--restart", "--no-infra"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert (
        "Namespace transition HOLD: no live native consumer drain witness"
        in result.stderr
    )
    assert not log.exists()
    assert (checkout / ".runtime/dev-topology").read_text() == "first-party\n"
