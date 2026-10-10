import copy
import errno
import fcntl
import hashlib
import json
import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_console import controller_launch as controller
from codex_console import remote_environments, toolchain_profiles
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError

SCHEMA = {"type": "object", "properties": {"requirements": {"type": ["object", "null"]}}}


def requirements():
    return {
        "requirements": {
            **copy.deepcopy(controller.ADMIN),
            "network": copy.deepcopy(controller.NETWORK),
        }
    }


@pytest.fixture
def native_fixture(tmp_path, monkeypatch):
    vendor = tmp_path / "native/vendor" / controller.VENDOR
    binary, bwrap = vendor / "bin/codex", vendor / "codex-resources/bwrap"
    for path in (binary, bwrap):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-public-" + path.name.encode())
        path.chmod(0o555)
    monkeypatch.setattr(
        controller, "NATIVE_BINARY_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(controller, "BWRAP_SHA256", hashlib.sha256(bwrap.read_bytes()).hexdigest())
    source, home = tmp_path / "source", tmp_path / "opaque-home"
    source.mkdir()
    home.mkdir(mode=0o700)
    (home / "config.toml").write_text("# untouched synthetic host configuration\n")
    (home / "auth.json").write_bytes(b"synthetic-auth-canary-not-real-auth")
    return binary, bwrap, source, home


def test_fixed_policy_matches_current_core_contract_and_supported_empty_allowlist():
    policy = tomllib.loads(controller.REQUIREMENTS.decode())
    assert policy["model_provider"] == "openai"
    assert policy["allowed_login_methods"] == ["chatgpt"]
    assert policy["features"] == remote_environments.SAFE_FEATURES
    assert policy["allowed_sandbox_modes"] == ["read-only", "workspace-write"]
    assert policy["experimental_network"]["domains"] == {}
    assert policy["experimental_network"]["managed_allowed_domains_only"] is True
    assert "*" not in policy["experimental_network"]["domains"]
    assert (
        controller.binding_identity()["requirements_sha256"]
        == hashlib.sha256(controller.REQUIREMENTS).hexdigest()
    )
    controller.verify_requirements(requirements(), SCHEMA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("domains", {"example.com": "allow"}),
        ("unixSockets", {"/tmp/socket": "allow"}),
        ("enabled", False),
        ("enabled", 1),
        ("managedAllowedDomainsOnly", False),
        ("allowUpstreamProxy", True),
        ("dangerouslyAllowNonLoopbackProxy", True),
        ("dangerouslyAllowAllUnixSockets", True),
        ("allowLocalBinding", True),
        ("allowedDomains", ["example.com"]),
        ("httpPort", 0),
        ("socksPort", 3128),
        ("unknownPermission", False),
    ],
)
def test_effective_network_expansion_or_unknown_contract_refuses(field, value):
    response = requirements()
    response["requirements"]["network"][field] = value
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        controller.verify_requirements(response, SCHEMA)


@pytest.mark.parametrize(
    "kind",
    [
        "response_null",
        "missing_requirements",
        "requirements_null",
        "network_null",
        "missing_managed",
        "admin_expansion",
        "nested_bool_int",
        "unknown_admin",
    ],
)
def test_missing_or_changed_effective_administration_refuses(kind):
    response = requirements()
    if kind == "response_null":
        response = None
    elif kind == "missing_requirements":
        response = {}
    elif kind == "requirements_null":
        response["requirements"] = None
    elif kind == "network_null":
        response["requirements"]["network"] = None
    elif kind == "missing_managed":
        del response["requirements"]["network"]["managedAllowedDomainsOnly"]
    elif kind == "admin_expansion":
        response["requirements"]["allowedSandboxModes"].append("danger-full-access")
    elif kind == "nested_bool_int":
        response["requirements"]["featureRequirements"]["apps"] = 0
    else:
        response["requirements"]["unknownAdmin"] = {"permissions": "expanded"}
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        controller.verify_requirements(response, SCHEMA)


