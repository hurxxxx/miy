#!/usr/bin/env python3
"""Offline path adapter for a copied Codex 0.162.1 home; never use on a running home.

The public resume API rejects a relocated paginated rollout as a stale path.
Only state_5.threads.rollout_path changes. History, IDs and rollout bytes stay intact.
"""

import argparse
import json
import os
import sqlite3
import stat
import subprocess
from pathlib import Path


def relocate(home, previous_home, backup):
    if (
        not home.is_absolute()
        or home.resolve() != home
        or not previous_home.is_absolute()
    ):
        raise ValueError("Use canonical absolute homes")
    database = home / "state_5.sqlite"
    info = database.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
    ):
        raise ValueError("Use a private database copy owned by the service user")
    if not backup.is_absolute() or backup.parent.resolve() != backup.parent:
        raise ValueError("Use an absolute backup in a canonical private directory")
    if (
        backup.parent.stat().st_mode & 0o077
        or backup.parent.stat().st_uid != os.getuid()
    ):
        raise ValueError("Use a private backup directory")
    with sqlite3.connect(database, timeout=0) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Database integrity check failed")
        rows = connection.execute(
            "SELECT id, rollout_path FROM threads ORDER BY id"
        ).fetchall()
        updates = []
        for thread_id, old in rows:
            relative = Path(old).relative_to(previous_home)
            if (
                relative.parts[0] not in ("sessions", "archived_sessions")
                or ".." in relative.parts
            ):
                raise ValueError("Unexpected rollout location")
            target = home / relative
            if target.resolve() != target or not target.is_file():
                raise ValueError("A copied rollout is missing or is a symlink")
            with target.open() as stream:
                metadata = json.loads(stream.readline(1024 * 1024))
            if (
                metadata.get("type") != "session_meta"
                or metadata["payload"].get("id") != thread_id
            ):
                raise ValueError("Copied rollout identity does not match")
            updates.append((str(target), thread_id, old))
        # Preserve a complete consistent backup before touching the copied index.
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with (
            sqlite3.connect(database, timeout=0) as source,
            sqlite3.connect(backup) as saved,
        ):
            source.backup(saved)
        before = connection.total_changes
        connection.executemany(
            "UPDATE threads SET rollout_path=? WHERE id=? AND rollout_path=?", updates
        )
        if connection.total_changes - before != len(updates):
            raise ValueError("Thread index changed during relocation")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Relocated database integrity check failed")
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--previous-home", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--codex-binary", type=Path, required=True)
    parser.add_argument("--services-stopped", action="store_true", required=True)
    args = parser.parse_args()
    version = subprocess.check_output(
        [str(args.codex_binary), "--version"], text=True
    ).strip()
    if version != "codex-cli 0.162.1":
        parser.error("This offline adapter is verified only with Codex 0.162.1")
    count = relocate(args.home, args.previous_home, args.backup)
    print(json.dumps({"relocated_threads": count}))


if __name__ == "__main__":
    main()
