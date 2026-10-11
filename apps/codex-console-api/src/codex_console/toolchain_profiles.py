"""Server-owned public command environments; never inherit host variables."""

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal

from . import controller_launch
from .errors import ConsoleError

NATIVE_PROFILE = "native_v1"
SDK_PROFILE = "miy-native-sdk-20261011-v3"
LEGACY_SDK_PROFILE = "miy-native-sdk-20261009-v2"
ToolchainProfile = Literal["native_v1", "miy-native-sdk-20261009-v2", "miy-native-sdk-20261011-v3"]
SDK_ROOT = "/opt/miy/" + SDK_PROFILE
SDK_PIN_SHA256 = "6e3bb8750526715fa9e5ddb2e0252f2e2e89a53762302eb300dbee81692d630f"
SDK_ARCHIVE_SHA256 = "1d4b270dd96629d4b91ba659c26e9dc9a68419683c6dcf0729b45191db23b040"
SDK_PIN = Path(__file__).resolve().parents[4] / "ops/codex-console/executor/sdk-toolchain-pin.json"
LEGACY_SDK_PIN = SDK_PIN.with_name("sdk-toolchain-v2-pin.json")
LEGACY_SDK_PIN_SHA256 = "1e174a1e831f831029d92ecc7ca1cf87d8d3a969d26efc4719874f23df4fa76b"
LEGACY_SDK_ARCHIVE_SHA256 = "a897f12e235081c1b877c2aaf9046770923e72b5028ae8a37559a69de0f67df6"
NATIVE_ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"}


def _sdk_resources(profile):
    if profile == LEGACY_SDK_PROFILE:
        return (
            LEGACY_SDK_PIN,
            LEGACY_SDK_PIN_SHA256,
            LEGACY_SDK_ARCHIVE_SHA256,
            "/opt/miy/" + LEGACY_SDK_PROFILE,
        )
    return SDK_PIN, SDK_PIN_SHA256, SDK_ARCHIVE_SHA256, SDK_ROOT


def _sdk_pin(profile=SDK_PROFILE):
    pin_path, pin_sha, archive_sha, _ = _sdk_resources(profile)
    try:
        fd = os.open(pin_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 128 * 1024:
                raise ValueError
            raw = file.read(info.st_size + 1)
        if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != pin_sha:
            raise ValueError
        pin = json.loads(raw)
        if pin["toolchain_id"] != profile or pin["bundle"]["sha256"] != archive_sha:
            raise ValueError
        return pin
    except (OSError, ValueError, KeyError, TypeError):
        raise ConsoleError("app_executor_toolchain_unavailable", 503) from None


def selected_profile(environment=None):
    profile = getattr(environment, "toolchain_profile", NATIVE_PROFILE)
    if profile not in (NATIVE_PROFILE, SDK_PROFILE, LEGACY_SDK_PROFILE):
        raise ConsoleError("app_executor_configuration", 503)
    return profile


def is_sdk_profile(environment=None):
    return selected_profile(environment) in (SDK_PROFILE, LEGACY_SDK_PROFILE)


def binding_identity(environment):
    """Native bindings retain their previous digest; SDK bindings pin content and path."""
    if selected_profile(environment) == NATIVE_PROFILE:
        return None
    profile = selected_profile(environment)
    pin = _sdk_pin(profile)
    _, pin_sha, archive_sha, root = _sdk_resources(profile)
    return {
        "id": pin["toolchain_id"],
        "pin_sha256": pin_sha,
        "archive_sha256": archive_sha,
        "root": root,
        "controller": controller_launch.binding_identity(),
    }


def command_environment(environment=None):
    if selected_profile(environment) == NATIVE_PROFILE:
        return dict(NATIVE_ENVIRONMENT)
    profile = selected_profile(environment)
    _sdk_pin(profile)
    root = _sdk_resources(profile)[3]
    return {
        "PATH": f"{root}/bin:{root}/node/bin:{root}/python/bin:/bin",
        "HOME": "/tmp/home",
        "CODEX_HOME": "/tmp/codex-home",
        "TMPDIR": "/tmp/temp",
        "SHELL": "/bin/sh",
        "LD_LIBRARY_PATH": f"/usr/lib/x86_64-linux-gnu:{root}/python/lib",
        "PYTHONPATH": f"{root}/python-packages",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_NO_INDEX": "1",
        "NPM_CONFIG_USERCONFIG": f"{root}/profile/.npmrc",
        "NPM_CONFIG_GLOBALCONFIG": "/dev/null",
        "npm_config_offline": "true",
        "npm_config_ignore_scripts": "true",
        "npm_config_manage_package_manager_versions": "false",
        "CI": "true",
    }