def test_legacy_views_cannot_expand_empty_canonical_maps():
    response = requirements()
    response["requirements"]["network"].update(
        {
            "allowedDomains": [],
            "deniedDomains": None,
            "allowUnixSockets": [],
            "httpPort": None,
            "socksPort": None,
        }
    )
    response["requirements"]["hooks"] = None
    controller.verify_requirements(response, SCHEMA)


@pytest.mark.parametrize("kind", ["missing", "invalid", "wrong_shape", "symlink"])
def test_official_requirements_schema_is_required_without_fallback(tmp_path, kind):
    path = tmp_path / "v2/ConfigRequirementsReadResponse.json"
    path.parent.mkdir()
    if kind == "invalid":
        path.write_bytes(b"{")
    elif kind == "wrong_shape":
        path.write_text('{"type":"array"}')
    elif kind == "symlink":
        target = tmp_path / "other.json"
        target.write_text(json.dumps(SCHEMA))
        path.symlink_to(target)
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        controller.requirements_schema(tmp_path)


def test_official_requirements_schema_uses_generated_v2_layout(tmp_path):
    path = tmp_path / "v2/ConfigRequirementsReadResponse.json"
    path.parent.mkdir()
    path.write_text(json.dumps(SCHEMA))
    (tmp_path / "ConfigRequirementsReadResponse.json").write_text('{"type":"array"}')

    assert controller.requirements_schema(tmp_path) == SCHEMA


def test_official_requirements_schema_rejects_root_only_layout(tmp_path):
    (tmp_path / "ConfigRequirementsReadResponse.json").write_text(json.dumps(SCHEMA))

    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        controller.requirements_schema(tmp_path)


@pytest.mark.parametrize("failure", [False, True])
def test_sealed_policy_fd_private_mount_lifetime_and_cleanup(native_fixture, failure):
    binary, bwrap, source, home = native_fixture
    context = controller.launch(
        str(binary), source, {"CODEX_HOME": str(home)}, ["app-server", "--listen", "stdio://"]
    )
    fd, scratch = None, None
    try:
        with context as prepared:
            fd = prepared.fd
            assert os.read(fd, 4096) == controller.REQUIREMENTS
            os.lseek(fd, 0, os.SEEK_SET)
            seals = fcntl.fcntl(fd, controller.F_GET_SEALS)
            assert (
                seals
                == controller.F_SEAL_WRITE
                | controller.F_SEAL_GROW
                | controller.F_SEAL_SHRINK
                | controller.F_SEAL_SEAL
            )
            with pytest.raises(OSError) as refused:
                os.write(fd, b"untrusted change")
            assert refused.value.errno == errno.EPERM
            argv = prepared.argv
            assert argv[0] == str(bwrap)
            assert "--unshare-net" not in argv  # Trusted official controller only.
            assert argv[argv.index("--cap-drop") + 1] == "ALL"
            assert argv[argv.index("--ro-bind-data") + 2] == "/etc/codex/requirements.toml"
            assert argv[argv.index("--remount-ro") + 1] == "/etc"
            assert prepared.spawn_options == {"pass_fds": (fd, prepared.config_fd)}
            last_bind = len(argv) - 1 - argv[::-1].index("--bind")
            scratch = Path(argv[last_bind + 1])
            assert scratch.is_dir()
            prepared.close_parent_fd()
            assert prepared.fd is None and scratch.is_dir()
            if failure:
                raise RuntimeError("synthetic spawn failure")
    except RuntimeError:
        assert failure
    with pytest.raises(OSError) as closed:
        os.fstat(fd)
    assert closed.value.errno == errno.EBADF
    assert not scratch.exists()
    assert not (home / "requirements.toml").exists()
    assert not (source / "requirements.toml").exists()


