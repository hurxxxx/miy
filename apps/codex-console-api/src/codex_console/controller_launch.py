"""SDK-only official controller launch and public managed-policy attestation.

The remote executor retains its own namespace and PrivateNetwork ceiling. This
adapter does not implement auth, agent, thread, proxy or command lifecycles.
"""

import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .errors import ConsoleError

CONTRACT_VERSION = 1
# Fixed Linux UAPI values; older-header CPython builds omit these constants.
F_ADD_SEALS = getattr(fcntl, "F_ADD_SEALS", 1033)
F_GET_SEALS = getattr(fcntl, "F_GET_SEALS", 1034)
F_SEAL_SEAL = getattr(fcntl, "F_SEAL_SEAL", 0x0001)
F_SEAL_SHRINK = getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
F_SEAL_GROW = getattr(fcntl, "F_SEAL_GROW", 0x0004)
F_SEAL_WRITE = getattr(fcntl, "F_SEAL_WRITE", 0x0008)
NATIVE_PIN_SHA256 = "ef9496536303ef3dae1bd65a5cc321f38429f3ed59e50e0757fa7fe72ec66975"
NATIVE_BINARY_SHA256 = "f34a4d2301892ae96c90097786bfe5dc269f187b6f69faf42a7b357b8c081e35"
BWRAP_SHA256 = "77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c"
NATIVE_PIN = Path(__file__).resolve().parents[4] / "ops/codex-console/executor/native-pin.json"
VENDOR = "x86_64-unknown-linux-musl"
FEATURES = {
    "apps": False,
    "plugins": False,
    "hooks": False,
    "shell_snapshot": False,
    "shell_snapshot_v2": False,
    "skip_host_skill_discovery": True,
    "skill_mcp_dependency_install": False,
    "deferred_executor": True,
    "executor_capability_discovery": True,
}
NETWORK = {
    "enabled": True,
    "managedAllowedDomainsOnly": True,
    "allowUpstreamProxy": False,
    "dangerouslyAllowNonLoopbackProxy": False,
    "dangerouslyAllowAllUnixSockets": False,
    "allowLocalBinding": False,
    "domains": {},
    "unixSockets": {},
}
ADMIN = {
    "modelProvider": "openai",
    "allowedLoginMethods": ["chatgpt"],
    "allowLoginShell": False,
    "allowedSandboxModes": ["read-only", "workspace-write"],
    "allowedApprovalPolicies": ["never", "on-request"],
    "featureRequirements": FEATURES,
}
USER_CONFIG = b"# MIY SDK controller: host user configuration is not inherited.\n"
REQUIREMENTS = (
    'model_provider = "openai"\n'
    'allowed_login_methods = ["chatgpt"]\n'
    "allow_login_shell = false\n"
    'allowed_sandbox_modes = ["read-only", "workspace-write"]\n'
    'allowed_approval_policies = ["never", "on-request"]\n\n'
    "mcp_servers = {}\n\n"
    "[features]\n"
    + "".join(f"{key} = {str(value).lower()}\n" for key, value in FEATURES.items())
    + "\n[experimental_network]\n"
    "enabled = true\n"
    "managed_allowed_domains_only = true\n"
    "allow_upstream_proxy = false\n"
    "dangerously_allow_non_loopback_proxy = false\n"
    "dangerously_allow_all_unix_sockets = false\n"
    "allow_local_binding = false\n"
    "unix_sockets = {}\n"
    "domains = {}\n"
).encode()
LAUNCH_CONTRACT = {
    "version": CONTRACT_VERSION,
    "private_etc_overlay": True,
    "requirements_fd_seals": ["WRITE", "GROW", "SHRINK", "SEAL"],
    "controller_host_network": True,
    "remote_private_network": True,
    "namespaces": ["user", "pid", "ipc", "uts"],
    "root_readonly": True,
    "capabilities": [],
    "writable": ["opaque_official_codex_home", "private_controller_scratch"],
    "user_config": "sealed_empty_existing_regular_target",
    "bootstrap": {"sandbox_mode": "read-only", "approval_policy": "never"},
}


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _refuse():
    raise ConsoleError("app_executor_configuration", 503) from None


