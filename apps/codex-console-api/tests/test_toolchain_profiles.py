import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from codex_console import controller_launch
from codex_console import toolchain_profiles as profiles
from codex_console.errors import ConsoleError
from codex_console.runtime import Runtime


def sdk():
    return SimpleNamespace(toolchain_profile=profiles.SDK_PROFILE)


def test_native_default_preserves_environment_and_existing_binding_without_sdk_pin(monkeypatch):
    monkeypatch.setattr(profiles, "_sdk_pin", lambda: pytest.fail("native read SDK pin"))
    assert profiles.command_environment() == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
    }
    assert profiles.binding_identity(SimpleNamespace()) is None
    changed = profiles.command_environment()
    changed["PATH"] = "synthetic"
    assert profiles.command_environment()["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_sdk_environment_uses_fixed_public_cache_and_private_empty_homes(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/synthetic-host/private")
    monkeypatch.setenv("SYNTHETIC_SECRET", "must-not-transfer")
    environment = profiles.command_environment(sdk())
    assert environment["PATH"] == (
        profiles.SDK_ROOT
        + "/bin:"
        + profiles.SDK_ROOT
        + "/node/bin:"
        + profiles.SDK_ROOT
        + "/python/bin:/bin"
    )
    assert environment["PYTHONPATH"] == profiles.SDK_ROOT + "/python-packages"
    assert environment["NPM_CONFIG_USERCONFIG"] == profiles.SDK_ROOT + "/profile/.npmrc"
    assert environment["HOME"] == "/tmp/home"
    assert environment["CODEX_HOME"] == "/tmp/codex-home"
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["npm_config_offline"] == "true"
    assert "SYNTHETIC_SECRET" not in environment
    assert "/synthetic-host" not in json.dumps(environment)
    assert profiles.binding_identity(sdk()) == {
        "id": profiles.SDK_PROFILE,
        "pin_sha256": profiles.SDK_PIN_SHA256,
        "archive_sha256": profiles.SDK_ARCHIVE_SHA256,
        "root": profiles.SDK_ROOT,
        "controller": controller_launch.binding_identity(),
    }


@pytest.mark.parametrize("kind", ["missing", "symlink", "modified", "directory", "oversized"])
def test_sdk_pin_unavailable_or_changed_refuses_without_fallback(tmp_path, monkeypatch, kind):
    candidate = tmp_path / "pin.json"
    if kind == "symlink":
        candidate.symlink_to(profiles.SDK_PIN)
    elif kind == "modified":
        candidate.write_bytes(profiles.SDK_PIN.read_bytes() + b"\n")
    elif kind == "directory":
        candidate.mkdir()
    elif kind == "oversized":
        candidate.write_bytes(b"x" * (128 * 1024 + 1))
    monkeypatch.setattr(profiles, "SDK_PIN", candidate)
    with pytest.raises(ConsoleError, match="app_executor_toolchain_unavailable"):
        profiles.command_environment(sdk())
    with pytest.raises(ConsoleError, match="app_executor_toolchain_unavailable"):
        profiles.binding_identity(sdk())


@pytest.mark.parametrize("field", ["toolchain_id", "bundle"])
def test_profile_id_and_archive_identity_are_checked_even_with_matching_source_digest(
    tmp_path, monkeypatch, field
):
    pin = json.loads(profiles.SDK_PIN.read_text())
    pin[field] = "other" if field == "toolchain_id" else {"sha256": "0" * 64}
    raw = json.dumps(pin).encode()
    candidate = tmp_path / "pin.json"
    candidate.write_bytes(raw)
    monkeypatch.setattr(profiles, "SDK_PIN", candidate)
    monkeypatch.setattr(profiles, "SDK_PIN_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ConsoleError, match="app_executor_toolchain_unavailable"):
        profiles.command_environment(sdk())


def test_unknown_server_profile_refuses():
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        profiles.command_environment(SimpleNamespace(toolchain_profile="app-supplied-env"))


def test_remote_thread_configuration_forwards_selected_profile_using_official_set(tmp_path):
    rpc = SimpleNamespace(
        remote_environment=sdk(),
        call=AsyncMock(
            return_value={"config": {"shell_environment_policy": {"set": {"OLD": "remove"}}}}
        ),
    )
    runtime = SimpleNamespace(remote_task_id="synthetic-task")
    result = asyncio.run(Runtime.configuration(runtime, rpc, tmp_path))
    assert result["shell_environment_policy.inherit"] == "none"
    assert (
        result["shell_environment_policy.set.PYTHONPATH"] == profiles.SDK_ROOT + "/python-packages"
    )
    assert result["shell_environment_policy.set.OLD"] == ""
    rpc.call.assert_awaited_once_with("config/read", {"cwd": str(tmp_path), "includeLayers": False})


def test_remote_thread_configuration_refuses_conflicting_sdk_profile_policy(tmp_path):
    rpc = SimpleNamespace(
        remote_environment=sdk(),
        call=AsyncMock(
            return_value={"config": {"shell_environment_policy": {"include_only": ["PATH"]}}}
        ),
    )
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        asyncio.run(
            Runtime.configuration(SimpleNamespace(remote_task_id="synthetic-task"), rpc, tmp_path)
        )


def test_historical_sdk_profile_cannot_select_the_new_cache():
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        profiles.command_environment(
            SimpleNamespace(toolchain_profile="miy-native-sdk-20261009-v1")
        )


def test_release_layout_uses_canonical_pin_and_refuses_missing_or_tampered_resource(
    tmp_path,
):
    release = tmp_path / "release"
    module_path = release / "apps/codex-console-api/src/codex_console/toolchain_profiles.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_bytes(Path(profiles.__file__).read_bytes())
    spec = importlib.util.spec_from_file_location(
        "codex_console.packaged_toolchain_profiles", module_path
    )
    packaged = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packaged)
    expected = release / "ops/codex-console/executor/sdk-toolchain-pin.json"
    assert packaged.SDK_PIN == expected
    with pytest.raises(ConsoleError, match="app_executor_toolchain_unavailable"):
        packaged.command_environment(sdk())
    expected.parent.mkdir(parents=True)
    expected.write_bytes(profiles.SDK_PIN.read_bytes())
    assert (
        packaged.command_environment(sdk())["PYTHONPATH"] == profiles.SDK_ROOT + "/python-packages"
    )
    expected.write_bytes(expected.read_bytes() + b"\n")
    with pytest.raises(ConsoleError, match="app_executor_toolchain_unavailable"):
        packaged.command_environment(sdk())
