"""Native disposable Git proves imported executables survive scoped checkpoints."""

import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_console import app_source_setup, app_sources, app_starters, git, workspace_git
from codex_console.errors import ConsoleError


@pytest.fixture
def item(settings, repository):
    identity = str(uuid4())
    root = settings.worktree_root / "managed" / identity
    root.parent.mkdir(parents=True)
    branch = "feat/wb-" + identity
    remote = "https://git.example.invalid/team/miy.git"
    git.git(repository, "remote", "add", "origin", remote)
    git.git(repository, "worktree", "add", "-b", branch, str(root), "HEAD")
    return SimpleNamespace(
        id=identity,
        app_id="equipment-test",
        repository_root=str(repository),
        repository=remote,
        worktree_root=str(root),
        common_dir=str(repository / ".git"),
        git_dir=git.git(root, "rev-parse", "--absolute-git-dir").decode().strip(),
        source_directory="personal-apps/equipment-test",
        branch=branch,
        source_revision=workspace_git.revision(root),
    )


def original_source(settings, tmp_path, relative, *, root_manifest=False):
    root = tmp_path / "original-app"
    root.mkdir(mode=0o700)
    app = root if relative == "." else root / relative
    app.mkdir(parents=True, exist_ok=True, mode=0o700)
    entries = app_starters.render(
        "basic",
        app_id="equipment-test",
        title="Equipment fixture",
        repository="https://git.example.invalid/team/original.git",
        expected_digest=app_starters.bundle()["bundle_digest"],
    )
    with app_source_setup.directory(app) as descriptor:
        app_source_setup.copy_files(descriptor, entries)
    with (app / "app.manifest.json").open() as source:
        manifest = json.load(source)
    manifest["source"]["directory"] = relative
    (app / "app.manifest.json").write_text(json.dumps(manifest))
    if root_manifest and relative != ".":
        (app / "app.manifest.json").rename(root / "app.manifest.json")
        (root / "outside-source.txt").write_text("Excluded platform fixture\n")
    (app / "bin").mkdir(mode=0o700)
    script = app / "bin/run-local.sh"
    script.write_text("#!/bin/sh\nprintf 'imported-ok\\n'\n")
    # Git records only the regular/executable distinction, not these extra bits.
    script.chmod(0o777)
    (app / "README.md").chmod(0o644)
    for args in (
        ("init", "-b", "dev"),
        ("config", "user.email", "fixture@localhost.invalid"),
        ("config", "user.name", "Import fixture"),
        ("remote", "add", "origin", manifest["source"]["repository"]),
        ("add", "."),
        ("commit", "-m", "Committed import fixture"),
    ):
        git.git(root, *args)
    settings.app_source_roots = [root]
    return root, app, {"repository_root": str(root), "directory": relative}


