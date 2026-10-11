#!/usr/bin/python3 -I
"""Root-owned fixed system-unit broker; never import or execute user Python.

Install this file and its configuration as root. The fixed entrypoint takes no
arguments; a bounded public request is its only input. Capability tokens remain
in the unprivileged Workbench descriptor, and only their SHA256 enters units.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

CONFIG = Path("/etc/miy/workbench-executors.json")
LIMIT = 128 * 1024
SUFFIXES = (".service", "-proxy.service", "-proxy.socket")
FIELDS = {
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
PROPERTIES = "Id,LoadState,ActiveState,SubState,MainPID,ControlPID,FragmentPath"


class Refused(ValueError):
    pass


def refuse():
    raise Refused("workspace_operation_unknown")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def directory(path, owners=(0,), *, private=False):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        refuse()
    for item in (*reversed(path.parents), path):
        info = item.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in owners
            or info.st_mode & 0o022
            and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
        ):
            refuse()
    if private and path.stat().st_mode & 0o077:
        refuse()
    return path


def read(path, *, private=False, maximum=LIMIT):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != 0
            or info.st_mode & 0o022
            or private
            and info.st_mode & 0o077
            or info.st_size > maximum
        ):
            refuse()
        raw = stream.read(maximum + 1)
        if len(raw) != info.st_size:
            refuse()
        return raw


def create(path, raw, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def save_receipt(path, receipt):
    """Persist owned intent before deleting units, including the parent directory."""
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".next")
    try:
        create(temporary, canonical(receipt))
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def config(path=CONFIG):
    directory(path.parent)
    value = json.loads(read(path, private=True))
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
        "template_root",
        "template_sha256",
        "systemctl_path",
        "socket_proxyd_path",
        "native_sha256",
        "bwrap_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value["schema_version"] != 1
    ):
        refuse()
    if (
        type(value["executor_uid"]) is not int
        or value["executor_uid"] <= 0
        or type(value["executor_gid"]) is not int
        or value["executor_gid"] <= 0
        or set(value["template_sha256"]) != set(SUFFIXES)
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
            for v in (
                *value["template_sha256"].values(),
                value["native_sha256"],
                value["bwrap_sha256"],
            )
        )
    ):
        refuse()
    owners = (0, value["executor_uid"])
    for name in (
        "repository_root",
        "worktree_root",
        "state_root",
        "vendor_root",
        "sdk_root",
        "unit_root",
        "template_root",
    ):
        value[name] = directory(
            value[name],
            owners if name in {"repository_root", "worktree_root"} else (0,),
            private=name == "state_root",
        )
    if value["unit_root"] != Path("/etc/systemd/system"):
        refuse()
    ports = value["host_ports"]
    if (
        not isinstance(ports, list)
        or not 1 <= len(ports) <= 32
        or any(type(p) is not int or not 1024 <= p <= 65535 for p in ports)
        or len(set(ports)) != len(ports)
        or type(value["private_port"]) is not int
        or not 1024 <= value["private_port"] <= 65535
    ):
        refuse()
    for name, exact in (
        ("systemctl_path", "/usr/bin/systemctl"),
        ("socket_proxyd_path", "/usr/lib/systemd/systemd-socket-proxyd"),
    ):
        if value[name] != exact:
            refuse()
        value[name] = Path(exact)
        directory(value[name].parent)
        read(value[name], maximum=32 * 1024 * 1024)
    for relative, expected in (
        ("bin/codex", value["native_sha256"]),
        ("codex-resources/bwrap", value["bwrap_sha256"]),
    ):
        path = value["vendor_root"] / relative
        directory(path.parent)
        if digest(read(path, maximum=512 * 1024 * 1024)) != expected:
            refuse()
    return value


def identity(config, snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != FIELDS:
        refuse()
    value = UUID(snapshot["id"])
    if (
        str(value) != snapshot["id"]
        or snapshot["profile_id"] != "app"
        or not isinstance(snapshot["app_id"], str)
        or len(snapshot["app_id"]) > 100
        or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", snapshot["app_id"])
        or not isinstance(snapshot["branch"], str)
        or not re.fullmatch(r"feature/[a-zA-Z0-9/_-]+", snapshot["branch"])
        or any(
            not isinstance(snapshot[k], str)
            or not re.fullmatch(r"[0-9a-f]{40}", snapshot[k])
            for k in ("base_revision", "source_revision")
        )
    ):
        refuse()
    source = config["worktree_root"] / str(value) / "personal-apps" / snapshot["app_id"]
    if (
        snapshot["repository_root"] != str(config["repository_root"])
        or snapshot["worktree_path"] != str(config["worktree_root"] / str(value))
        or snapshot["app_directory"] != "personal-apps/" + snapshot["app_id"]
    ):
        refuse()
    binding = digest(canonical({k: snapshot[k] for k in FIELDS - {"source_revision"}}))
    return source, binding, "miy-wb-" + value.hex


def empty_git_mask(source, item, owner):
    if item != source / ".git":
        return False
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(
                ".git", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=source_fd
            )
        finally:
            os.close(source_fd)
        try:
            info = os.fstat(fd)
            return (
                info.st_uid == owner and not info.st_mode & 0o022 and not os.listdir(fd)
            )
        finally:
            os.close(fd)
    except OSError:
        return False


def source_guard(config, source):
    directory(source, (0, config["executor_uid"]))
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
                or info.st_uid not in (0, config["executor_uid"])
                or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
            ):
                refuse()


def render(config, source, stem, port, token_sha256, *, legacy_budget=False):
    if (
        type(port) is not int
        or port not in config["host_ports"]
        or not isinstance(token_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", token_sha256)
    ):
        refuse()
    values = {
        "SOURCE_ROOT": str(source),
        "VENDOR_ROOT": str(config["vendor_root"]),
        "SDK_ROOT": str(config["sdk_root"]),
        "UNIT_STEM": stem,
        "EXECUTOR_UID": str(config["executor_uid"]),
        "EXECUTOR_GID": str(config["executor_gid"]),
        "HOST_PORT": str(port),
        "PRIVATE_PORT": str(config["private_port"]),
        "TOKEN_SHA256": token_sha256,
    }
    if any(
        not re.fullmatch(r"[A-Za-z0-9/._+@-]+", v) or re.search(r"@[A-Z_]+@", v)
        for v in values.values()
    ):
        refuse()
    output = {}
    for suffix in SUFFIXES:
        raw = read(
            config["template_root"] / ("miy-app-sdk-managed" + suffix + ".example")
        )
        if digest(raw) != config["template_sha256"][suffix]:
            refuse()
        text = raw.decode()
        if suffix == ".service":
            if text.count("\nTasksMax=256\n") != 1:
                refuse()
            if legacy_budget:
                text = text.replace("\nTasksMax=256\n", "\nTasksMax=64\n")
        text = text.replace(
            "[Service]\n", "[Service]\nUser=@EXECUTOR_UID@\nGroup=@EXECUTOR_GID@\n"
        )
        for key, value in values.items():
            text = text.replace("@" + key + "@", value)
        if re.search(r"@[A-Z_]+@", text):
            refuse()
        output[stem + suffix] = text.encode()
    return output


class Native:
    def __init__(self, config):
        self.config = config

    def call(self, *args):
        result = subprocess.run(
            [str(self.config["systemctl_path"]), *args],
            env={"PATH": os.defpath},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        if result.returncode or len(result.stdout) > LIMIT:
            refuse()
        return result.stdout

    def states(self, units):
        raw = self.call("show", "--property=" + PROPERTIES, *units)
        output = [
            dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            for block in raw.decode().strip().split("\n\n")
        ]
        if len(output) != 3 or {s.get("Id") for s in output} != set(units):
            refuse()
        for state in output:
            if state.get("LoadState") != "not-found" and state.get(
                "FragmentPath"
            ) != str(self.config["unit_root"] / state["Id"]):
                refuse()
        return output


def inactive(states):
    return all(
        s.get("ActiveState") in {"inactive", "failed"}
        and s.get("MainPID", "0") == "0"
        and s.get("ControlPID", "0") == "0"
        for s in states
    )


def owned(config, receipt, required=True):
    for name, expected in receipt["units"].items():
        path = config["unit_root"] / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            if required:
                refuse()
            continue
        if not stat.S_ISREG(info.st_mode):
            refuse()
        if digest(read(path)) != expected:
            refuse()


def units_absent(config, units):
    for name in units:
        try:
            (config["unit_root"] / name).lstat()
        except FileNotFoundError:
            continue
        return False
    return True


def receipt_budget(config, source, stem, receipt):
    """Classify only the original owned unit's exact current/legacy rendering."""
    raw = read(config["unit_root"] / (stem + ".service"))
    tokens = re.findall(rb"--ws-token-sha256 ([0-9a-f]{64})\n", raw)
    if len(tokens) != 1:
        refuse()
    for legacy in (False, True):
        rendered = render(
            config,
            source,
            stem,
            receipt["host_port"],
            tokens[0].decode(),
            legacy_budget=legacy,
        )
        if {name: digest(value) for name, value in rendered.items()} == receipt[
            "units"
        ]:
            return 64 if legacy else 256
    refuse()


