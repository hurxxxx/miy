from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "independent_app_env", ROOT / "scripts/independent-app-env.py"
)
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)
IMAGE = "registry.test/core/app@sha256:" + "a" * 64


def test_scaffold_is_portable_and_conflicting_destination_is_preserved(tmp_path):
    source = tmp_path / "new-app"
    env.scaffold(
        source, app_id="field-app", name="현업 앱", repository="https://example.test/app.git"
    )
    definition = env.manifest(source)
    assert definition.app_id == "field-app"
    assert (source / "vendor/miy-app-sdk/src/index.mjs").is_file()
    assert (source / "AGENTS.md").is_file()
    assert not (source / "AGENTS.md.template").exists()
    (source / "user-file.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        env.scaffold(
            source, app_id="other-app", name="Another", repository="https://example.test/other.git"
        )
    assert (source / "user-file.txt").read_text() == "keep"


def test_private_notes_scaffold_is_a_portable_data_profile_without_database_credentials(tmp_path):
    source = tmp_path / "notes"
    env.scaffold(
        source,
        app_id="my-notes",
        name="Private notes",
        repository="https://example.test/notes.git",
        template="private-notes",
    )
    definition = env.manifest(source)
    assert definition.runtime_profile == "web-api-postgres-v1"
    assert definition.requested_permissions == ["identity:read", "data:read", "data:write"]
    assert (
        env.container_plan(source, image=IMAGE, port=18003)["profile"] == definition.runtime_profile
    )
    business = (source / "business.py").read_text()
    assert "/_data/notes" in business
    assert "POSTGRES" not in business
    assert (source / "vendor/miy-app-sdk/src/index.mjs").is_file()
    assert (source / "src/main.jsx").is_file()
    with pytest.raises(FileExistsError):
        env.scaffold(
            source,
            app_id="overwrite",
            name="No",
            repository="https://example.test/no.git",
            template="private-notes",
        )


def test_container_plan_enforces_core_profile_without_executing_host_input(tmp_path):
    source = tmp_path / "app"
    env.scaffold(source, app_id="field-app", name="App", repository="https://example.test/app.git")
    plan = env.container_plan(source, image=IMAGE, port=18001)
    create = plan["create"]
    assert plan["state"] == "plan_only"
    assert "--internal" in plan["network_create"]
    assert "--read-only" in create and "--cap-drop=ALL" in create
    assert "no-new-privileges" in create
    assert "--publish" not in create
    assert plan["ingress"]["publish"] == "127.0.0.1:18001:8080"
    assert plan["preview_origin"] is None
    assert create[-1] == IMAGE
    assert not any(
        "docker.sock" in arg or "/.codex" in arg or arg.startswith("--env") for arg in create
    )
    assert "--mount" not in create and "--volume" not in create
    second = tmp_path / "another-worktree"
    env.scaffold(second, app_id="field-app", name="App", repository="https://example.test/app.git")
    assert (
        env.container_plan(second, image=IMAGE, port=18002)["container_name"]
        != plan["container_name"]
    )
    for image in ("registry.test/app:latest", "--privileged", "registry.test/app@sha256:no"):
        with pytest.raises(ValueError):
            env.container_plan(source, image=image, port=18001)
    path = source / "app.manifest.json"
    path.write_text(
        json.dumps(json.loads(path.read_text()) | {"initializeCommand": "touch /host-owned"})
    )
    with pytest.raises(ValueError):
        env.container_plan(source, image=IMAGE, port=18001)


def test_manifest_reader_rejects_symlinks_large_files_and_fifo_without_blocking(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "app.manifest.json"
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    path.symlink_to(target)
    with pytest.raises(ValueError):
        env.manifest(source)
    path.unlink()
    path.write_bytes(b" " * 65537)
    with pytest.raises(ValueError):
        env.manifest(source)
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(ValueError):
        env.manifest(source)