@pytest.mark.parametrize(
    "kind",
    [
        "binary_tamper",
        "bwrap_tamper",
        "wrapper",
        "symlink",
        "writable",
        "overlapping_home",
        "missing_home",
        "no_memfd",
    ],
)
def test_unsupported_or_changed_launch_refuses_without_host_fallback(
    native_fixture, monkeypatch, kind
):
    binary, bwrap, source, home = native_fixture
    if kind.endswith("tamper"):
        path = binary if kind == "binary_tamper" else bwrap
        path.chmod(0o755)
        path.write_bytes(b"modified-public-resource")
    elif kind == "wrapper":
        binary = binary.parent / "codex.js"
    elif kind == "symlink":
        target = binary.with_name("actual-codex")
        binary.rename(target)
        binary.symlink_to(target)
    elif kind == "writable":
        bwrap.chmod(0o777)
    elif kind == "overlapping_home":
        home = source
    elif kind == "missing_home":
        home = home / "absent"
    elif kind == "no_memfd":
        monkeypatch.setattr(
            controller,
            "_create_memfd",
            lambda *args: (_ for _ in ()).throw(OSError(errno.ENOSYS, "synthetic")),
        )
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        with controller.launch(str(binary), source, {"CODEX_HOME": str(home)}, ["app-server"]):
            pytest.fail("unsafe controller admitted")


@pytest.mark.parametrize(
    "component",
    ["REQUIREMENTS", "NETWORK", "ADMIN", "LAUNCH_CONTRACT", "NATIVE_BINARY_SHA256", "BWRAP_SHA256"],
)
def test_policy_native_admin_change_refuses_existing_task_resume(tmp_path, monkeypatch, component):
    selected = AppExecutionEnvironment(
        key="fixture",
        source_root=tmp_path,
        exec_server_url="ws://127.0.0.1:19391",
        auth_bearer_token="synthetic-" + "x" * 32,
        toolchain_profile=toolchain_profiles.SDK_PROFILE,
    )
    settings = SimpleNamespace(app_execution_environments=[selected])
    task = SimpleNamespace(
        context={
            "source_binding": {
                "repository_root": str(tmp_path),
                **remote_environments.binding_snapshot(settings, tmp_path),
            }
        },
        root=str(tmp_path),
        worktree_owned=False,
        template_snapshot={},
    )
    assert remote_environments.for_task(settings, task) is selected
    value = getattr(controller, component)
    changed = (
        value + b"\n"
        if isinstance(value, bytes)
        else {**value, "syntheticChanged": False}
        if isinstance(value, dict)
        else "0" * 64
    )
    monkeypatch.setattr(controller, component, changed)
    with pytest.raises(ConsoleError, match="app_executor_changed") as refused:
        remote_environments.for_task(settings, task)
    assert refused.value.status == 409


def test_missing_native_pin_refuses_sdk_binding_and_native_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "NATIVE_PIN", tmp_path / "absent-pin")
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        toolchain_profiles.binding_identity(
            SimpleNamespace(toolchain_profile=toolchain_profiles.SDK_PROFILE)
        )
    assert toolchain_profiles.binding_identity(SimpleNamespace()) is None


def test_sealing_failure_closes_fd_and_refuses(native_fixture, monkeypatch):
    binary, _, source, home = native_fixture
    original = controller._create_memfd
    original_fcntl = fcntl.fcntl
    created = []

    def create():
        fd = original()
        created.append(fd)
        return fd

    def failed_seal(fd, operation, *args):
        if operation == controller.F_ADD_SEALS:
            raise OSError(errno.EPERM, "synthetic sealing unavailable")
        return original_fcntl(fd, operation, *args)

    monkeypatch.setattr(controller, "_create_memfd", create)
    monkeypatch.setattr(fcntl, "fcntl", failed_seal)
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        with controller.launch(str(binary), source, {"CODEX_HOME": str(home)}, ["app-server"]):
            pytest.fail("unsealed policy admitted")
    assert len(created) == 1
    with pytest.raises(OSError) as closed:
        os.fstat(created[0])
    assert closed.value.errno == errno.EBADF