def quiescent(config, units, native):
    states = native.states(units)
    return (
        len(states) == len(units)
        and {s.get("Id") for s in states} == set(units)
        and all(
            s.get("ActiveState") == "inactive"
            and s.get("ControlPID") == "0"
            and s.get("MainPID", "0" if s["Id"].endswith(".socket") else None) == "0"
            and s.get("FragmentPath") == str(config["unit_root"] / s["Id"])
            for s in states
        )
    )


def owned_upgrade(config, receipt):
    intent = receipt.get("budget_upgrade")
    if (
        not isinstance(intent, dict)
        or set(intent) != {"from_units", "to_units"}
        or intent["from_units"] != receipt["units"]
        or set(intent["to_units"]) != set(receipt["units"])
    ):
        refuse()
    for name, expected in receipt["units"].items():
        path = config["unit_root"] / name
        if not stat.S_ISREG(path.lstat().st_mode):
            refuse()
        if digest(read(path)) not in {expected, intent["to_units"][name]}:
            refuse()


def replace_backend(config, stem, raw):
    path = config["unit_root"] / (stem + ".service")
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".next")
    try:
        create(temporary, raw, 0o644)
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def upgrade_budget(config, request, source, stem, receipt, receipt_path, native):
    if receipt is None or receipt.get("state") not in {"owned", "upgrading"}:
        refuse()
    rendered = render(
        config, source, stem, receipt["host_port"], request["token_sha256"]
    )
    target = {name: digest(raw) for name, raw in rendered.items()}
    legacy = render(
        config,
        source,
        stem,
        receipt["host_port"],
        request["token_sha256"],
        legacy_budget=True,
    )
    original = {name: digest(raw) for name, raw in legacy.items()}
    intent = {"from_units": original, "to_units": target}
    if request["units"] != target:
        refuse()
    completed = receipt["state"] == "owned" and receipt["units"] == target
    if completed:
        if receipt.get("budget_upgrade") != intent:
            refuse()
        owned(config, receipt)
    elif receipt["units"] != original or (
        receipt["state"] == "upgrading" and receipt.get("budget_upgrade") != intent
    ):
        refuse()
    elif receipt["state"] == "upgrading":
        owned_upgrade(config, receipt)
    else:
        owned(config, receipt)
    source_guard(config, source)
    if not quiescent(config, list(rendered), native):
        refuse()
    if completed:
        return {"units": target}
    if receipt["state"] == "owned":
        receipt["state"] = "upgrading"
        receipt["budget_upgrade"] = intent
        save_receipt(receipt_path, receipt)
    backend = stem + ".service"
    if digest(read(config["unit_root"] / backend)) == original[backend]:
        replace_backend(config, stem, rendered[backend])
    native.call("daemon-reload")
    owned(config, {"units": target})
    if not quiescent(config, list(rendered), native):
        refuse()
    receipt["units"] = target
    receipt["state"] = "owned"
    save_receipt(receipt_path, receipt)
    return {"units": target}


