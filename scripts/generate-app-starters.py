#!/usr/bin/env python3
"""Package the canonical app starters and SDK for the standalone Workbench."""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("apps/codex-console-api/src/codex_console/app_starters.generated.json")
IGNORED = {"__pycache__", ".pytest_cache", "node_modules", "dist", ".venv"}
MAX_BYTES = 2 * 1024 * 1024


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )


def regular_text(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Starter inputs must be independent regular files")
        value = stream.read(MAX_BYTES + 1)
    if len(value) > MAX_BYTES:
        raise ValueError("Starter input too large")
    return value.decode("utf-8")


def source_files(root):
    if root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError("Starter roots must be canonical directories")
    result = {}
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name not in IGNORED)
        for name in directories:
            if (Path(current) / name).is_symlink():
                raise ValueError("Starter directory links are forbidden")
        for name in sorted(names):
            if name.endswith((".pyc", ".pyo")):
                continue
            path = Path(current) / name
            relative = path.relative_to(root)
            if any(
                part.startswith((".env", ".auth_info")) or part == ".git" for part in relative.parts
            ):
                raise ValueError("Private files cannot enter starter resources")
            result[relative.as_posix()] = regular_text(path)
    return result


def generate(root):
    root = root.resolve(strict=True)
    basic = source_files(root / "templates/independent-app")
    basic["AGENTS.md"] = basic.pop("AGENTS.md.template")
    sdk_package = regular_text(root / "packages/app-sdk/package.json")
    basic["vendor/miy-app-sdk/package.json"] = sdk_package
    for name, content in source_files(root / "packages/app-sdk/src").items():
        basic["vendor/miy-app-sdk/src/" + name] = content
    data = {**basic, **source_files(root / "templates/independent-app-data")}
    manifest = json.loads(data["app.manifest.json"])
    manifest.update(
        runtime_profile="web-api-postgres-v1",
        requested_permissions=["identity:read", "data:read", "data:write"],
    )
    data["app.manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    templates = {}
    for key, name, entries in (
        ("basic", "Web app", basic),
        ("private-notes", "Private notes with data", data),
    ):
        if len(entries) > 256 or sum(len(value.encode()) for value in entries.values()) > MAX_BYTES:
            raise ValueError("Starter bundle exceeds its fixed bounds")
        templates[key] = {
            "name": name,
            "runtime_profile": json.loads(entries["app.manifest.json"])["runtime_profile"],
            "files": dict(sorted(entries.items())),
        }
    value = {
        "schema_version": 1,
        "sdk_version": json.loads(sdk_package)["version"],
        "templates": templates,
    }
    return {**value, "bundle_digest": digest(value)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(generate(ROOT), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    destination = ROOT / OUTPUT
    if args.check:
        if not destination.is_file() or destination.read_text() != expected:
            parser.exit(
                1, "Workbench starter bundle is stale; run scripts/generate-app-starters.py.\n"
            )
    else:
        destination.write_text(expected)
    print("Workbench starter bundle matches canonical templates and SDK.")


if __name__ == "__main__":
    main()
