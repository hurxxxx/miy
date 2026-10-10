"""Read/write the single owner's last selected development queue namespace.

This is restart configuration, not empty-broker or drain evidence. The launcher
writes a changed mode only after its existing native consumer drain succeeds.
"""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import stat
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
NAME = "dev-topology"
MODES = {"legacy", "first-party"}


def read_selection(directory: int) -> tuple[str, tuple[int, int] | None]:
    try:
        descriptor = os.open(
            NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
    except FileNotFoundError:
        return "unselected", None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 1 <= info.st_size <= 32
        ):
            raise ValueError("dev_topology_invalid")
        raw = os.read(descriptor, 33)
        if raw not in {b"legacy\n", b"first-party\n"}:
            raise ValueError("dev_topology_invalid")
        return raw.decode().strip(), (info.st_dev, info.st_ino)
    finally:
        os.close(descriptor)


def select_mode(directory: int, *, mode: str, expected: str) -> None:
    fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        previous = read_selection(directory)
        if previous[0] != expected:
            raise ValueError("dev_topology_changed")
        temporary = NAME + "." + uuid4().hex
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        try:
            try:
                os.fchmod(descriptor, 0o600)
                data = (mode + "\n").encode()
                if os.write(descriptor, data) != len(data):
                    raise OSError("dev_topology_write_incomplete")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if read_selection(directory) != previous:
                raise ValueError("dev_topology_changed")
            os.replace(temporary, NAME, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    finally:
        fcntl.flock(directory, fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--read", action="store_true")
    action.add_argument("--select", choices=sorted(MODES))
    parser.add_argument("--expect", choices=sorted(MODES | {"unselected"}))
    args = parser.parse_args()
    if args.select and args.expect is None:
        parser.error("--select requires the launcher's previous --expect mode")
    runtime = ROOT / ".runtime"
    if not runtime.exists():
        runtime.mkdir(mode=0o700)
    directory = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError("dev_topology_directory_invalid")
        if args.read:
            print(read_selection(directory)[0])
        else:
            select_mode(directory, mode=args.select, expected=args.expect)
    finally:
        os.close(directory)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print(
            "Development topology state is unavailable or invalid; startup HOLD.", file=sys.stderr
        )
        sys.exit(1)
