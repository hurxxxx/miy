"""Native synthetic Git targets are not source or platform Git metadata."""

import hashlib
import os
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
VERIFY = runpy.run_path(str(ROOT / "scripts/verify-native-sdk-toolchain.py"))
Refused = VERIFY["ToolchainRefused"]


@pytest.fixture
def source(tmp_path):
    (tmp_path / "node_modules").mkdir()
    sdk = tmp_path / "vendor/miy-app-sdk"
    (sdk / "src").mkdir(parents=True)
    pin = {"source_inputs": {}}
    for name in (
        "package.json",
        "src/index.mjs",
        "src/file-picker.mjs",
        "src/index.test.mjs",
    ):
        raw = (ROOT / "packages/app-sdk" / name).read_bytes()
        (sdk / name).write_bytes(raw)
        pin["source_inputs"]["packages/app-sdk/" + name] = hashlib.sha256(raw).hexdigest()
    return tmp_path, pin


@pytest.mark.parametrize("present", (False, True), ids=("absent", "native-empty"))
def test_managed_source_accepts_only_absent_or_owned_empty_root_git(source, present):
    root, pin = source
    if present:
        (root / ".git").mkdir(mode=0o755)
    VERIFY["verify_source_mounts"](root, pin, managed=True)
    assert not present or list((root / ".git").iterdir()) == []


@pytest.mark.parametrize(
    "kind",
    ("file", "symlink", "nested", "nonempty", "group-writable", "world-writable", "foreign-owner"),
)
def test_managed_source_rejects_real_or_unsafe_git_targets(source, monkeypatch, kind):
    root, pin = source
    target = root / ".git"
    if kind == "file":
        target.write_text("gitdir: /outside/platform-metadata")
    elif kind == "symlink":
        outside = root.parent / "outside"
        outside.mkdir()
        target.symlink_to(outside, target_is_directory=True)
    elif kind == "nested":
        (root / "nested/.git").mkdir(parents=True)
    else:
        target.mkdir(mode=0o755)
        if kind == "nonempty":
            (target / "HEAD").write_text("ref: refs/heads/private")
        elif kind == "group-writable":
            target.chmod(0o775)
        elif kind == "world-writable":
            target.chmod(0o777)
        elif kind == "foreign-owner":
            expected = target.stat()
            original = os.fstat

            def foreign(fd):
                info = original(fd)
                if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
                    values = list(info)
                    values[4] = info.st_uid + 1
                    return os.stat_result(values)
                return info

            monkeypatch.setattr(os, "fstat", foreign)
    with pytest.raises(Refused, match="^managed_source_git_metadata_present$"):
        VERIFY["verify_source_mounts"](root, pin, managed=True)


def test_standalone_metadata_contract_and_reserved_sdk_checks_are_preserved(source):
    root, pin = source
    with pytest.raises(OSError):
        VERIFY["verify_source_mounts"](root, pin)
    (root / ".git").mkdir()
    (root / ".git/HEAD").write_text("ref: refs/heads/private")
    VERIFY["verify_source_mounts"](root, pin)
    (root / ".git/HEAD").unlink()
    (root / "node_modules/untrusted").write_text("no dependency acquisition")
    with pytest.raises(Refused, match="source_dependencies_target_not_empty"):
        VERIFY["verify_source_mounts"](root, pin, managed=True)
    (root / "node_modules/untrusted").unlink()
    (root / "vendor/miy-app-sdk/src/index.mjs").write_text("changed SDK")
    with pytest.raises(Refused, match="source_sdk_input_mismatch"):
        VERIFY["verify_source_mounts"](root, pin, managed=True)
