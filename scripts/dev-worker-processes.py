"""Read native worker Main identities from /proc without importing app code."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple


class InventoryUnavailable(ValueError):
    def __init__(self, reason: str, pid: int | None = None, stage: str | None = None):
        super().__init__(reason)
        self.pid = pid
        self.stage = stage


class Process(NamedTuple):
    pid: int
    ppid: int
    uid: int
    cwd: str = ""
    exe: str = ""
    argv: tuple[str, ...] = ()


ENTRIES = {
    "miy_worker.celery_app:celery_app": {"worker", "beat"},
    "miy_worker.first_party_platform:celery_app": {"worker"},
    "miy_worker.first_party_beat:celery_app": {"beat"},
    "miy_official_worker.runtime:celery_app": {"worker"},
}


def command(argv: tuple[str, ...], root: Path) -> tuple[str, str, str] | None:
    """Accept the existing native script/module entry, never shell command text."""
    if len(argv) >= 3 and argv[1:3] == ("-m", "celery"):
        arguments = list(argv[3:])
    elif len(argv) >= 2 and Path(argv[1]).name == "celery":
        script = Path(argv[1])
        if not script.is_absolute():
            script = root / "apps/worker" / script
        if script != root / "apps/worker/.venv/bin/celery":
            raise InventoryUnavailable("unknown_native_worker_script")
        arguments = list(argv[2:])
    else:
        if any("celery" in value for value in argv):
            raise InventoryUnavailable("unknown_native_worker_entry")
        return None
    if len(arguments) < 3 or arguments[0] not in ("-A", "--app"):
        raise InventoryUnavailable("unknown_native_worker_entry")
    entry, role = arguments[1:3]
    if entry not in ENTRIES or role not in ENTRIES[entry]:
        raise InventoryUnavailable("unknown_native_worker_entry")
    hostnames = []
    for index, value in enumerate(arguments[3:], start=3):
        if value in ("--hostname", "-n"):
            if index + 1 >= len(arguments):
                raise InventoryUnavailable("unknown_native_worker_hostname")
            hostnames.append(arguments[index + 1])
        elif value.startswith("--hostname="):
            hostnames.append(value.partition("=")[2])
    if len(hostnames) > 1 or any(
        not re.fullmatch(r"[A-Za-z0-9_.@%+-]+", value) for value in hostnames
    ):
        raise InventoryUnavailable("unknown_native_worker_hostname")
    return entry, role, hostnames[0] if hostnames else ""


def snapshot(root: Path, uid: int, proc: Path = Path("/proc")) -> dict[int, Process]:
    result = {}
    worker_cwd = str(root / "apps/worker")
    for directory in proc.iterdir():
        if not directory.name.isdecimal():
            continue
        stage = "status"
        try:
            status = dict(
                line.split(":", 1)
                for line in (directory / "status").read_text().splitlines()
                if ":" in line
            )
            if status["State"].split()[0] == "Z":
                continue
            pid, ppid, owner = (
                int(directory.name),
                int(status["PPid"]),
                int(status["Uid"].split()[0]),
            )
            process = Process(pid, ppid, owner)
            if owner == uid:
                # General user-manager processes may forbid cwd/exe access.
                # Only native Celery candidates need that identity metadata.
                stage = "argv"
                values = (directory / "cmdline").read_bytes().split(b"\0")
                if any(b"celery" in value for value in values):
                    stage = "exe"
                    exe = str((directory / "exe").resolve(strict=True))
                    if Path(exe).name.startswith("python"):
                        stage = "cwd"
                        cwd = str((directory / "cwd").resolve(strict=True))
                        if cwd == worker_cwd:
                            process = Process(
                                pid,
                                ppid,
                                owner,
                                cwd,
                                exe,
                                tuple(value.decode() for value in values if value),
                            )
            result[pid] = process
        except FileNotFoundError:
            # A process that disappeared is no signal candidate. A live owned
            # process with unreadable metadata cannot prove an empty inventory.
            if directory.exists():
                raise InventoryUnavailable(
                    "native_process_metadata_unavailable", int(directory.name), stage
                ) from None
        except (OSError, UnicodeError, KeyError, ValueError):
            raise InventoryUnavailable(
                "native_process_metadata_unavailable", int(directory.name), stage
            ) from None
    return result


def native_mains(
    processes: dict[int, Process], root: Path, uid: int, interpreter: str | None
) -> list[tuple[int, str, str, str]]:
    candidates = {}
    worker_cwd = str(root / "apps/worker")
    for pid, process in processes.items():
        if process.uid != uid or process.cwd != worker_cwd:
            continue
        if process.exe != interpreter:
            # Shell/uv wrappers can contain the whole worker command. They do
            # not own the native warm shutdown handler and are never signaled.
            if Path(process.exe).name.startswith("python") and any(
                "celery" in value for value in process.argv
            ):
                raise InventoryUnavailable("unknown_native_worker_interpreter")
            continue
        identity = command(process.argv, root)
        if identity is not None:
            candidates[pid] = identity
    result = []
    for pid, identity in candidates.items():
        parent = processes[pid].ppid
        visited = {pid}
        descendant = False
        while parent:
            if parent in visited or parent not in processes:
                raise InventoryUnavailable("native_process_ancestry_unavailable")
            visited.add(parent)
            if parent in candidates:
                if candidates[parent][:2] != identity[:2]:
                    raise InventoryUnavailable("nested_native_worker_owner")
                descendant = True
            parent = processes[parent].ppid
        if not descendant:
            result.append((pid, *identity))
    return sorted(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--role", choices=("worker", "beat"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    try:
        interpreter = str((root / "apps/worker/.venv/bin/python").resolve(strict=True))
    except FileNotFoundError:
        interpreter = None
    for pid, entry, role, hostname in native_mains(
        snapshot(root, os.getuid()), root, os.getuid(), interpreter
    ):
        if args.role and role != args.role:
            continue
        suffix = " --hostname=" + hostname if hostname else ""
        print(f"{pid} {entry} {role}{suffix}")


if __name__ == "__main__":
    try:
        main()
    except (InventoryUnavailable, OSError, ValueError):
        print(
            "Native worker identity unavailable; development lifecycle HOLD.",
            file=sys.stderr,
        )
        sys.exit(1)
