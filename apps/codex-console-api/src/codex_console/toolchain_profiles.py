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
SDK_PROFILE = "miy-native-sdk-20261009-v2"
ToolchainProfile = Literal["native_v1", "miy-native-sdk-20261009-v2"]
SDK_ROOT = "/opt/miy/miy-native-sdk-20261009-v2"
SDK_PIN_SHA256 = "1e174a1e831f831029d92ecc7ca1cf87d8d3a969d26efc4719874f23df4fa76b"
SDK_ARCHIVE_SHA256 = "a897f12e235081c1b877c2aaf9046770923e72b5028ae8a37559a69de0f67df6"
SDK_PIN = Path(__file__).resolve().parents[4] / "ops/codex-console/executor/sdk-toolchain-pin.json"
NATIVE_ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"}


def _sdk_pin():
    try:
        fd = os.open(SDK_PIN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 128 * 1024:
                raise ValueError
            raw = file.read(info.st_size + 1)
        if len(raw) != info.st_size or hashlib.sha256(raw).hexdigest() != SDK_PIN_SHA256:
            raise ValueError
        pin = json.loads(raw)
        if pin["toolchain_id"] != SDK_PROFILE or pin["bundle"]["sha256"] != SDK_ARCHIVE_SHA256:
            raise ValueError
        return pin
    except (OSError, ValueError, KeyError, TypeError):
        raise ConsoleError("app_executor_toolchain_unavailable", 503) from None


def selected_profile(environment=None):
    profile = getattr(environment, "toolchain_profile", NATIVE_PROFILE)
    if profile not in (NATIVE_PROFILE, SDK_PROFILE):
        raise ConsoleError("app_executor_configuration", 503)
    return profile


def binding_identity(environment):
    """Native bindings retain their previous digest; SDK bindings pin content and path."""
    if selected_profile(environment) == NATIVE_PROFILE:
        return None
    pin = _sdk_pin()
    return {
        "id": pin["toolchain_id"],
        "pin_sha256": SDK_PIN_SHA256,
        "archive_sha256": SDK_ARCHIVE_SHA256,
        "root": SDK_ROOT,
        "controller": controller_launch.binding_identity(),
    }


def command_environment(environment=None):
    if selected_profile(environment) == NATIVE_PROFILE:
        return dict(NATIVE_ENVIRONMENT)
    _sdk_pin()
    return {
        "PATH": f"{SDK_ROOT}/bin:{SDK_ROOT}/node/bin:{SDK_ROOT}/python/bin:/bin",
        "HOME": "/tmp/home",
        "CODEX_HOME": "/tmp/codex-home",
        "TMPDIR": "/tmp/temp",
        "SHELL": "/bin/sh",
        "LD_LIBRARY_PATH": f"/usr/lib/x86_64-linux-gnu:{SDK_ROOT}/python/lib",
        "PYTHONPATH": f"{SDK_ROOT}/python-packages",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_NO_INDEX": "1",
        "NPM_CONFIG_USERCONFIG": f"{SDK_ROOT}/profile/.npmrc",
        "NPM_CONFIG_GLOBALCONFIG": "/dev/null",
        "npm_config_offline": "true",
        "npm_config_ignore_scripts": "true",
        "npm_config_manage_package_manager_versions": "false",
        "CI": "true",
    }