def handle(config, request, *, native=None):
    if not isinstance(request, dict) or request.get("action") not in {
        "install",
        "query",
        "start",
        "stop",
        "cleanup",
        "upgrade-budget",
    }:
        refuse()
    action = request["action"]
    expected_fields = {"action", "snapshot"}
    if action == "install":
        expected_fields |= {"host_port", "token_sha256", "units"}
    elif action == "upgrade-budget":
        expected_fields |= {"token_sha256", "units"}
    if set(request) != expected_fields:
        refuse()
    source, binding, stem = identity(config, request["snapshot"])
    units = [stem + suffix for suffix in SUFFIXES]
    native = native or Native(config)
    receipt_path = config["state_root"] / (stem + ".json")
    receipt = (
        json.loads(read(receipt_path, private=True)) if receipt_path.exists() else None
    )
    if receipt is not None and (
        receipt.get("binding") != binding or set(receipt.get("units", {})) != set(units)
    ):
        refuse()
    if action == "upgrade-budget":
        return upgrade_budget(
            config, request, source, stem, receipt, receipt_path, native
        )
    if action == "install":
        if receipt is not None or any(
            s.get("LoadState") != "not-found" for s in native.states(units)
        ):
            refuse()
        source_guard(config, source)
        rendered = render(
            config, source, stem, request["host_port"], request["token_sha256"]
        )
        hashes = {name: digest(raw) for name, raw in rendered.items()}
        if request["units"] != hashes or any(
            (config["unit_root"] / name).exists() for name in units
        ):
            refuse()
        for path in config["state_root"].glob("miy-wb-*.json"):
            existing = json.loads(read(path, private=True))
            if (
                existing.get("state") != "cleaned"
                and existing.get("host_port") == request["host_port"]
            ):
                refuse()
        receipt = {
            "binding": binding,
            "units": hashes,
            "host_port": request["host_port"],
            "state": "owned",
        }
        create(receipt_path, canonical(receipt))
        for name, raw in rendered.items():
            create(config["unit_root"] / name, raw, 0o644)
        native.call("daemon-reload")
        return {"units": hashes}
    if receipt is None:
        if action != "query":
            refuse()
        return {"states": native.states(units)}
    state = receipt.get("state")
    if state == "upgrading":
        if action != "query":
            refuse()
        owned_upgrade(config, receipt)
        return {"states": native.states(units)}
    if state not in {"owned", "cleaning", "cleaned"}:
        refuse()
    owned(config, receipt, required=state == "owned")
    budget = receipt_budget(config, source, stem, receipt) if state == "owned" else None
    if action == "query":
        states = native.states(units)
        if state in {"cleaning", "cleaned"}:
            # Only reconcile a persisted cleanup intent. Query never resends a
            # stop, reload or deletion, and partial removal remains uncertain.
            if (
                not units_absent(config, units)
                or not inactive(states)
                or any(
                    s.get("LoadState") != "not-found"
                    or s.get("ActiveState") != "inactive"
                    or s.get("ControlPID") != "0"
                    or s.get("MainPID", "0" if s["Id"].endswith(".socket") else None)
                    != "0"
                    for s in states
                )
            ):
                refuse()
            if state == "cleaning":
                receipt["state"] = "cleaned"
                save_receipt(receipt_path, receipt)
        return {"states": states}
    if state != "owned":
        refuse()
    if action == "start":
        if budget != 256:
            refuse()
        source_guard(config, source)
        if not inactive(native.states(units)):
            refuse()
        native.call("start", units[0], units[2])
    elif action == "stop":
        native.call("stop", units[2], units[1], units[0])
    elif action == "cleanup":
        if not inactive(native.states(units)):
            refuse()
        receipt["state"] = "cleaning"
        save_receipt(receipt_path, receipt)
        for name in units:
            (config["unit_root"] / name).unlink()
        native.call("daemon-reload")
        receipt["state"] = "cleaned"
        save_receipt(receipt_path, receipt)
    return {"states": native.states(units)}


def main():
    try:
        if len(sys.argv) != 1 or os.getuid() != 0:
            refuse()
        value = config()
        raw = sys.stdin.buffer.read(LIMIT + 1)
        if len(raw) > LIMIT:
            refuse()
        request = json.loads(raw)
        lock = value["state_root"] / ".lock"
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or info.st_nlink != 1
                or info.st_mode & 0o077
            ):
                refuse()
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            output = canonical(handle(value, request))
        finally:
            os.close(fd)
        if len(output) > LIMIT:
            refuse()
        print(output.decode())
        return 0
    except (
        Refused,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ):
        print('{"state":"unknown","failure_code":"workspace_operation_unknown"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
