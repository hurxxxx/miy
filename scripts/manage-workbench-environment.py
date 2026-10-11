#!/usr/bin/env python3
"""Operator-owned managed SDK units. Only describe returns a private capability.

The Workbench supplies a public, immutable workspace snapshot on stdin. This
adapter never reads app code for commands, acquires packages or controls Git.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "miy-native-sdk-20261011-v3"
LIMIT = 128 * 1024
APP_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
REVISION = re.compile(r"[0-9a-f]{40}")
SNAPSHOT_FIELDS = {
    "id",
    "app_id",
    "repository_root",
    "worktree_path",
    "app_directory",
    "branch",
    "base_revision",
    "source_revision",
    "profile_id",
}
SUFFIXES = (".service", "-proxy.service", "-proxy.socket")


class Refused(ValueError):
    """Only stable public codes cross the subprocess boundary."""


def refuse(code="workspace_environment_unavailable"):
    raise Refused(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def directory(path, *, private=False):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        refuse()
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
            refuse()
        if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
            refuse()
    info = path.stat()
    if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        refuse()
    return path


def read_file(path, *, private=False, maximum=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid not in (0, os.getuid())
            or info.st_mode & 0o022
            or info.st_size > maximum
            or private
            and (info.st_uid != os.getuid() or info.st_mode & 0o077)
        ):
            refuse()
        value = stream.read(maximum + 1)
        if len(value) != info.st_size:
            refuse()
        return value


def write_private(path, value, *, new=False, private_parent=True):
    directory(path.parent, private=private_parent)
    if new and path.exists():
        refuse("workspace_operation_unknown")
    if path.exists():
        read_file(path, private=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if new:
            os.link(temporary, path, follow_symlinks=False)
        else:
            os.replace(temporary, path)
        parentfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parentfd)
        finally:
            os.close(parentfd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config(path):
    directory(path.parent, private=True)
    config = json.loads(read_file(path, private=True))
    fields = {
        "schema_version",
        "repository_root",
        "worktree_root",
        "state_root",
        "vendor_root",
        "sdk_root",
        "executor_uid",
        "executor_gid",
        "host_ports",
        "private_port",
        "unit_root",
        "systemctl_path",
        "socket_proxyd_path",
    }
    if (
        not isinstance(config, dict)
        or set(config) not in (fields, fields | {"system_unit_broker"})
        or config["schema_version"] != 1
    ):
        refuse()
    if (
        type(config["executor_uid"]) is not int
        or type(config["executor_gid"]) is not int
        or config["executor_uid"] != os.getuid()
        or config["executor_gid"] != os.getgid()
        or os.getuid() == 0
    ):
        refuse()
    for name in (
        "repository_root",
        "worktree_root",
        "state_root",
        "vendor_root",
        "sdk_root",
        "unit_root",
    ):
        config[name] = directory(config[name], private=name == "state_root")
    if (
        config["state_root"].is_relative_to(config["worktree_root"])
        or config["state_root"].is_relative_to(config["repository_root"])
        or config["worktree_root"].is_relative_to(config["repository_root"])
        or config["unit_root"]
        != (
            Path("/etc/systemd/system")
            if config.get("system_unit_broker")
            else Path.home() / ".config/systemd/user"
        )
    ):
        refuse()
    ports = config["host_ports"]
    if (
        not isinstance(ports, list)
        or not 1 <= len(ports) <= 32
        or len(set(ports)) != len(ports)
        or any(type(port) is not int or not 1024 <= port <= 65535 for port in ports)
        or type(config["private_port"]) is not int
        or not 1024 <= config["private_port"] <= 65535
    ):
        refuse()
    for name in ("systemctl_path", "socket_proxyd_path"):
        path = Path(config[name])
        directory(path.parent)
        info = path.stat()
        if (
            not path.is_absolute()
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022
            or not info.st_mode & 0o111
        ):
            refuse()
        config[name] = path
    if "system_unit_broker" in config:
        broker = Path(config["system_unit_broker"])
        if broker != Path("/usr/local/libexec/miy-workbench-environment"):
            refuse()
        directory(broker.parent)
        info = broker.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o022
            or not info.st_mode & 0o111
        ):
            refuse()
        config["system_unit_broker"] = broker
    return config


def empty_git_mask(source, item, owner):
    """Only native's empty app-root mask; never expose actual Git metadata."""
    if item != source / ".git":
        return False
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(".git", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd)
        finally:
            os.close(source_fd)
        try:
            info = os.fstat(fd)
            return info.st_uid == owner and not info.st_mode & 0o022 and not os.listdir(fd)
        finally:
            os.close(fd)
    except OSError:
        return False


