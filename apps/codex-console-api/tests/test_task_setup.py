import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from codex_console import git, task_setup


@pytest.fixture
def setup_request(repository, tmp_path):
    (repository / ".env.example").write_text(
        "MIY_ENVIRONMENT=development\nMIY_POSTGRES_DSN=shared\nMIY_WORKER_BROKER_URL=shared\n"
    )
    (repository / ".env").write_text("DO_NOT_COPY=development-secret\n")
    (repository / "pnpm-lock.yaml").write_text("lock")
    for name in ("api", "worker", "codex-console-api"):
        path = repository / "apps" / name
        path.mkdir(parents=True)
        (path / "uv.lock").write_text("lock")
    subprocess.run(
        ["git", "-C", str(repository), "add", ".env.example", "pnpm-lock.yaml", "apps"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "setup fixture"],
        check=True,
        capture_output=True,
    )
    task_id = str(uuid4())
    root, _ = git.prepare_workspace(
        repository,
        task_id,
        base_ref="HEAD",
        worktree_root=tmp_path / "worktrees",
        branch_name="feature/setup",
    )
    config = {
        "source": str(repository),
        "worktree_root": str(tmp_path / "worktrees"),
        "runtime_root": str(tmp_path / "private-runtime"),
        "uv": "/usr/bin/uv",
        "pnpm": "/usr/bin/pnpm",
        "python": "/usr/bin/python3",
    }
    request = {
        "task_id": task_id,
        "root": str(root),
        "source": str(repository),
        "revision": git.git(repository, "rev-parse", "HEAD").decode().strip(),
    }
    return config, request


def fake_install(calls):
    def run(args, **kwargs):
        calls.append(args)
        if args[1] == "venv":
            Path(args[-1]).mkdir(parents=True)

    return run


def test_task_setup_uses_example_and_private_task_local_dependencies(setup_request, monkeypatch):
    config, request = setup_request
    calls = []
    monkeypatch.setattr(task_setup, "run", fake_install(calls))
    task_setup.prepare(config, request)
    root = Path(request["root"])
    env = (root / ".env").read_text()
    assert "development-secret" not in env and "shared" not in env
    assert request["task_id"].replace("-", "") in env
    assert (root / ".env").stat().st_mode & 0o777 == 0o600
    assert all("--frozen" in args for args in calls if args[1] == "sync")
    assert "--ignore-scripts" in calls[0] and "--frozen-lockfile" in calls[0]
    for name in ("api", "worker", "codex-console-api"):
        link = root / "apps" / name / ".venv"
        assert link.is_symlink() and link.resolve().is_relative_to(
            Path(config["runtime_root"]) / request["task_id"]
        )
    ready = json.loads(
        (Path(config["runtime_root"]) / request["task_id"] / "ready.json").read_text()
    )
    assert ready["services_started"] is False
    task_setup.prepare(config, request)
    assert (root / ".env").read_text() == env


def test_failed_install_does_not_mark_the_environment_ready(setup_request, monkeypatch):
    config, request = setup_request

    def fail(*args, **kwargs):
        raise RuntimeError("installer failure")

    monkeypatch.setattr(task_setup, "run", fail)
    with pytest.raises(RuntimeError):
        task_setup.prepare(config, request)
    assert not (Path(config["runtime_root"]) / request["task_id"] / "ready.json").exists()


@pytest.mark.parametrize("field", ["root", "source", "revision"])
def test_setup_rejects_target_or_revision_drift(setup_request, monkeypatch, field):
    config, request = setup_request
    monkeypatch.setattr(
        task_setup, "run", lambda *args, **kwargs: pytest.fail("No installer may run")
    )
    request[field] = "/tmp/other" if field != "revision" else "0" * 40
    with pytest.raises(ValueError):
        task_setup.prepare(config, request)


def test_setup_does_not_follow_an_environment_file_symlink(setup_request, monkeypatch, tmp_path):
    config, request = setup_request
    secret = tmp_path / "secret"
    secret.write_text("preserve")
    (Path(request["root"]) / ".env").symlink_to(secret)
    monkeypatch.setattr(
        task_setup, "run", lambda *args, **kwargs: pytest.fail("No installer may run")
    )
    with pytest.raises(ValueError):
        task_setup.prepare(config, request)
    assert secret.read_text() == "preserve"


def test_private_write_rejects_hardlinks_without_truncating_the_original(tmp_path):
    import os

    source = tmp_path / "original"
    source.write_text("preserve")
    link = tmp_path / "link"
    os.link(source, link)
    with pytest.raises(ValueError):
        task_setup.private_write(link, "replacement")
    assert source.read_text() == "preserve"
