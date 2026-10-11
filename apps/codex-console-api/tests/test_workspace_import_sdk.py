"""Pinned legacy SDK imports use the same v3 bytes for development and builds."""

import hashlib
import json
from pathlib import Path

import pytest
from test_workspace_import_modes import item as item
from test_workspace_import_modes import original_source

from codex_console import git, toolchain_profiles, workspace_git
from codex_console.errors import ConsoleError

FIXTURE = Path(__file__).with_name("fixtures") / "sdk-v2-public.json"


def legacy_files():
    value = json.loads(FIXTURE.read_bytes())
    pin = toolchain_profiles._sdk_pin(toolchain_profiles.LEGACY_SDK_PROFILE)
    assert value["toolchain_id"] == pin["toolchain_id"]
    assert value["pin_sha256"] == toolchain_profiles.LEGACY_SDK_PIN_SHA256
    result = {}
    for name, record in value["files"].items():
        raw = record["text"].encode()
        assert record["sha256"] == pin["source_inputs"]["packages/app-sdk/" + name]
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        result[name] = raw
    return result


def legacy_source(settings, tmp_path, relative, *, readme=False):
    original, source, selected = original_source(
        settings, tmp_path, relative, root_manifest=relative != "."
    )
    sdk = source / "vendor/miy-app-sdk"
    for name, value in legacy_files().items():
        if name != "README.md" or readme:
            (sdk / name).write_bytes(value)
            (sdk / name).chmod(0o600)
    git.git(original, "add", ".")
    git.git(original, "commit", "-m", "Pinned existing v2 SDK")
    return original, source, selected