def snapshot_identity(config, snapshot, *, source_required=True):
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        refuse()
    try:
        identity = UUID(snapshot["id"])
    except (ValueError, TypeError, AttributeError):
        refuse()
    app_id = snapshot["app_id"]
    if (
        str(identity) != snapshot["id"]
        or not isinstance(app_id, str)
        or not APP_ID.fullmatch(app_id)
        or len(app_id) > 100
        or snapshot["profile_id"] != "app"
        or not isinstance(snapshot["branch"], str)
        or not re.fullmatch(r"feature/[a-zA-Z0-9/_-]+", snapshot["branch"])
        or not all(
            isinstance(snapshot[key], str) and REVISION.fullmatch(snapshot[key])
            for key in ("base_revision", "source_revision")
        )
    ):
        refuse()
    worktree = config["worktree_root"] / str(identity)
    app_directory = "personal-apps/" + app_id
    if (
        snapshot["repository_root"] != str(config["repository_root"])
        or snapshot["worktree_path"] != str(worktree)
        or snapshot["app_directory"] != app_directory
    ):
        refuse()
    source = worktree / app_directory
    if source_required:
        directory(source)
        count = 0
        for parent, dirs, files in os.walk(source, followlinks=False):
            for name in (*dirs, *files):
                count += 1
                item = Path(parent) / name
                info = item.lstat()
                if (
                    count <= 20000
                    and name == ".git"
                    and empty_git_mask(source, item, config["executor_uid"])
                ):
                    dirs.remove(name)
                    continue
                if (
                    count > 20000
                    or name == ".git"
                    or name.startswith(".env")
                    or stat.S_ISLNK(info.st_mode)
                ):
                    refuse()
                if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                    refuse()
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    refuse()
    # Source HEAD changes are expected. The immutable path/branch binding is not.
    binding = {key: snapshot[key] for key in SNAPSHOT_FIELDS - {"source_revision"}}
    return source, sha(canonical(binding))


