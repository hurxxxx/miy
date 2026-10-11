"""Rename private environment keys; preserve credentials and resource locations."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values

ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z_0-9]*)(\s*=)", re.MULTILINE)


def renamed_key(key: str) -> str:
    for brand in ("MTY", "OWH", "OPEN_WORK_HUB"):
        for scope in ("VITE_", ""):
            prefix = f"{scope}{brand}_"
            if key.startswith(prefix):
                return f"{scope}MIY_" + key[len(prefix):].replace(
                    f"{brand}_DESKTOP", "MIY_DESKTOP"
                )
    return key


def rename_keys(text: str) -> tuple[str, int]:
    keys = [match[2] for match in ASSIGNMENT.finditer(text)]
    renamed = [renamed_key(key) for key in keys]
    if len(keys) != len(set(keys)) or len(renamed) != len(set(renamed)):
        raise ValueError("Resolve duplicate or colliding environment keys before migration.")
    mapping = {key: new for key, new in zip(keys, renamed) if key != new}
    # References inside values need explicit review; do not rewrite secret values.
    if any(re.search(r"\$\{?" + re.escape(key) + r"(?:\}|:|\b)", text) for key in mapping):
        raise ValueError("Review environment variable references before renaming keys.")
    updated = ASSIGNMENT.sub(lambda match: match[1] + renamed_key(match[2]) + match[3], text)
    before = dotenv_values(stream=StringIO(text), interpolate=False)
    after = dotenv_values(stream=StringIO(updated), interpolate=False)
    expected = {renamed_key(key): value for key, value in before.items()}
    if after != expected:
        raise ValueError("Migration would alter a value or multiline entry; review it manually.")
    return updated, len(mapping)


def migrate(path: Path, *, apply: bool) -> int:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("Environment file must be a regular non-symlink file with mode 0600.")
    if info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("Environment file must be owned by the current user without hard links.")
    with path.open(newline="") as stream:
        original = stream.read()
    updated, count = rename_keys(original)
    if not apply or not count:
        return count
    backup_fd, _backup = tempfile.mkstemp(prefix=path.name + ".backup-miy-", dir=path.parent)
    with os.fdopen(backup_fd, "w", newline="") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".miy-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        with path.open(newline="") as stream:
            if stream.read() != original:
                raise ValueError("Environment file changed during migration; retry after review.")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path(".env"))
    parser.add_argument("--apply", action="store_true", help="Write with a private recovery backup")
    args = parser.parse_args()
    try:
        count = migrate(args.file, apply=args.apply)
    except (OSError, ValueError) as error:
        # Value errors contain metadata only; never display configuration contents.
        parser.exit(1, f"Environment migration refused: {error}\n")
    print(f"{'Applied' if args.apply else 'Preview'}: {count} renamed keys; values preserved.")


if __name__ == "__main__":
    main()