@pytest.mark.parametrize("relative,readme", [(".", False), ("legacy/app", True)])
def test_pinned_v2_import_migrates_only_public_sdk_and_records_native_checkpoint(
    settings, item, tmp_path, relative, readme
):
    original, source, selected = legacy_source(settings, tmp_path, relative, readme=readme)
    original_revision = workspace_git.revision(original)
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(source).parts
    }
    verify = workspace_git.sdk_verifier()
    old_pin = toolchain_profiles._sdk_pin(toolchain_profiles.LEGACY_SDK_PROFILE)
    new_pin = toolchain_profiles._sdk_pin()
    # Native source-mount validation reproduces the exact review failure before migration.
    baseline = tmp_path / "legacy-mount"
    (baseline / "node_modules").mkdir(parents=True)
    for name, raw in legacy_files().items():
        if name != "README.md" or readme:
            target = baseline / "vendor/miy-app-sdk" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    verify.verify_source_mounts(baseline, old_pin, managed=True)
    with pytest.raises(verify.ToolchainRefused, match="source_sdk_input_mismatch"):
        verify.verify_source_mounts(baseline, new_pin, managed=True)

    workspace_git.import_source(settings, item, selected)
    app = Path(item.worktree_root) / item.source_directory
    verify.verify_source_mounts(app, new_pin, managed=True)
    for name, raw in before.items():
        if name != "app.manifest.json" and not name.startswith("vendor/miy-app-sdk/"):
            assert (app / name).read_bytes() == raw
    original_definition = json.loads((original / "app.manifest.json").read_bytes())
    imported_definition = json.loads((app / "app.manifest.json").read_bytes())
    assert {key: value for key, value in original_definition.items() if key != "source"} == {
        key: value for key, value in imported_definition.items() if key != "source"
    }
    for name, raw in legacy_files().items():
        if name != "README.md" or readme:
            assert (source / "vendor/miy-app-sdk" / name).read_bytes() == raw
            assert (
                hashlib.sha256((app / "vendor/miy-app-sdk" / name).read_bytes()).hexdigest()
                == (new_pin["source_inputs"]["packages/app-sdk/" + name])
            )
    record = (app / "SDK_IMPORT.md").read_text()
    assert old_pin["toolchain_id"] in record and new_pin["toolchain_id"] in record
    assert toolchain_profiles.LEGACY_SDK_PIN_SHA256 in record
    assert toolchain_profiles.SDK_PIN_SHA256 in record
    saved = workspace_git.checkpoint(settings, item)
    item.source_revision = saved["source_revision"]
    assert saved["created"]
    assert (
        git.git(
            Path(item.worktree_root), "show", "HEAD:" + item.source_directory + "/SDK_IMPORT.md"
        )
        == record.encode()
    )
    assert git.git(
        Path(item.worktree_root),
        "ls-tree",
        "HEAD",
        "--",
        item.source_directory + "/bin/run-local.sh",
    ).startswith(b"100755 blob ")
    verify.verify_source_mounts(app, new_pin, managed=True)
    assert (
        workspace_git.revision(original) == original_revision
        and git.status(original)["changed"] == 0
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "custom",
        "mixed",
        "extra",
        "missing",
        "existing_record",
        "files",
        "bytes",
        "single_file",
        "dependencies",
    ],
)
def test_sdk_import_refuses_custom_inventory_record_collision_and_migration_budgets(
    settings, item, tmp_path, monkeypatch, invalid
):
    original, source, selected = legacy_source(settings, tmp_path, "legacy/app", readme=True)
    sdk = source / "vendor/miy-app-sdk"
    if invalid == "custom":
        (sdk / "src/index.mjs").write_text("Custom unpinned SDK\n")
    elif invalid == "mixed":
        (sdk / "src/index.mjs").write_bytes(
            (Path(__file__).resolve().parents[3] / "packages/app-sdk/src/index.mjs").read_bytes()
        )
    elif invalid == "extra":
        (sdk / "untrusted.mjs").write_text("Additional SDK executable\n")
    elif invalid == "missing":
        (sdk / "src/index.test.mjs").unlink()
    elif invalid == "existing_record":
        (source / "SDK_IMPORT.md").write_text("Original owner record, must not be overwritten\n")
    elif invalid == "single_file":
        (source / "oversized.bin").write_bytes(b"x" * (git.MAX_BYTES + 1))
    elif invalid == "dependencies":
        (source / "node_modules").mkdir(mode=0o700)
        (source / "node_modules/foreign.mjs").write_text("Unverified dependency\n")
        git.git(original, "add", "-f", "legacy/app/node_modules/foreign.mjs")
    git.git(original, "add", ".")
    if git.status(original)["changed"]:
        git.git(original, "commit", "-m", "SDK import refusal fixture")
    original_revision = workspace_git.revision(original)
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    expected = "workspace_source_invalid"
    entries = git.git(original, "ls-tree", "-r", "-z", "HEAD", "--", "legacy/app").split(b"\0")
    if invalid == "files":
        # Root manifest plus all original source files fit; the new audit file does not.
        monkeypatch.setattr(
            workspace_git.checkpoints, "MAX_FILES", len([e for e in entries if e]) + 1
        )
        expected = "app_checkpoint_too_large"
    elif invalid == "bytes":
        total = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
        total += (original / "app.manifest.json").stat().st_size
        # Keep the input accepted and reject the new v3 files/audit record as a whole.
        monkeypatch.setattr(workspace_git.checkpoints, "MAX_TOTAL_BYTES", total + 128)
        expected = "app_checkpoint_too_large"
    elif invalid == "single_file":
        # The existing bounded native blob reader refuses before allocating the body.
        expected = "output_too_large"
    with pytest.raises(ConsoleError, match=expected):
        workspace_git.import_source(settings, item, selected)
    assert workspace_git.revision(original) == original_revision
    assert git.status(original)["changed"] == 0
    assert {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    } == before
    worktree = Path(item.worktree_root)
    assert worktree.is_dir()
    assert git.git(worktree, "symbolic-ref", "--short", "HEAD").decode().strip() == item.branch
    assert workspace_git.revision(worktree) == item.source_revision
    if invalid == "dependencies":
        # Source-mount refusal occurs after copying. Retain only this owned
        # partial snapshot for the existing prepare failure/cleanup lifecycle.
        assert (worktree / item.source_directory / "SDK_IMPORT.md").is_file()
    if invalid == "existing_record":
        assert (
            source / "SDK_IMPORT.md"
        ).read_text() == "Original owner record, must not be overwritten\n"