def verifier():
    spec = importlib.util.spec_from_file_location(
        "managed_sdk_verify", ROOT / "scripts/verify-native-sdk-toolchain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_inputs(config, source):
    verify = verifier()
    pin = verify.load_pin()
    if pin["toolchain_id"] != PROFILE or config["sdk_root"] != Path("/opt/miy") / PROFILE:
        refuse()
    # A linked worktree has no tracked dependency tree. Reserve only this empty
    # mountpoint; existing files/links are verified by the unchanged SDK rules.
    dependencies = source / "node_modules"
    if not dependencies.exists() and not dependencies.is_symlink():
        dependencies.mkdir(mode=0o700)
    verify.install_path(config["sdk_root"])
    records, elf = verify.scan_tree(config["sdk_root"], owner=0)
    verify.verify_inventory(records, pin)
    verify.verify_elf(elf, pin)
    verify.verify_source_mounts(source, pin, managed=True)
    sys.path.insert(0, str(ROOT / "apps/codex-console-api/src"))
    from codex_console import controller_launch
    from codex_console.errors import ConsoleError

    try:
        controller_launch.binding_identity()
        controller_launch._native_resources(config["vendor_root"] / "bin/codex")
    except ConsoleError:
        refuse()


def templates(config, source, stem, host_port, token, *, legacy_budget=False):
    values = {
        "SOURCE_ROOT": str(source),
        "VENDOR_ROOT": str(config["vendor_root"]),
        "SDK_ROOT": str(config["sdk_root"]),
        "UNIT_STEM": stem,
        "EXECUTOR_UID": str(config["executor_uid"]),
        "EXECUTOR_GID": str(config["executor_gid"]),
        "HOST_PORT": str(host_port),
        "PRIVATE_PORT": str(config["private_port"]),
        "TOKEN_SHA256": sha(token.encode()),
    }
    # Reject systemd specifier/quoting injection before native substitution.
    if any(
        not re.fullmatch(r"[A-Za-z0-9/._+@-]+", value) or re.search(r"@[A-Z_]+@", value)
        for value in values.values()
    ):
        refuse()
    result = {}
    for suffix in SUFFIXES:
        path = ROOT / "ops/codex-console/executor" / ("miy-app-sdk-managed" + suffix + ".example")
        text = read_file(path).decode()
        if suffix == ".service":
            if text.count("\nTasksMax=256\n") != 1:
                refuse()
            if legacy_budget:
                text = text.replace("\nTasksMax=256\n", "\nTasksMax=64\n")
        if config.get("system_unit_broker"):
            text = text.replace(
                "[Service]\n",
                "[Service]\nUser=@EXECUTOR_UID@\nGroup=@EXECUTOR_GID@\n",
            )
        text = text.replace(
            "/usr/lib/systemd/systemd-socket-proxyd", str(config["socket_proxyd_path"])
        )
        for key, value in values.items():
            text = text.replace("@" + key + "@", value)
        if re.search(r"@[A-Z_]+@", text):
            refuse()
        result[stem + suffix] = text.encode()
    return result


class Native:
    def __init__(self, config):
        self.config = config

    def systemctl(self, *args):
        environment = {"PATH": os.defpath}
        for key in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
            if key in os.environ:
                environment[key] = os.environ[key]
        result = subprocess.run(
            [str(self.config["systemctl_path"]), "--user", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            env=environment,
            check=False,
        )
        if len(result.stdout) > LIMIT:
            refuse()
        return result

    def states(self, units):
        result = self.systemctl(
            "show",
            "--property=Id,LoadState,ActiveState,SubState,MainPID,ControlPID,FragmentPath",
            *units,
        )
        if result.returncode:
            refuse()
        output = []
        for block in result.stdout.decode().strip().split("\n\n"):
            properties = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            if properties.get("Id") not in units:
                refuse()
            if properties.get("LoadState") != "not-found" and properties.get("FragmentPath") != str(
                self.config["unit_root"] / properties["Id"]
            ):
                refuse()
            output.append(properties)
        if len(output) != len(units) or len({item["Id"] for item in output}) != len(units):
            refuse()
        return output

    def require(self, *args):
        if self.systemctl(*args).returncode:
            refuse("workspace_operation_unknown")

    def inactive(self, units):
        states = self.states(units)
        return all(
            item.get("ActiveState") in {"inactive", "failed"}
            and (item["Id"].endswith(".socket") or item.get("MainPID") == "0")
            and item.get("ControlPID", "0") == "0"
            for item in states
        )

    def ready(self, units, descriptor):
        async def observe():
            sys.path.insert(0, str(ROOT / "apps/codex-console-api/src"))
            from websockets.exceptions import WebSocketException

            from codex_console.config import AppExecutionEnvironment
            from codex_console.executor_probe import ProbeFailure, preflight

            try:
                await preflight(AppExecutionEnvironment.model_validate(descriptor))
                return True
            except (OSError, ValueError, ProbeFailure, WebSocketException):
                return False

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            states = self.states(units)
            if any(item.get("ActiveState") == "failed" for item in states):
                refuse("workspace_environment_unavailable")
            # The socket-activated proxy may be inactive before the first connection.
            byname = {item["Id"]: item for item in states}
            if (
                byname[units[0]].get("ActiveState") == "active"
                and byname[units[2]].get("ActiveState") == "active"
                and asyncio.run(observe())
            ):
                return
            time.sleep(0.5)
        refuse("workspace_operation_unknown")


class SystemBroker(Native):
    """The root entrypoint owns only fixed units; SDK/app imports stay here."""

    def __init__(self, config, snapshot):
        super().__init__(config)
        self.snapshot = snapshot
        stem = "miy-wb-" + UUID(snapshot["id"]).hex
        self.units = [stem + suffix for suffix in SUFFIXES]

    def request(self, action, **values):
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", str(self.config["system_unit_broker"])],
            input=canonical({"action": action, "snapshot": self.snapshot, **values}),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            env={"PATH": os.defpath},
            check=False,
        )
        if result.returncode or len(result.stdout) > LIMIT:
            refuse("workspace_operation_unknown")
        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            refuse()
        return output

    def states(self, units):
        if units != self.units:
            refuse()
        output = self.request("query").get("states")
        if (
            not isinstance(output, list)
            or len(output) != len(units)
            or {item.get("Id") for item in output} != set(units)
        ):
            refuse()
        return output

    def install(self, rendered, port, token):
        expected = {name: sha(raw) for name, raw in rendered.items()}
        actual = self.request(
            "install", host_port=port, token_sha256=sha(token.encode()), units=expected
        )
        if actual.get("units") != expected:
            refuse("workspace_operation_unknown")

    def require(self, *args):
        if args == ("daemon-reload",):
            # install/cleanup perform their reload in the same privileged scope.
            return
        if args == ("start", self.units[0], self.units[2]):
            self.request("start")
        elif args == ("stop", self.units[2], self.units[1], self.units[0]):
            self.request("stop")
        else:
            refuse()

    def remove(self):
        self.request("cleanup")

    def upgrade_budget(self, rendered, token):
        expected = {name: sha(raw) for name, raw in rendered.items()}
        actual = self.request("upgrade-budget", token_sha256=sha(token.encode()), units=expected)
        if actual.get("units") != expected:
            refuse("workspace_operation_unknown")


def read_json(path):
    value = json.loads(read_file(path, private=True))
    if not isinstance(value, dict):
        refuse()
    return value


def verify_owned_units(config, journal, *, required=True):
    for name, expected in journal["units"].items():
        path = config["unit_root"] / name
        if not path.exists() and not required:
            continue
        if sha(read_file(path, private=not config.get("system_unit_broker"))) != expected:
            refuse("workspace_operation_unknown")


def removed_units(config, units, native):
    # lstat also sees broken links: an absent target is not an absent owned unit.
    for name in units:
        try:
            (config["unit_root"] / name).lstat()
        except FileNotFoundError:
            continue
        return False
    states = native.states(units)
    if len(states) != len(units) or {item.get("Id") for item in states} != set(units):
        refuse("workspace_operation_unknown")
    return all(
        item.get("LoadState") == "not-found"
        and item.get("ActiveState") == "inactive"
        and item.get("MainPID", "0" if item["Id"].endswith(".socket") else None) == "0"
        and item.get("ControlPID") == "0"
        for item in states
    )


def descriptor_units(config, source, stem, journal, path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        refuse("workspace_operation_unknown")
    descriptor = read_json(path)
    if (
        set(descriptor)
        != {
            "key",
            "source_root",
            "exec_server_url",
            "auth_bearer_token",
            "toolchain_profile",
        }
        or descriptor["key"] != stem.removeprefix("miy-")
        or descriptor["source_root"] != str(source)
        or descriptor["exec_server_url"] != "ws://127.0.0.1:" + str(journal["host_port"])
        or descriptor["toolchain_profile"] != PROFILE
        or not isinstance(descriptor["auth_bearer_token"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{64}", descriptor["auth_bearer_token"])
    ):
        refuse("workspace_operation_unknown")
    rendered = templates(
        config, source, stem, journal["host_port"], descriptor["auth_bearer_token"]
    )
    legacy = templates(
        config,
        source,
        stem,
        journal["host_port"],
        descriptor["auth_bearer_token"],
        legacy_budget=True,
    )
    return descriptor, rendered, legacy


def verify_residual_descriptor(config, source, stem, journal, path, *, allow_legacy=True):
    observed = descriptor_units(config, source, stem, journal, path)
    if observed is None:
        return False
    _, rendered, legacy = observed
    allowed = [{name: sha(raw) for name, raw in rendered.items()}]
    if allow_legacy:
        allowed.append({name: sha(raw) for name, raw in legacy.items()})
    if journal["units"] not in allowed:
        refuse("workspace_operation_unknown")
    return True


def quiescent(config, units, native):
    states = native.states(units)
    return (
        len(states) == len(units)
        and {item.get("Id") for item in states} == set(units)
        and all(
            item.get("ActiveState") == "inactive"
            and item.get("ControlPID") == "0"
            and item.get("MainPID", "0" if item["Id"].endswith(".socket") else None) == "0"
            and item.get("FragmentPath") == str(config["unit_root"] / item["Id"])
            for item in states
        )
    )


def verify_upgrade_units(config, original, target):
    for name, expected in original.items():
        actual = sha(
            read_file(config["unit_root"] / name, private=not config.get("system_unit_broker"))
        )
        if actual not in {expected, target[name]}:
            refuse("workspace_operation_unknown")


def upgrade_budget(config, source, stem, journal, journal_path, descriptor_path, native, validate):
    """Explicit, stopped-only migration; never start execution or replace identity."""
    if journal["state"] not in {"stopped", "upgrading"}:
        refuse("workspace_operation_unknown")
    observed = descriptor_units(config, source, stem, journal, descriptor_path)
    if observed is None:
        refuse("workspace_operation_unknown")
    descriptor, rendered, legacy = observed
    original = {name: sha(raw) for name, raw in legacy.items()}
    target = {name: sha(raw) for name, raw in rendered.items()}
    intent = {"from_units": original, "to_units": target}
    # A completed retry needs the same original durable intent, not merely a
    # matching new unit. Ordinary preparation never creates this receipt.
    completed = journal["state"] == "stopped" and journal["units"] == target
    if completed:
        if journal.get("budget_upgrade") != intent:
            refuse("workspace_operation_unknown")
        verify_owned_units(config, journal)
    elif journal["units"] != original or (
        journal["state"] == "upgrading" and journal.get("budget_upgrade") != intent
    ):
        refuse("workspace_operation_unknown")
    else:
        if journal["state"] == "upgrading":
            verify_upgrade_units(config, original, target)
        else:
            verify_owned_units(config, journal)
    validate(config, source)
    if not quiescent(config, list(rendered), native):
        refuse("workspace_operation_unknown")
    if completed:
        return {"state": "stopped"}
    if journal["state"] == "stopped":
        journal["state"] = "upgrading"
        journal["budget_upgrade"] = intent
        write_private(journal_path, canonical(journal))
    try:
        if config.get("system_unit_broker"):
            native.upgrade_budget(rendered, descriptor["auth_bearer_token"])
        else:
            backend = stem + ".service"
            if sha(read_file(config["unit_root"] / backend, private=True)) == original[backend]:
                write_private(
                    config["unit_root"] / backend,
                    rendered[backend],
                    private_parent=False,
                )
            native.require("daemon-reload")
        verify_owned_units(config, {"units": target})
        if not quiescent(config, list(rendered), native):
            refuse("workspace_operation_unknown")
        journal["units"] = target
        journal["state"] = "stopped"
        write_private(journal_path, canonical(journal))
    except (Refused, OSError, ValueError, subprocess.SubprocessError):
        refuse("workspace_operation_unknown")
    return {"state": "stopped"}


def host_port(config):
    reserved = set()
    for path in config["state_root"].glob("*/journal.json"):
        directory(path.parent, private=True)
        record = read_json(path)
        if record.get("state") != "cleaned":
            reserved.add(record["host_port"])
    for port in config["host_ports"]:
        if port in reserved:
            continue
        with socket.socket() as connection:
            try:
                connection.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    refuse("workspace_environment_capacity")


def manage(config, snapshot, action, *, native=None, validate=verify_inputs):
    source, binding = snapshot_identity(
        config,
        snapshot,
        source_required=action in {"prepare", "resume", "describe", "upgrade-budget"},
    )
    native = native or (
        SystemBroker(config, snapshot) if config.get("system_unit_broker") else Native(config)
    )
    state_path = config["state_root"] / snapshot["id"]
    journal_path = state_path / "journal.json"
    descriptor_path = state_path / "descriptor.json"
    stem = "miy-wb-" + UUID(snapshot["id"]).hex
    units = [stem + suffix for suffix in SUFFIXES]
    if state_path.exists():
        directory(state_path, private=True)
        journal = read_json(journal_path)
        if journal.get("id") != snapshot["id"] or journal.get("binding") != binding:
            refuse("workspace_environment_changed")
        if set(journal.get("units", {})) != set(units):
            refuse()
    elif action == "prepare":
        validate(config, source)
        # Foreign or stale same-name units must never be replaced or adopted.
        if any(item.get("LoadState") != "not-found" for item in native.states(units)):
            refuse("workspace_operation_unknown")
        token = secrets.token_urlsafe(48)
        port = host_port(config)
        rendered = templates(config, source, stem, port, token)
        descriptor = {
            "key": "wb-" + UUID(snapshot["id"]).hex,
            "source_root": str(source),
            "exec_server_url": "ws://127.0.0.1:" + str(port),
            "auth_bearer_token": token,
            "toolchain_profile": PROFILE,
        }
        journal = {
            "id": snapshot["id"],
            "binding": binding,
            "state": "preparing",
            "host_port": port,
            "units": {name: sha(raw) for name, raw in rendered.items()},
            "failure_code": None,
        }
        state_path.mkdir(mode=0o700)
        write_private(descriptor_path, canonical(descriptor), new=True)
        write_private(journal_path, canonical(journal), new=True)
        try:
            if config.get("system_unit_broker"):
                native.install(rendered, port, token)
            else:
                for name, raw in rendered.items():
                    write_private(config["unit_root"] / name, raw, new=True, private_parent=False)
            native.require("daemon-reload")
            native.require("start", units[0], units[2])
            native.ready(units, descriptor)
        except (Refused, OSError, ValueError, subprocess.SubprocessError):
            # Receipt remains preparing/unknown: no retry, cleanup or secret emission.
            journal["state"] = "unknown"
            journal["failure_code"] = "workspace_operation_unknown"
            write_private(journal_path, canonical(journal))
            refuse("workspace_operation_unknown")
        journal["state"] = "ready"
        write_private(journal_path, canonical(journal))
        return {"state": "ready"}
    else:
        if action == "status":
            return {"state": "unknown"}
        refuse("workspace_environment_unavailable")
    if action == "upgrade-budget":
        return upgrade_budget(
            config,
            source,
            stem,
            journal,
            journal_path,
            descriptor_path,
            native,
            validate,
        )
    if journal["state"] == "upgrading":
        # Only explicit continuation may finish the original migration.
        if action == "status":
            return {"state": "unknown"}
        refuse("workspace_operation_unknown")
    if action in {"prepare", "resume"} and not verify_residual_descriptor(
        config, source, stem, journal, descriptor_path, allow_legacy=False
    ):
        refuse("workspace_operation_unknown")
    if journal["state"] in {"cleaning", "cleaned"}:
        verify_owned_units(config, journal, required=False)
        residual_descriptor = verify_residual_descriptor(
            config, source, stem, journal, descriptor_path
        )
        if not removed_units(config, units, native):
            if action == "status":
                return {"state": "unknown"}
            refuse("workspace_operation_unknown")
        if journal["state"] == "cleaning":
            journal["state"] = "cleaned"
            journal["failure_code"] = None
            write_private(journal_path, canonical(journal))
        if action in {"status", "stop", "cleanup"}:
            # Status proves execution absence only. Explicit continuation removes
            # a surviving, original private descriptor without replaying units.
            if action == "cleanup" and residual_descriptor:
                descriptor_path.unlink()
                write_private(journal_path, canonical(journal))
            return {"state": "cleaned"}
        refuse("workspace_environment_unavailable")
    if action == "status":
        verify_owned_units(config, journal)
        if journal["state"] in {"stopping", "stopped"}:
            if not native.inactive(units):
                return {"state": "unknown"}
            if journal["state"] == "stopping":
                journal["state"] = "stopped"
                journal["failure_code"] = None
                write_private(journal_path, canonical(journal))
            return {"state": "stopped"}
        states = {item["Id"]: item for item in native.states(units)}
        ready = (
            journal["state"] == "ready"
            and source.exists()
            and all(states[name].get("ActiveState") == "active" for name in (units[0], units[2]))
        )
        return {"state": "ready" if ready else "unknown"}
    if journal["state"] in {"preparing", "unknown", "stopping"}:
        # Read-only reconciliation can prove an existing start or completed stop.
        verify_owned_units(config, journal)
        if journal["state"] == "stopping" and action == "stop" and native.inactive(units):
            journal["state"] = "stopped"
            journal["failure_code"] = None
            write_private(journal_path, canonical(journal))
            return {"state": "stopped"}
        if action != "describe":
            refuse("workspace_operation_unknown")
        if journal["state"] == "stopping":
            if not native.inactive(units):
                refuse("workspace_operation_unknown")
            journal["state"] = "stopped"
            journal["failure_code"] = None
            write_private(journal_path, canonical(journal))
            refuse("workspace_environment_unavailable")
        descriptor = read_json(descriptor_path)
        native.ready(units, descriptor)
        journal["state"] = "ready"
        journal["failure_code"] = None
        write_private(journal_path, canonical(journal))
    if action == "describe":
        if journal["state"] != "ready":
            refuse("workspace_environment_unavailable")
        verify_owned_units(config, journal)
        if not verify_residual_descriptor(config, source, stem, journal, descriptor_path):
            refuse("workspace_operation_unknown")
        validate(config, source)
        descriptor = read_json(descriptor_path)
        if descriptor.get("source_root") != str(source) or descriptor.get(
            "exec_server_url"
        ) != "ws://127.0.0.1:" + str(journal["host_port"]):
            refuse()
        native.ready(units, descriptor)
        return descriptor
    if action == "prepare":
        if journal["state"] != "ready":
            refuse("workspace_operation_unknown")
        verify_owned_units(config, journal)
        native.ready(units, read_json(descriptor_path))
        return {"state": "ready"}
    if action == "resume":
        if journal["state"] == "ready":
            verify_owned_units(config, journal)
            native.ready(units, read_json(descriptor_path))
            return {"state": "ready"}
        if journal["state"] != "stopped":
            refuse("workspace_operation_unknown")
        verify_owned_units(config, journal)
        validate(config, source)
        if not native.inactive(units):
            refuse("workspace_operation_unknown")
        journal["state"] = "preparing"
        write_private(journal_path, canonical(journal))
        native.require("start", units[0], units[2])
        native.ready(units, read_json(descriptor_path))
        journal["state"] = "ready"
    elif action in {"stop", "cleanup"}:
        verify_owned_units(config, journal)
        if action == "stop" and journal["state"] == "stopped" and native.inactive(units):
            return {"state": "stopped"}
        if action == "cleanup":
            verify_residual_descriptor(config, source, stem, journal, descriptor_path)
        journal["state"] = "stopping"
        write_private(journal_path, canonical(journal))
        native.require("stop", units[2], units[1], units[0])
        if not native.inactive(units):
            refuse("workspace_operation_unknown")
        journal["state"] = "stopped"
        write_private(journal_path, canonical(journal))
        if action == "cleanup":
            verify_owned_units(config, journal)
            journal["state"] = "cleaning"
            write_private(journal_path, canonical(journal))
            if config.get("system_unit_broker"):
                native.remove()
            else:
                for name in units:
                    (config["unit_root"] / name).unlink()
            native.require("daemon-reload")
            journal["state"] = "cleaned"
            descriptor_path.unlink(missing_ok=True)
    else:
        refuse()
    write_private(journal_path, canonical(journal))
    return {"state": journal["state"]}


def acquire_lock(fd, action):
    # Describe performs the same exclusive, verified operation once after taking
    # the lock. Only lock contention may wait; lifecycle intents never replay.
    deadline = time.monotonic() + (3 if action == "describe" else 0)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                refuse("workspace_busy")
            time.sleep(min(0.05, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "action",
        choices=(
            "prepare",
            "resume",
            "stop",
            "cleanup",
            "describe",
            "status",
            "upgrade-budget",
        ),
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT:
            refuse()
        snapshot = json.loads(raw)
        lock = config["state_root"] / ".lock"
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
            ):
                refuse()
            acquire_lock(fd, args.action)
            result = manage(config, snapshot, args.action)
        finally:
            os.close(fd)
        output = canonical(result)
        if len(output) > LIMIT:
            refuse()
        print(output.decode())
    except (
        Refused,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ImportError,
        subprocess.SubprocessError,
    ) as error:
        code = str(error) if isinstance(error, Refused) else "workspace_environment_unavailable"
        print(
            json.dumps(
                {
                    "state": "unknown" if code == "workspace_operation_unknown" else "error",
                    "failure_code": code,
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
