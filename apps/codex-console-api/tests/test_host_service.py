import importlib.util
import json
import os
import plistlib
import sqlite3
from pathlib import Path

import pytest

from codex_console.cli import load_environment


def test_service_environment_is_literal_and_shared_with_native_children(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "previous")
    monkeypatch.delenv("HOST_TEST_LITERAL", raising=False)
    environment = tmp_path / "console.env"
    environment.write_text('CODEX_HOME="/private/owned-codex"\nHOST_TEST_LITERAL="${HOME}"\n')
    environment.chmod(0o600)
    load_environment(environment)
    assert os.environ["CODEX_HOME"] == "/private/owned-codex"
    assert os.environ["HOST_TEST_LITERAL"] == "${HOME}"


@pytest.mark.parametrize("unsafe", ["public", "symlink", "hardlink"])
def test_environment_rejects_unsafe_files(tmp_path, monkeypatch, unsafe):
    monkeypatch.delenv("HOST_TEST_LITERAL", raising=False)
    path = tmp_path / "console.env"
    path.write_text("HOST_TEST_LITERAL=must-not-load\n")
    path.chmod(0o644 if unsafe == "public" else 0o600)
    target = tmp_path / "alias.env"
    if unsafe == "symlink":
        target.symlink_to(path)
    elif unsafe == "hardlink":
        target.hardlink_to(path)
    else:
        target = path
    with pytest.raises(ValueError):
        load_environment(target)
    assert "HOST_TEST_LITERAL" not in os.environ


def installer():
    path = Path(__file__).resolve().parents[3] / "scripts/install-workbench-launchd.py"
    spec = importlib.util.spec_from_file_location("workbench_launchd", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launchd_installer_preserves_environment_privacy_and_refuses_overwrite(tmp_path):
    module = installer()
    release = tmp_path / "release with spaces"
    python = release / "apps/codex-console-api/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    environment = tmp_path / "console.env"
    environment.write_text("PRIVATE_FIXTURE_VALUE=never-in-plist\n")
    environment.chmod(0o600)
    agents, logs = tmp_path / "LaunchAgents", tmp_path / "logs"
    module.install(release, environment, agents, logs, "/usr/bin:/bin")
    for role, command in module.ROLES.items():
        path = agents / f"com.miy.workbench.{role}.plist"
        assert path.stat().st_mode & 0o777 == 0o600
        assert b"never-in-plist" not in path.read_bytes()
        job = plistlib.loads(path.read_bytes())
        assert job["ProgramArguments"] == [
            str(python),
            "-m",
            "codex_console.cli",
            command,
            "--env-file",
            str(environment),
        ]
        assert job["Umask"] == 0o077
        assert "UserName" not in job
    before = {path: path.read_bytes() for path in agents.iterdir()}
    with pytest.raises(ValueError, match="Jobs already exist"):
        module.install(release, environment, agents, logs, "/other")
    assert before == {path: path.read_bytes() for path in agents.iterdir()}


@pytest.mark.parametrize("invalid", [None, "missing", "wrong-identity", "foreign-path"])
def test_offline_relocation_preserves_history_and_fails_without_partial_changes(tmp_path, invalid):
    path = Path(__file__).resolve().parents[3] / "scripts/relocate-workbench-codex.py"
    spec = importlib.util.spec_from_file_location("workbench_relocation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "codex"
    home.mkdir(mode=0o700)
    sessions = home / "sessions"
    sessions.mkdir()
    database = home / "state_5.sqlite"
    original = "/old/codex/sessions/one.jsonl"
    second = "/foreign/two.jsonl" if invalid == "foreign-path" else "/old/codex/sessions/two.jsonl"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, metadata TEXT)")
        db.executemany(
            "INSERT INTO threads VALUES (?,?,?)",
            [("one", original, "preserved"), ("two", second, "preserved")],
        )
        before = db.execute("SELECT * FROM threads ORDER BY id").fetchall()
    database.chmod(0o600)
    for ident in ("one", "two"):
        if ident == "two" and invalid == "missing":
            continue
        (sessions / (ident + ".jsonl")).write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "wrong" if ident == "two" and invalid == "wrong-identity" else ident
                    },
                }
            )
            + "\n"
        )
    history = {p: p.read_bytes() for p in sessions.iterdir()}
    backup = tmp_path / "before.sqlite3"
    if invalid:
        with pytest.raises(ValueError):
            module.relocate(home, Path("/old/codex"), backup)
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT * FROM threads ORDER BY id").fetchall() == before
        assert not backup.exists()
    else:
        assert module.relocate(home, Path("/old/codex"), backup) == 2
        with sqlite3.connect(backup) as db:
            assert db.execute("SELECT * FROM threads ORDER BY id").fetchall() == before
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT * FROM threads ORDER BY id").fetchall() == [
                ("one", str(sessions / "one.jsonl"), "preserved"),
                ("two", str(sessions / "two.jsonl"), "preserved"),
            ]
    assert history == {p: p.read_bytes() for p in sessions.iterdir()}
