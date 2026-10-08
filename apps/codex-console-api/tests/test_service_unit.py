import base64
import configparser
import json
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("service", ["codex-console", "codex-console-templates"])
def test_console_service_preserves_host_privileges_for_native_yolo_turns(service):
    unit = (ROOT / f"ops/codex-console/{service}.service").read_text()
    directives = {
        line.strip()
        for line in unit.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "NoNewPrivileges=false" in directives
    assert "NoNewPrivileges=true" not in directives


EXECUTOR = ROOT / "ops/codex-console/executor"


def executor_unit(name):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string((EXECUTOR / f"{name}.example").read_text().replace("\\\n", ""))
    return parser


@pytest.mark.parametrize("name", ["miy-app-executor", "miy-app-executor-proxy"])
def test_native_executor_has_finite_non_root_supervisor_and_no_restart(name):
    unit = executor_unit(f"{name}.service")
    service = unit["Service"]
    assert service["User"] == "@EXECUTOR_UID@"
    assert service["Group"] == "@EXECUTOR_GID@"
    assert service["NoNewPrivileges"] == "yes"
    assert service["CapabilityBoundingSet"] == ""
    assert service["PrivateNetwork"] == "yes"
    assert service["ProtectSystem"] == "strict"
    assert service["ProtectHome"] == service["PrivateTmp"] == "yes"
    assert service["CPUQuota"] == "100%"
    assert int(service["MemoryMax"]) == 1024**3
    assert int(service["MemorySwapMax"]) == 0
    assert int(service["TasksMax"]) == 64
    assert int(service["RuntimeMaxSec"]) == 270
    assert int(service["TimeoutStopSec"]) == 3
    assert service["KillMode"] == "control-group"
    assert service["Restart"] == "no"
    assert service["StandardOutput"] == service["StandardError"] == "null"
    assert service["LimitCORE"] == "0"
    assert "Install" not in unit
    assert not {"EnvironmentFile", "ExecStartPre", "ExecStartPost", "ExecStopPost"} & set(service)


def test_native_enclosure_preserves_private_network_and_exact_writable_checkout():
    service = executor_unit("miy-app-executor.service")["Service"]
    args = shlex.split(service["ExecStart"])
    assert args[0] == "@VENDOR_ROOT@/codex-resources/bwrap"
    boundary = args.index("--")
    enclosure = args[1:boundary]
    assert all(
        flag in enclosure
        for flag in (
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--new-session",
            "--die-with-parent",
            "--clearenv",
        )
    )
    assert "--unshare-net" not in enclosure
    assert "--share-net" not in enclosure
    assert enclosure[enclosure.index("--cap-drop") + 1] == "ALL"
    assert enclosure[enclosure.index("--uid") + 1] == "@EXECUTOR_UID@"
    assert enclosure[enclosure.index("--gid") + 1] == "@EXECUTOR_GID@"
    binds = [enclosure[i + 1 : i + 3] for i, value in enumerate(enclosure) if value == "--bind"]
    assert binds == [["@SOURCE_ROOT@", "@SOURCE_ROOT@"]]
    readonly = [
        enclosure[i + 1 : i + 3] for i, value in enumerate(enclosure) if value == "--ro-bind"
    ]
    assert readonly == [
        ["@VENDOR_ROOT@", "@VENDOR_ROOT@"],
        ["/usr/bin/dash", "/bin/sh"],
        ["/usr/lib/x86_64-linux-gnu/libc.so.6", "/usr/lib/x86_64-linux-gnu/libc.so.6"],
        ["/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2", "/lib64/ld-linux-x86-64.so.2"],
        ["@SOURCE_ROOT@/.git", "@SOURCE_ROOT@/.git"],
    ]
    assert enclosure[enclosure.index("--size") + 1 : enclosure.index("--size") + 4] == [
        "67108864",
        "--tmpfs",
        "/tmp",
    ]
    environment = {
        enclosure[i + 1]: enclosure[i + 2]
        for i, value in enumerate(enclosure)
        if value == "--setenv"
    }
    assert environment == {
        "PATH": "/bin",
        "HOME": "/tmp/home",
        "CODEX_HOME": "/tmp/codex-home",
        "TMPDIR": "/tmp/temp",
        "SHELL": "/bin/sh",
    }
    assert enclosure[-4:] == ["--chdir", "@SOURCE_ROOT@", "--remount-ro", "/"]
    assert service["BindPaths"] == "@SOURCE_ROOT@"
    assert service["BindReadOnlyPaths"] == "@VENDOR_ROOT@"
    assert args[boundary + 1 :] == [
        "@VENDOR_ROOT@/bin/codex",
        "exec-server",
        "--listen",
        "ws://127.0.0.1:@PRIVATE_PORT@",
        "--ws-auth",
        "capability-token",
        "--ws-token-sha256",
        "@TOKEN_SHA256@",
    ]
    assert not any(value.startswith(("--bind-try", "--ro-bind-try")) for value in enclosure)


def test_standard_ingress_shares_only_backend_namespace_and_stops_with_backend():
    proxy = executor_unit("miy-app-executor-proxy.service")
    assert proxy["Unit"]["JoinsNamespaceOf"] == "miy-app-executor.service"
    dependencies = {"miy-app-executor.service", "miy-app-executor-proxy.socket"}
    assert set(proxy["Unit"]["BindsTo"].split()) == dependencies
    assert set(proxy["Unit"]["After"].split()) == dependencies
    assert proxy["Service"]["Type"] == "notify"
    assert shlex.split(proxy["Service"]["ExecStart"]) == [
        "/usr/lib/systemd/systemd-socket-proxyd",
        "--connections-max=2",
        "--exit-idle-time=10s",
        "127.0.0.1:@PRIVATE_PORT@",
    ]
    assert not {"BindPaths", "BindReadOnlyPaths"} & set(proxy["Service"])
    socket = executor_unit("miy-app-executor-proxy.socket")
    assert socket["Unit"]["BindsTo"] == socket["Unit"]["After"] == "miy-app-executor.service"
    assert dict(socket["Socket"]) == {
        "ListenStream": "127.0.0.1:@HOST_PORT@",
        "Accept": "no",
        "Service": "miy-app-executor-proxy.service",
    }
    assert "Install" not in socket


def test_native_pin_retains_official_packages_and_critical_helper_digests():
    from codex_console.remote_environments import REMOTE_VERSION

    pin = json.loads((EXECUTOR / "native-pin.json").read_text())
    assert pin["schema_version"] == 1
    assert pin["codex_version"] == REMOTE_VERSION == "0.160.1"
    assert pin["target"] == "x86_64-unknown-linux-musl"
    assert pin["systemd_minimum_version"] == 255
    wrapper, platform = pin["packages"]
    assert wrapper["name"] == platform["name"] == "@openai/codex"
    assert wrapper["version"] == "0.160.1"
    assert platform["version"] == "0.160.1-linux-x64"
    assert platform["alias"] == "@openai/codex-linux-x64"
    for package in pin["packages"]:
        assert package["tarball"] == (
            f"https://registry.npmjs.org/@openai/codex/-/codex-{package['version']}.tgz"
        )
        assert (
            len(base64.b64decode(package["dist_integrity"].removeprefix("sha512-"), validate=True))
            == 64
        )
        assert len(package["archive_sha256"]) == 64
        for relative, digest in package["files_sha256"].items():
            assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
            assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    vendor = pin["layout"]["vendor_relative"]
    files = platform["files_sha256"]
    assert files[f"{vendor}/bin/codex"] == (
        "f34a4d2301892ae96c90097786bfe5dc269f187b6f69faf42a7b357b8c081e35"
    )
    assert files[f"{vendor}/codex-resources/bwrap"] == (
        "77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c"
    )
    assert len(wrapper["files_sha256"]) == 3 and len(files) == 46
    assert pin["policy"] == {
        "acquisition_scripts": False,
        "automatic_download": False,
        "mutable_global_binary": False,
        "preserve_official_vendor_layout": True,
        "verification_before_installation": True,
    }