def test_empty_user_config_is_sealed_separately_without_reading_host_files(
    native_fixture, monkeypatch
):
    binary, _, source, home = native_fixture
    config, auth = home / "config.toml", home / "auth.json"
    before = {p: (p.read_bytes(), p.stat()) for p in (config, auth)}
    original_open = os.open
    opened = []

    def public_open(path, *args, **kwargs):
        assert Path(path) not in (config, auth)
        opened.append(Path(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", public_open)
    with controller.launch(str(binary), source, {"CODEX_HOME": str(home)}, ["app-server"]) as ready:
        policy_fd, config_fd = ready.spawn_options["pass_fds"]
        assert policy_fd != config_fd
        assert tomllib.loads(os.read(config_fd, 4096).decode()) == {}
        assert tomllib.loads(os.read(policy_fd, 4096).decode())["mcp_servers"] == {}
        for fd in (policy_fd, config_fd):
            assert fcntl.fcntl(fd, controller.F_GET_SEALS) == 15
            with pytest.raises(OSError) as blocked:
                os.write(fd, b"change")
            assert blocked.value.errno == errno.EPERM
        binds = [
            ready.argv[i + 1 : i + 3]
            for i, value in enumerate(ready.argv)
            if value == "--ro-bind-data"
        ]
        assert binds == [
            [str(policy_fd), "/etc/codex/requirements.toml"],
            [str(config_fd), str(config)],
        ]
    assert opened
    for fd in (policy_fd, config_fd):
        with pytest.raises(OSError):
            os.fstat(fd)
    for path, (raw, info) in before.items():
        assert path.read_bytes() == raw
        assert path.stat().st_ino == info.st_ino and path.stat().st_mode == info.st_mode


@pytest.mark.parametrize("kind", ["absent", "symlink", "hardlink", "directory", "writable"])
def test_user_config_target_refuses_before_memfd_or_missing_mountpoint_creation(
    native_fixture, monkeypatch, kind
):
    binary, _, source, home = native_fixture
    config = home / "config.toml"
    if kind in ("absent", "symlink", "directory"):
        config.unlink()
        if kind == "symlink":
            config.symlink_to(home / "auth.json")
        elif kind == "directory":
            config.mkdir()
    elif kind == "hardlink":
        os.link(config, home / "another-config")
    else:
        config.chmod(0o666)
    created = []
    monkeypatch.setattr(controller, "_create_memfd", lambda: created.append(True))
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        with controller.launch(str(binary), source, {"CODEX_HOME": str(home)}, ["app-server"]):
            pytest.fail("unsafe host configuration mount admitted")
    assert created == []
    if kind == "absent":
        assert not config.exists()
    assert (home / "auth.json").read_bytes() == b"synthetic-auth-canary-not-real-auth"


def test_second_memfd_seal_failure_closes_both_and_preserves_host_config(
    native_fixture, monkeypatch
):
    binary, _, source, home = native_fixture
    original_create, original_fcntl = controller._create_memfd, fcntl.fcntl
    created = []
    before = (home / "config.toml").read_bytes()

    def create():
        fd = original_create()
        created.append(fd)
        return fd

    def failed_second_seal(fd, operation, *args):
        if operation == controller.F_ADD_SEALS and len(created) == 2:
            raise OSError(errno.EPERM, "synthetic second sealing unavailable")
        return original_fcntl(fd, operation, *args)

    monkeypatch.setattr(controller, "_create_memfd", create)
    monkeypatch.setattr(fcntl, "fcntl", failed_second_seal)
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        with controller.launch(str(binary), source, {"CODEX_HOME": str(home)}, ["app-server"]):
            pytest.fail("unsealed empty configuration admitted")
    assert len(created) == 2
    for fd in created:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert (home / "config.toml").read_bytes() == before


@pytest.mark.parametrize("original", [None, {}, {"hooks": None}, copy.deepcopy(controller.ADMIN)])
def test_original_public_administration_is_absent_or_exactly_preserved(original):
    controller.verify_original_requirements({"requirements": original}, SCHEMA)


@pytest.mark.parametrize(
    "original",
    [
        {"network": {}},
        {"modelProvider": "other"},
        {"allowedLoginMethods": ["api_key", "chatgpt"]},
        {"allowedSandboxModes": ["read-only"]},
        {"allowedSandboxModes": ["read-only", "workspace-write", "danger-full-access"]},
        {"allowedApprovalPolicies": ["never"]},
        {"featureRequirements": {"apps": False}},
        {"featureRequirements": {**controller.FEATURES, "apps": 0}},
        {"allowLoginShell": 0},
        {"unknownAdmin": False},
    ],
)
def test_original_nonempty_unknown_partial_or_changed_admin_refuses(original):
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        controller.verify_original_requirements({"requirements": original}, SCHEMA)


def test_user_config_contract_change_rejects_old_task_fingerprint(monkeypatch):
    before = controller.binding_identity()
    monkeypatch.setattr(controller, "USER_CONFIG", controller.USER_CONFIG + b"\n")
    after = controller.binding_identity()
    assert before["user_config_sha256"] != after["user_config_sha256"]
    assert before["requirements_sha256"] == after["requirements_sha256"]


def test_public_release_builder_copies_native_and_sdk_pins_before_identity(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    import sys

    project, release = tmp_path / "project", tmp_path / "release"
    owner = Path(controller.__file__).resolve().parents[4]
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    build = scripts / "build-codex-console.sh"
    build.write_bytes((owner / "scripts/build-codex-console.sh").read_bytes())
    (scripts / "generate-app-starters.py").write_text("pass\n")
    api = project / "apps/codex-console-api"
    source = api / "src/codex_console"
    source.mkdir(parents=True)
    for name in ("__init__.py", "controller_launch.py", "toolchain_profiles.py", "errors.py"):
        (source / name).write_bytes((Path(controller.__file__).parent / name).read_bytes())
    for name in ("migrations", "sqlite_migrations"):
        (api / name).mkdir()
    for name in ("pyproject.toml", "uv.lock", "alembic.ini"):
        (api / name).write_text("synthetic packaging fixture\n")
    web = project / "apps/codex-console-web/dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("synthetic\n")
    resources = project / "ops/codex-console/executor"
    resources.mkdir(parents=True)
    for name in ("sdk-toolchain-pin.json", "native-pin.json"):
        (resources / name).write_bytes((owner / "ops/codex-console/executor" / name).read_bytes())
    tools = tmp_path / "external-tool-stubs"
    tools.mkdir()
    for name in ("pnpm", "uv", "git"):
        code = "#!/bin/sh\nexit 0\n"
        if name == "git":
            code = (
                '#!/bin/sh\nif [ "$3" = "rev-parse" ]; then '
                "echo 0000000000000000000000000000000000000000; fi\n"
            )
        path = tools / name
        path.write_text(code)
        path.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(build), str(release), sys.executable],
        env={"PATH": str(tools) + ":" + os.defpath},
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0
    identity = json.loads(
        (release / "apps/codex-console-api/src/codex_console/_build.json").read_text()
    )
    assert identity["source_dirty"] is False and identity["digest"].startswith("sha256:")
    for name in ("sdk-toolchain-pin.json", "native-pin.json"):
        assert (release / "ops/codex-console/executor" / name).read_bytes() == (
            resources / name
        ).read_bytes()
    package_root = release / "apps/codex-console-api/src/codex_console"
    spec = importlib.util.spec_from_file_location(
        "synthetic_packaged_console",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, package)
    spec.loader.exec_module(package)
    spec = importlib.util.spec_from_file_location(
        "synthetic_packaged_console.toolchain_profiles", package_root / "toolchain_profiles.py"
    )
    packaged = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, packaged)
    spec.loader.exec_module(packaged)
    sdk = SimpleNamespace(toolchain_profile=toolchain_profiles.SDK_PROFILE)
    assert (
        packaged.binding_identity(sdk)["controller"]["native_pin_sha256"]
        == controller.NATIVE_PIN_SHA256
    )
    native = release / "ops/codex-console/executor/native-pin.json"
    native.write_bytes(native.read_bytes() + b"\n")
    with pytest.raises(packaged.ConsoleError, match="app_executor_configuration"):
        packaged.binding_identity(sdk)
