"""Only disposable independent Git checkouts may receive broker-created commits."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest
from test_app_sources import app_checkout as app_checkout
from test_app_sources import command
from test_remote_environments import environment

from codex_console import app_checkpoints, remote_environments
from codex_console.errors import ConsoleError


@pytest.fixture
def app_task(settings, app_checkout):
    settings.app_execution_environments = [environment(app_checkout)]
    manifest = json.loads((app_checkout / "app.manifest.json").read_text())
    return SimpleNamespace(
        id="disposable-checkpoint-task",
        root=str(app_checkout),
        worktree_owned=False,
        template_snapshot=None,
        context={
            "source_binding": {
                "app_id": "sample-app",
                "repository_root": str(app_checkout),
                "repository": manifest["source"]["repository"],
                "directory": ".",
                **remote_environments.binding_snapshot(settings, app_checkout),
            }
        },
    )


def checkpoint(settings, app_task):
    return app_checkpoints.checkpoint(settings, app_task)


def test_checkpoint_snapshots_add_edit_delete_mode_and_is_clean_idempotent(
    settings, app_checkout, app_task
):
    previous = command(app_checkout, "rev-parse", "HEAD")
    (app_checkout / "README.md").unlink()
    script = app_checkout / "new-script.py"
    script.write_text("print('synthetic app')\n")
    script.chmod(0o755)
    manifest = json.loads((app_checkout / "app.manifest.json").read_text())
    manifest["display"]["name"] = "Edited app"
    (app_checkout / "app.manifest.json").write_text(json.dumps(manifest))
    result = checkpoint(settings, app_task)
    assert result["created"] and result["source_revision"] != previous
    assert command(app_checkout, "rev-parse", "HEAD^") == previous
    assert command(app_checkout, "show", "HEAD:new-script.py") == "print('synthetic app')"
    assert command(app_checkout, "ls-tree", "HEAD", "new-script.py").startswith("100755 blob")
    assert command(app_checkout, "status", "--porcelain") == ""
    assert (
        command(app_checkout, "log", "-1", "--format=%an <%ae>:%s")
        == "MIY Workbench <workbench@local.invalid>:MIY application checkpoint"
    )
    assert checkpoint(settings, app_task) == {
        "source_revision": result["source_revision"],
        "created": False,
    }
    assert not (app_checkout / ".git/HEAD.lock").exists()
    assert not (app_checkout / ".git/index.lock").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "secret", "oversize"])
def test_unsafe_files_are_not_committed(settings, app_checkout, app_task, tmp_path, kind):
    previous = command(app_checkout, "rev-parse", "HEAD")
    target = app_checkout / "unsafe.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text("fixture outside app")
    if kind == "symlink":
        target.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, target)
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "secret":
        (app_checkout / ".env").write_text("SYNTHETIC_ONLY=must-not-be-committed")
    else:
        target.write_bytes(b"x" * (app_checkpoints.git.MAX_BYTES + 1))
    with pytest.raises(ConsoleError):
        checkpoint(settings, app_task)
    assert command(app_checkout, "rev-parse", "HEAD") == previous


def test_staged_changes_are_preserved_and_refused(settings, app_checkout, app_task):
    (app_checkout / "README.md").write_text("User-staged content")
    command(app_checkout, "add", "README.md")
    index = (app_checkout / ".git/index").read_bytes()
    head = command(app_checkout, "rev-parse", "HEAD")
    with pytest.raises(ConsoleError, match="app_checkpoint_staged"):
        checkpoint(settings, app_task)
    assert (app_checkout / ".git/index").read_bytes() == index
    assert command(app_checkout, "rev-parse", "HEAD") == head


def test_core_missing_remote_and_detached_tasks_are_refused(settings, app_checkout, app_task):
    core = SimpleNamespace(context={})
    with pytest.raises(ConsoleError, match="app_checkpoint_source_required"):
        checkpoint(settings, core)
    environments = settings.app_execution_environments
    settings.app_execution_environments = []
    with pytest.raises(ConsoleError, match="app_executor_unavailable"):
        checkpoint(settings, app_task)
    settings.app_execution_environments = environments
    command(app_checkout, "checkout", "--detach")
    with pytest.raises(ConsoleError, match="app_checkpoint_named_branch_required"):
        checkpoint(settings, app_task)


def test_hooks_and_signing_never_execute_and_external_filters_are_refused(
    settings, app_checkout, app_task
):
    marker = app_checkout / "hook-executed"
    hooks = app_checkout / ".git/hooks"
    for name in ("pre-commit", "prepare-commit-msg", "post-commit", "reference-transaction"):
        path = hooks / name
        path.write_text("#!/bin/sh\ntouch " + str(marker) + "\n")
        path.chmod(0o755)
    command(app_checkout, "config", "commit.gpgsign", "true")
    command(app_checkout, "config", "gpg.program", str(hooks / "pre-commit"))
    (app_checkout / "README.md").write_text("safe content")
    assert checkpoint(settings, app_task)["created"]
    assert not marker.exists()
    command(app_checkout, "config", "filter.untrusted.clean", str(hooks / "pre-commit"))
    (app_checkout / ".gitattributes").write_text("* filter=untrusted\n")
    with pytest.raises(ConsoleError, match="app_source_git_policy"):
        checkpoint(settings, app_task)
    assert not marker.exists()


def test_external_git_includes_and_metadata_links_are_refused(
    settings, app_checkout, app_task, tmp_path
):
    external = tmp_path / "outside-config"
    external.write_text("[user]\nname = Outside\n")
    command(app_checkout, "config", "include.path", str(external))
    with pytest.raises(ConsoleError, match="app_checkpoint_metadata_denied"):
        checkpoint(settings, app_task)
    command(app_checkout, "config", "--unset", "include.path")
    (app_checkout / ".git/objects/info/alternates").symlink_to(external)
    with pytest.raises(ConsoleError, match="app_checkpoint_metadata_denied"):
        checkpoint(settings, app_task)


def test_head_cas_preserves_another_actor_commit_and_original_index(
    settings, app_checkout, app_task, monkeypatch
):
    before = command(app_checkout, "rev-parse", "HEAD")
    tree = command(app_checkout, "rev-parse", "HEAD^{tree}")
    competing = command(app_checkout, "commit-tree", tree, "-p", before, "-m", "Other actor")
    (app_checkout / "README.md").write_text("App editing")
    index = (app_checkout / ".git/index").read_bytes()
    original = app_checkpoints._update_head

    def race(root, *args, **kwargs):
        command(app_checkout, "update-ref", "refs/heads/main", competing, before)
        return original(root, *args, **kwargs)

    monkeypatch.setattr(app_checkpoints, "_update_head", race)
    with pytest.raises(ConsoleError, match="app_checkpoint_conflict"):
        checkpoint(settings, app_task)
    assert command(app_checkout, "rev-parse", "HEAD") == competing
    assert (app_checkout / ".git/index").read_bytes() == index


def test_files_changing_during_snapshot_leave_head_and_index_untouched(
    settings, app_checkout, app_task, monkeypatch
):
    before = command(app_checkout, "rev-parse", "HEAD")
    (app_checkout / "README.md").write_text("First content")
    original = app_checkpoints._git

    def race(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[0] == "write-tree":
            (app_checkout / "README.md").write_text("Later content")
        return result

    monkeypatch.setattr(app_checkpoints, "_git", race)
    with pytest.raises(ConsoleError, match="app_checkpoint_changed"):
        checkpoint(settings, app_task)
    assert command(app_checkout, "rev-parse", "HEAD") == before
    assert command(app_checkout, "diff", "--cached", "--name-only") == ""


def test_existing_lock_is_never_removed(settings, app_checkout, app_task):
    lock = app_checkout / ".git/index.lock"
    lock.write_text("Other actor lock")
    with pytest.raises(ConsoleError, match="app_checkpoint_busy"):
        checkpoint(settings, app_task)
    assert lock.read_text() == "Other actor lock"


def test_checkpoint_does_not_include_other_directories_of_a_scoped_task(
    settings, app_checkout, app_task
):
    scoped = app_checkout / "subapp"
    scoped.mkdir()
    (scoped / "source.py").write_text("app = True\n")
    command(app_checkout, "add", ".")
    command(app_checkout, "commit", "-m", "Scoped fixture")
    app_task.template_snapshot = {"definition": {"directory": "subapp"}}
    app_task.root = str(scoped)
    before = command(app_checkout, "rev-parse", "HEAD")
    (app_checkout / "README.md").write_text("Unrelated root edit")
    with pytest.raises(ConsoleError, match="app_checkpoint_path_denied"):
        checkpoint(settings, app_task)
    assert command(app_checkout, "rev-parse", "HEAD") == before


def test_checkpoint_limits_count_and_total_bytes(settings, app_checkout, app_task, monkeypatch):
    monkeypatch.setattr(app_checkpoints, "MAX_FILES", 2)
    (app_checkout / "third.py").write_text("app = True")
    with pytest.raises(ConsoleError, match="app_checkpoint_too_large"):
        checkpoint(settings, app_task)
    monkeypatch.setattr(app_checkpoints, "MAX_FILES", 2048)
    monkeypatch.setattr(app_checkpoints, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(ConsoleError, match="app_checkpoint_too_large"):
        checkpoint(settings, app_task)


def test_prepared_transaction_holds_head_against_branch_switching(
    settings, app_checkout, app_task, monkeypatch
):
    (app_checkout / "README.md").write_text("Snapshot")
    original = app_checkpoints._ack
    checked = []

    def observe_lock(process, expected):
        original(process, expected)
        if expected == b"start: ok\nprepare: ok\n":
            assert (app_checkout / ".git/HEAD.lock").is_file()
            with pytest.raises(subprocess.CalledProcessError):
                command(app_checkout, "symbolic-ref", "HEAD", "refs/heads/other")
            checked.append(True)

    monkeypatch.setattr(app_checkpoints, "_ack", observe_lock)
    assert checkpoint(settings, app_task)["created"]
    assert checked == [True]
    assert command(app_checkout, "symbolic-ref", "HEAD") == "refs/heads/main"
