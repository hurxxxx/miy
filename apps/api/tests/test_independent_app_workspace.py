import importlib.util
from pathlib import Path

import pytest

from miy_api.domains.independent_apps.builds import BuildFailure
from test_independent_app_builds import replace_loose_object, repo


def helper():
    path = Path(__file__).resolve().parents[3] / "scripts/prepare-independent-app-workspace.py"
    loader = importlib.util.spec_from_file_location("app_workspace", path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def test_workspace_starts_fresh_git_metadata_without_executing_source_hooks(tmp_path):
    source, revision, definition, git = repo(tmp_path)
    marker = tmp_path / "host-hook-must-not-run"
    hook = source / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\ntouch " + str(marker) + "\n")
    hook.chmod(0o755)
    destination = tmp_path / "app-development"
    result = helper().prepare(source, revision, destination)
    assert result["app_id"] == definition.app_id
    assert result["source_revision"] == revision
    assert result["development_revision"] != revision
    assert result["reverse_sync"] is False
    assert (destination / "app.manifest.json").read_bytes() == (
        source / "app.manifest.json"
    ).read_bytes()
    assert not (destination / ".git/hooks/pre-commit").exists()
    assert not marker.exists()
    assert git("rev-parse", "HEAD") == revision
    assert definition.source.repository in (destination / ".git/config").read_text()


def test_workspace_rejects_committed_credentials_and_preserves_existing_targets(tmp_path):
    source, revision, _, git = repo(tmp_path)
    destination = tmp_path / "app-development"
    destination.mkdir()
    (destination / "unrelated").write_text("retain")
    with pytest.raises(BuildFailure, match="workspace_target_denied"):
        helper().prepare(source, revision, destination)
    assert (destination / "unrelated").read_text() == "retain"
    (source / ".env").write_text("SYNTHETIC_VALUE=fixture")
    git("add", ".env")
    git("commit", "-m", "Synthetic denied source")
    target = tmp_path / "unsafe-development"
    with pytest.raises(BuildFailure, match="build_archive_unsafe"):
        helper().prepare(source, git("rev-parse", "HEAD"), target)
    assert not target.exists()
    assert not list(tmp_path.glob(".miy-app-source-*"))


def test_workspace_rejects_corrupt_source_without_publishing_or_leaving_staging(tmp_path):
    source, revision, _, git = repo(tmp_path)
    replace_loose_object(source, git("rev-parse", "HEAD:api.py"), "blob", b"value = 999\n")
    destination = tmp_path / "app-development"
    with pytest.raises(BuildFailure, match="build_source_object_invalid"):
        helper().prepare(source, revision, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".miy-app-source-*"))


def test_workspace_pins_original_source_despite_replace_refs(tmp_path):
    source, revision, _, git = repo(tmp_path)
    (source / "api.py").write_text("value = 999\n")
    git("add", "api.py")
    git("commit", "-m", "Replacement workspace fixture")
    git("replace", revision, git("rev-parse", "HEAD"))
    destination = tmp_path / "app-development"
    result = helper().prepare(source, revision, destination)
    assert result["source_revision"] == revision
    assert (destination / "api.py").read_text() == "value = 1\n"