def test_root_manifest_declared_subtree_import_keeps_checkpoint_and_executable(
    settings, item, tmp_path
):
    original, source, selected = original_source(
        settings, tmp_path, "legacy/app", root_manifest=True
    )
    before = workspace_git.revision(original)
    source_manifest = (original / "app.manifest.json").read_bytes()
    assert (
        app_sources.read_manifest(settings, original, item.app_id)[0]["source"]["directory"]
        == "legacy/app"
    )
    workspace_git.import_source(settings, item, selected)
    app = Path(item.worktree_root) / item.source_directory
    imported = json.loads((app / "app.manifest.json").read_bytes())
    assert imported["app_id"] == item.app_id
    assert imported["source"] == {"repository": item.repository, "directory": item.source_directory}
    assert not (app / "outside-source.txt").exists()
    assert stat.S_IMODE((app / "app.manifest.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((app / "bin/run-local.sh").stat().st_mode) == 0o700
    result = workspace_git.checkpoint(settings, item)
    item.source_revision = result["source_revision"]
    assert result["created"]
    recorded = git.git(
        Path(item.worktree_root),
        "ls-tree",
        "HEAD",
        "--",
        item.source_directory + "/bin/run-local.sh",
    )
    assert recorded.startswith(b"100755 blob ")
    assert (
        git.git(
            Path(item.worktree_root), "show", "HEAD:" + item.source_directory + "/app.manifest.json"
        )
        == (app / "app.manifest.json").read_bytes()
    )
    assert (original / "app.manifest.json").read_bytes() == source_manifest
    assert not (source / "app.manifest.json").exists()
    assert workspace_git.revision(original) == before
    assert git.status(original)["changed"] == 0


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate_manifest",
        "different_nested_manifest",
        "app_id",
        "directory",
        "repository",
        "origin",
        "traversal",
        "selected_other_tree",
        "manifest_symlink",
        "manifest_gitlink",
        "manifest_size",
        "file_limit",
        "byte_limit",
    ],
)
def test_root_manifest_import_refuses_ambiguous_identity_paths_modes_and_limits(
    settings, item, tmp_path, monkeypatch, invalid
):
    original, app, selected = original_source(settings, tmp_path, "legacy/app", root_manifest=True)
    manifest = original / "app.manifest.json"
    definition = json.loads(manifest.read_bytes())
    expected = "workspace_source_invalid"
    if invalid in {"duplicate_manifest", "different_nested_manifest"}:
        if invalid == "different_nested_manifest":
            definition["display"]["name"] = "A second app declaration"
        (app / "app.manifest.json").write_text(json.dumps(definition))
    elif invalid in {"app_id", "directory", "repository"}:
        if invalid == "app_id":
            definition["app_id"] = "another-app"
        else:
            definition["source"][invalid] = (
                "different/app"
                if invalid == "directory"
                else "https://foreign.invalid/team/app.git"
            )
        manifest.write_text(json.dumps(definition))
    elif invalid == "origin":
        git.git(original, "remote", "set-url", "origin", "https://foreign.invalid/team/app.git")
    elif invalid == "traversal":
        selected["directory"] = "legacy/../app"
    elif invalid == "selected_other_tree":
        other = original / "legacy/other"
        other.mkdir()
        (other / "file.txt").write_text("Not the declared source\n")
        selected["directory"] = "legacy/other"
    elif invalid == "manifest_symlink":
        manifest.unlink()
        manifest.symlink_to("legacy/app/README.md")
        expected = "app_checkpoint_path_denied"
    elif invalid == "manifest_gitlink":
        manifest.unlink()
        git.git(original, "rm", "--cached", "app.manifest.json")
        manifest.mkdir()
        git.git(
            original,
            "update-index",
            "--add",
            "--cacheinfo",
            "160000," + workspace_git.revision(original) + ",app.manifest.json",
        )
        expected = "app_checkpoint_path_denied"
    elif invalid == "manifest_size":
        manifest.write_bytes(manifest.read_bytes() + b" " * 65537)
    elif invalid == "file_limit":
        count = len([p for p in app.rglob("*") if p.is_file()])
        monkeypatch.setattr(workspace_git.checkpoints, "MAX_FILES", count)
        expected = "app_checkpoint_too_large"
    else:
        total = sum(p.stat().st_size for p in app.rglob("*") if p.is_file())
        monkeypatch.setattr(workspace_git.checkpoints, "MAX_TOTAL_BYTES", total)
        expected = "app_checkpoint_too_large"
    if invalid != "manifest_gitlink":
        git.git(original, "add", ".")
    # Native commit is only needed when the case changed tracked source bytes.
    if git.status(original)["changed"]:
        git.git(original, "commit", "-m", "Invalid source import fixture")
    before = workspace_git.revision(original)
    with pytest.raises(ConsoleError, match=expected):
        workspace_git.import_source(settings, item, selected)
    assert not (Path(item.worktree_root) / item.source_directory).exists()
    assert workspace_git.revision(original) == before
    assert git.status(original)["changed"] == 0


@pytest.mark.parametrize("relative", [".", "legacy/app"])
def test_git_executable_import_retains_safe_modes_and_native_checkpoint(
    settings, item, tmp_path, relative
):
    original, source, selected = original_source(settings, tmp_path, relative)
    before = workspace_git.revision(original)
    workspace_git.import_source(settings, item, selected)
    app = Path(item.worktree_root) / item.source_directory
    executable, regular = app / "bin/run-local.sh", app / "README.md"
    assert stat.S_IMODE(executable.stat().st_mode) == 0o700
    assert stat.S_IMODE(regular.stat().st_mode) == 0o600
    assert stat.S_IMODE(executable.parent.stat().st_mode) == 0o700
    result = workspace_git.checkpoint(settings, item)
    assert result["created"]
    item.source_revision = result["source_revision"]
    root = Path(item.worktree_root)
    recorded = git.git(root, "ls-tree", "HEAD", "--", item.source_directory + "/bin/run-local.sh")
    assert recorded.startswith(b"100755 blob ")
    recorded = git.git(root, "ls-tree", "HEAD", "--", item.source_directory + "/README.md")
    assert recorded.startswith(b"100644 blob ")
    assert (
        subprocess.run([str(executable)], capture_output=True, check=True).stdout
        == b"imported-ok\n"
    )
    assert workspace_git.checkpoint(settings, item)["created"] is False
    assert workspace_git.revision(original) == before
    assert stat.S_IMODE((source / "bin/run-local.sh").stat().st_mode) == 0o777
    assert git.status(original)["changed"] == 0


@pytest.mark.parametrize("kind", ["symlink", "gitlink"])
def test_import_still_refuses_nonregular_git_modes(settings, item, tmp_path, kind):
    original, source, selected = original_source(settings, tmp_path, ".")
    if kind == "symlink":
        (source / "unsupported").symlink_to("README.md")
        git.git(original, "add", "unsupported")
    else:
        (source / "unsupported").mkdir()
        git.git(
            original,
            "update-index",
            "--add",
            "--cacheinfo",
            "160000," + workspace_git.revision(original) + ",unsupported",
        )
    git.git(original, "commit", "-m", "Nonregular import fixture")
    with pytest.raises(ConsoleError, match="app_checkpoint_path_denied"):
        workspace_git.import_source(settings, item, selected)
    assert not (Path(item.worktree_root) / item.source_directory).exists()