def _public_file(path, maximum, *, executable=False, digest=False):
    """Read one public pinned resource without following its final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid not in (0, os.getuid())
                or info.st_mode & 0o022
                or not 0 < info.st_size <= maximum
                or executable
                and not info.st_mode & 0o111
            ):
                _refuse()
            if digest:
                hasher = hashlib.sha256()
                length = 0
                while chunk := file.read(min(8 * 1024 * 1024, info.st_size - length + 1)):
                    length += len(chunk)
                    if length > info.st_size:
                        _refuse()
                    hasher.update(chunk)
                raw = hasher.hexdigest()
            else:
                raw = file.read(info.st_size + 1)
                length = len(raw)
            after = os.fstat(file.fileno())
        if length != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            _refuse()
        return raw
    except OSError:
        _refuse()


def binding_identity():
    """Only public contract identities enter existing Task SQLite bindings."""
    if hashlib.sha256(_public_file(NATIVE_PIN, 128 * 1024)).hexdigest() != NATIVE_PIN_SHA256:
        _refuse()
    return {
        "version": CONTRACT_VERSION,
        "requirements_sha256": hashlib.sha256(REQUIREMENTS).hexdigest(),
        "network_sha256": _digest(NETWORK),
        "admin_sha256": _digest(ADMIN),
        "native_pin_sha256": NATIVE_PIN_SHA256,
        "native_binary_sha256": NATIVE_BINARY_SHA256,
        "bwrap_sha256": BWRAP_SHA256,
        "launch_sha256": _digest(LAUNCH_CONTRACT),
        "user_config_sha256": hashlib.sha256(USER_CONFIG).hexdigest(),
    }


def requirements_schema(directory):
    try:
        schema = json.loads(
            _public_file(Path(directory) / "v2/ConfigRequirementsReadResponse.json", 1024 * 1024)
        )
        Draft7Validator.check_schema(schema)
        if schema.get("type") != "object" or "requirements" not in schema.get("properties", {}):
            _refuse()
        return schema
    except (ValueError, TypeError, RecursionError, SchemaError):
        _refuse()


def _same(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same(actual[k], v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def verify_requirements(response, schema):
    """Reject expansion, unsupported managed administration, and absent policy."""
    try:
        Draft7Validator(schema).validate(response)
        requirements = response["requirements"]
        if not isinstance(requirements, dict):
            _refuse()
        network = requirements["network"]
        if not isinstance(network, dict):
            _refuse()
        for key, value in NETWORK.items():
            if not _same(network.get(key), value):
                _refuse()
        for key, value in network.items():
            if key in NETWORK:
                continue
            if key in ("allowedDomains", "deniedDomains", "allowUnixSockets"):
                if value is not None and (type(value) is not list or value):
                    _refuse()
            elif key in ("httpPort", "socksPort"):
                if value is not None:
                    _refuse()
            else:
                _refuse()
        for key, value in ADMIN.items():
            actual = requirements.get(key)
            if not _same(actual, value):
                _refuse()
        # A new cloud/admin contract is reviewed deliberately, never silently
        # discarded by this private system-policy replacement.
        if any(
            value is not None
            for key, value in requirements.items()
            if key not in (*ADMIN, "network")
        ):
            _refuse()
    except (KeyError, TypeError, ValidationError):
        _refuse()


def verify_original_requirements(response, schema):
    """Preserve every supported original public admin value before overlay."""
    try:
        Draft7Validator(schema).validate(response)
        requirements = response["requirements"]
        if requirements is None:
            return
        if not isinstance(requirements, dict):
            _refuse()
        for key, value in requirements.items():
            if value is not None and (key not in ADMIN or not _same(value, ADMIN[key])):
                _refuse()
    except (KeyError, TypeError, ValidationError):
        _refuse()


def verify_request(method, params):
    if params.get("permissions") is not None:
        _refuse()
    if method in ("thread/start", "thread/resume"):
        if params.get("sandbox") != "read-only":
            _refuse()
    elif method == "turn/start":
        policy = params.get("sandboxPolicy")
        if (
            not isinstance(policy, dict)
            or policy.get("type") not in ("readOnly", "workspaceWrite")
            or policy.get("networkAccess") is not False
        ):
            _refuse()


def _directory(path):
    """Metadata-only opaque mount validation; never read auth/config contents."""
    path = Path(path)
    if not path.is_absolute():
        _refuse()
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except OSError:
            _refuse()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
            _refuse()
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            _refuse()
    return path


def _native_resources(binary):
    binary = Path(binary)
    if not binary.is_absolute() or binary.parts[-4:] != ("vendor", VENDOR, "bin", "codex"):
        _refuse()
    _directory(binary.parent)
    bwrap = binary.parent.parent / "codex-resources/bwrap"
    _directory(bwrap.parent)
    if (
        _public_file(binary, 512 * 1024 * 1024, executable=True, digest=True)
        != NATIVE_BINARY_SHA256
    ):
        _refuse()
    if _public_file(bwrap, 32 * 1024 * 1024, executable=True, digest=True) != BWRAP_SHA256:
        _refuse()
    return binary, bwrap


def _user_config_target(home):
    """Validate only metadata; never read the original configuration."""
    path = home / "config.toml"
    try:
        info = path.lstat()
    except OSError:
        _refuse()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid not in (0, os.getuid())
        or info.st_nlink != 1
        or info.st_mode & 0o022
    ):
        _refuse()
    return path, (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


@dataclass
class ControllerLaunch:
    argv: list[str]
    fd: int | None
    config_fd: int | None = None

    @property
    def spawn_options(self):
        return {"pass_fds": (self.fd, self.config_fd)}

    def close_parent_fd(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.config_fd is not None:
            os.close(self.config_fd)
            self.config_fd = None


def _create_memfd():
    # CPython can omit os.memfd_create when built against older libc headers.
    # The documented Linux libc symbol still performs the identical sealed-fd
    # operation. No architecture-specific syscall or unsealed file substitute.
    if hasattr(os, "memfd_create"):
        return os.memfd_create("miy-sdk-controller-requirements", 0x0001 | 0x0002)
    libc = ctypes.CDLL(None, use_errno=True)
    create = libc.memfd_create
    create.argtypes = [ctypes.c_char_p, ctypes.c_uint]
    create.restype = ctypes.c_int
    fd = create(b"miy-sdk-controller-requirements", 0x0001 | 0x0002)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "memfd_create unavailable")
    return fd


@contextlib.contextmanager
def launch(binary, cwd, environment, arguments):
    """Prepare a single spawn; caller retains the official stdio lifecycle."""
    binding_identity()
    binary, bwrap = _native_resources(binary)
    root = _directory(cwd)
    home = environment.get("CODEX_HOME")
    if not home:
        if not environment.get("HOME"):
            _refuse()
        home = Path(environment["HOME"]) / ".codex"
    codex_home = _directory(home)
    if codex_home.is_relative_to(root) or root.is_relative_to(codex_home):
        _refuse()
    user_config, original_metadata = _user_config_target(codex_home)
    fd = None
    config_fd = None
    prepared = None
    try:
        fd = _create_memfd()
        if os.write(fd, REQUIREMENTS) != len(REQUIREMENTS):
            _refuse()
        os.lseek(fd, 0, os.SEEK_SET)
        seals = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL
        fcntl.fcntl(fd, F_ADD_SEALS, seals)
        if fcntl.fcntl(fd, F_GET_SEALS) != seals:
            _refuse()
        config_fd = _create_memfd()
        if os.write(config_fd, USER_CONFIG) != len(USER_CONFIG):
            _refuse()
        os.lseek(config_fd, 0, os.SEEK_SET)
        fcntl.fcntl(config_fd, F_ADD_SEALS, seals)
        if fcntl.fcntl(config_fd, F_GET_SEALS) != seals:
            _refuse()
        with tempfile.TemporaryDirectory(prefix="miy-sdk-controller-") as scratch:
            argv = [
                str(bwrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-user",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--cap-drop",
                "ALL",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--overlay-src",
                "/etc",
                "--tmp-overlay",
                "/etc",
                "--dir",
                "/etc/codex",
                "--perms",
                "0400",
                "--ro-bind-data",
                str(fd),
                "/etc/codex/requirements.toml",
                "--remount-ro",
                "/etc",
                "--bind",
                str(codex_home),
                str(codex_home),
                "--perms",
                "0400",
                "--ro-bind-data",
                str(config_fd),
                str(user_config),
                "--bind",
                scratch,
                scratch,
                "--chdir",
                str(root),
                "--",
                str(binary),
                *arguments,
            ]
            if _user_config_target(codex_home)[1] != original_metadata:
                _refuse()
            prepared = ControllerLaunch(argv, fd, config_fd)
            yield prepared
            if _user_config_target(codex_home)[1] != original_metadata:
                _refuse()
    except (OSError, AttributeError, KeyError):
        _refuse()
    finally:
        if prepared is not None:
            prepared.close_parent_fd()
        elif fd is not None:
            os.close(fd)
        if prepared is None and config_fd is not None:
            os.close(config_fd)
