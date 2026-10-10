#!/usr/bin/env python3
"""Verify an offline Core SDK artifact/cache; never execute or acquire packages."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import re
import stat
import struct
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "ops/codex-console/executor/sdk-toolchain-pin.json"
MAX_FILES = 20000
MAX_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")
PATH = re.compile(r"[A-Za-z0-9._/@+-]+")
COMPONENTS = frozenset(
    {
        "node",
        "python",
        "pnpm",
        "node_modules",
        "python-packages",
        "runtime",
        "sdk",
        "profile",
        "bin",
    }
)
SOURCE_INPUTS = frozenset(
    {
        "ops/codex-console/executor/sdk-node-lock.yaml",
        "ops/codex-console/executor/sdk-python-requirements.txt",
        "templates/independent-app/package.json",
        "templates/independent-app/pyproject.toml",
        "packages/app-sdk/package.json",
        "packages/app-sdk/README.md",
        "packages/app-sdk/src/index.mjs",
        "packages/app-sdk/src/index.test.mjs",
        "packages/app-sdk/src/file-picker.mjs",
    }
)
SDK_V2 = "miy-native-sdk-20261009-v2"
VITE_SCRATCH = {
    "path": "node_modules/.vite-temp",
    "bytes": 16777216,
    "mount": "tmpfs",
    "artifact_state": "empty_directory",
}


class ToolchainRefused(ValueError):
    """Stable refusal; callers must not log artifact contents or raw exceptions."""


def refuse(code: str):
    raise ToolchainRefused(code)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def is_digest(value) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not PATH.fullmatch(value):
        refuse("unsafe_member_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        refuse("unsafe_member_path")
    if path.parts[0] not in COMPONENTS:
        refuse("unexpected_component")
    return value


def regular_bytes(path: Path, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > maximum
        ):
            refuse("unsafe_regular_file")
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        refuse("file_budget")
    return value


def load_pin(path: Path = PIN) -> dict:
    try:
        pin = json.loads(regular_bytes(path, 2 * 1024 * 1024))
    except (UnicodeError, json.JSONDecodeError):
        refuse("invalid_pin_json")
    if not isinstance(pin, dict) or pin.get("schema_version") != 1:
        refuse("unsupported_pin_schema")
    if (
        pin.get("target") != "x86_64-unknown-linux-gnu"
        or pin.get("native_version") != "0.160.1"
    ):
        refuse("unsupported_target_or_native")
    if pin.get("versions") != {
        "node": "22.23.3",
        "python": "3.12.14",
        "pnpm": "10.34.5",
    }:
        refuse("unsupported_versions")
    if pin.get("toolchain_id") == SDK_V2 and pin.get("runtime_scratch") != VITE_SCRATCH:
        refuse("unsupported_runtime_scratch")
    if (
        not isinstance(pin.get("components"), dict)
        or set(pin["components"]) != COMPONENTS
    ):
        refuse("incomplete_components")
    artifact = pin.get("bundle", {})
    if not isinstance(artifact, dict):
        refuse("invalid_artifact_record")
    if artifact.get("format") != "tar.xz" or not is_digest(artifact.get("sha256")):
        refuse("incomplete_artifact_digest")
    for row in [artifact, *pin["components"].values()]:
        if not isinstance(row, dict):
            refuse("invalid_inventory_record")
        if not is_digest(row.get("inventory_sha256")):
            refuse("incomplete_inventory_digest")
        if type(row.get("members")) is not int or not 0 < row["members"] <= MAX_FILES:
            refuse("inventory_count_budget")
        if (
            type(row.get("regular_bytes")) is not int
            or not 0 <= row["regular_bytes"] <= MAX_BYTES
        ):
            refuse("inventory_byte_budget")
    if type(artifact.get("bytes")) is not int or not 0 < artifact["bytes"] <= MAX_BYTES:
        refuse("artifact_byte_budget")
    if not isinstance(pin.get("elf"), list) or not pin["elf"]:
        refuse("incomplete_elf_inventory")
    inputs = pin.get("source_inputs")
    if not isinstance(inputs, dict) or set(inputs) != SOURCE_INPUTS:
        refuse("incomplete_owned_source_inputs")
    for name, expected in inputs.items():
        if (
            not is_digest(expected)
            or hashlib.sha256(regular_bytes(ROOT / name, 2 * 1024 * 1024)).hexdigest()
            != expected
        ):
            refuse("owned_source_input_mismatch")
    return pin


def _file_record(name: str, mode: int, value: bytes) -> dict:
    if len(value) > MAX_FILE_BYTES:
        refuse("file_budget")
    return {
        "path": name,
        "kind": "file",
        "mode": mode,
        "bytes": len(value),
        "sha256": hashlib.sha256(value).hexdigest(),
    }


def check_records(records: list[dict]) -> list[dict]:
    if len(records) > MAX_FILES:
        refuse("inventory_count_budget")
    records = sorted(records, key=lambda r: r["path"])
    bypath = {}
    total = 0
    for row in records:
        name = relative_path(row["path"])
        if name in bypath:
            refuse("duplicate_member")
        if row["kind"] == "file":
            if row["mode"] not in {0o444, 0o555}:
                refuse("mutable_or_special_mode")
            total += row["bytes"]
        elif row["kind"] == "directory":
            if row["mode"] != 0o555:
                refuse("mutable_or_special_mode")
        elif row["kind"] == "symlink":
            link = row["target"]
            if (
                not isinstance(link, str)
                or not PATH.fullmatch(link)
                or link.startswith("/")
            ):
                refuse("unsafe_symlink")
            normalized = posixpath.normpath(
                posixpath.join(posixpath.dirname(name), link)
            )
            if normalized == ".." or normalized.startswith("../"):
                refuse("escaping_symlink")
        else:
            refuse("unsupported_member_type")
        bypath[name] = row
    if total > MAX_BYTES:
        refuse("inventory_byte_budget")
    for name, row in bypath.items():
        parent = PurePosixPath(name).parent.as_posix()
        if parent != "." and (
            parent not in bypath or bypath[parent]["kind"] != "directory"
        ):
            refuse("missing_or_linked_parent")
        if row["kind"] != "symlink":
            continue
        current = name
        seen = set()
        for _ in range(64):
            parts = current.split("/")
            changed = False
            for length in range(1, len(parts) + 1):
                prefix = "/".join(parts[:length])
                candidate = bypath.get(prefix)
                if candidate is None:
                    refuse("dangling_symlink")
                if candidate["kind"] == "symlink":
                    if prefix in seen:
                        refuse("symlink_cycle")
                    seen.add(prefix)
                    current = posixpath.normpath(
                        posixpath.join(
                            posixpath.dirname(prefix),
                            candidate["target"],
                            *parts[length:],
                        )
                    )
                    changed = True
                    break
            if not changed:
                break
        else:
            refuse("symlink_depth")
    return records


def summary(records: list[dict]) -> dict:
    return {
        "inventory_sha256": digest(records),
        "members": len(records),
        "regular_bytes": sum(r.get("bytes", 0) for r in records),
    }


def verify_inventory(records: list[dict], pin: dict):
    records = check_records(records)
    if summary(records) != {key: pin["bundle"][key] for key in summary(records)}:
        refuse("bundle_inventory_mismatch")
    for name in COMPONENTS:
        selected = [r for r in records if r["path"].split("/")[0] == name]
        if summary(selected) != pin["components"][name]:
            refuse("component_inventory_mismatch")
    if pin.get("toolchain_id") == SDK_V2:
        if pin.get("runtime_scratch") != VITE_SCRATCH:
            refuse("unsupported_runtime_scratch")
        target = VITE_SCRATCH["path"]
        if {"path": target, "kind": "directory", "mode": 0o555} not in records or any(
            row["path"].startswith(target + "/") for row in records
        ):
            refuse("vite_scratch_not_empty_directory")


def verify_source_mounts(source: Path, pin: dict):
    """Check reserved targets, four functional SDK files and an optional pinned README."""
    if not source.is_absolute() or source.resolve() != source:
        refuse("noncanonical_source_root")
    rootfd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def open_directory(parts):
        fd = os.dup(rootfd)
        try:
            for name in parts:
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                os.close(fd)
                fd = child
                if os.fstat(fd).st_mode & 0o022:
                    refuse("source_mount_target_mutable_by_other_users")
            return fd
        except BaseException:
            os.close(fd)
            raise

    try:
        if os.fstat(rootfd).st_mode & 0o022:
            refuse("source_mount_target_mutable_by_other_users")
        for parts in [(".git",), ("node_modules",)]:
            fd = open_directory(parts)
            try:
                if parts == ("node_modules",) and os.listdir(fd):
                    refuse("source_dependencies_target_not_empty")
            finally:
                os.close(fd)
        sdkfd = open_directory(("vendor", "miy-app-sdk"))
        try:
            sdk_names = set(os.listdir(sdkfd))
            if sdk_names not in (
                {"package.json", "src"},
                {"package.json", "README.md", "src"},
            ):
                refuse("source_sdk_inventory_mismatch")
            srcfd = os.open(
                "src", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=sdkfd
            )
            try:
                if os.fstat(srcfd).st_mode & 0o022:
                    refuse("source_mount_target_mutable_by_other_users")
                if set(os.listdir(srcfd)) != {
                    "index.mjs",
                    "file-picker.mjs",
                    "index.test.mjs",
                }:
                    refuse("source_sdk_inventory_mismatch")
                for parentfd, names, prefix in (
                    (
                        sdkfd,
                        ["package.json"]
                        + (["README.md"] if "README.md" in sdk_names else []),
                        "",
                    ),
                    (srcfd, ["index.mjs", "file-picker.mjs", "index.test.mjs"], "src/"),
                ):
                    for name in names:
                        fd = os.open(
                            name,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=parentfd,
                        )
                        with os.fdopen(fd, "rb") as stream:
                            info = os.fstat(stream.fileno())
                            if (
                                not stat.S_ISREG(info.st_mode)
                                or info.st_nlink != 1
                                or info.st_mode & 0o022
                                or info.st_size > 2 * 1024**2
                            ):
                                refuse("source_sdk_file_refused")
                            raw = stream.read(info.st_size + 1)
                        expected = pin["source_inputs"][
                            "packages/app-sdk/" + prefix + name
                        ]
                        if (
                            len(raw) != info.st_size
                            or hashlib.sha256(raw).hexdigest() != expected
                        ):
                            refuse("source_sdk_input_mismatch")
            finally:
                os.close(srcfd)
        finally:
            os.close(sdkfd)
    finally:
        os.close(rootfd)


def scan_tree(
    root: Path, *, owner: int | None = None
) -> tuple[list[dict], dict[str, bytes]]:
    records = []
    elf = {}
    total = 0
    rootfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def walk(fd, prefix):
        nonlocal total
        for name in sorted(os.listdir(fd)):
            path = relative_path(prefix + name)
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if owner is not None and info.st_uid != owner:
                refuse("wrong_cache_owner")
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                records.append({"path": path, "kind": "directory", "mode": mode})
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                try:
                    walk(child, path + "/")
                finally:
                    os.close(child)
            elif stat.S_ISLNK(info.st_mode):
                records.append(
                    {
                        "path": path,
                        "kind": "symlink",
                        "target": os.readlink(name, dir_fd=fd),
                    }
                )
            elif stat.S_ISREG(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                )
                with os.fdopen(child, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if opened.st_nlink != 1 or opened.st_size > MAX_FILE_BYTES:
                        refuse("unsafe_regular_file")
                    if total + opened.st_size > MAX_BYTES:
                        refuse("inventory_byte_budget")
                    if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        refuse("cache_changed_during_read")
                    value = stream.read(opened.st_size + 1)
                    if len(value) != opened.st_size:
                        refuse("cache_changed_during_read")
                records.append(_file_record(path, mode, value))
                total += len(value)
                if value.startswith(b"\x7fELF"):
                    elf[path] = value
            else:
                refuse("unsupported_member_type")
            if len(records) > MAX_FILES:
                refuse("inventory_count_budget")

    try:
        walk(rootfd, "")
    finally:
        os.close(rootfd)
    return check_records(records), elf


def elf_metadata(data: bytes) -> dict:
    """Bounded Linux x86_64 ELF metadata, including per-provider version needs."""
    if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
        refuse("unsupported_elf")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if header[1] != 62 or header[8] != 56 or header[9] > 1024:
        refuse("unsupported_elf")
    offset, count = header[4], header[9]

    def unpack(fmt, at):
        if at < 0 or at + struct.calcsize(fmt) > len(data):
            refuse("malformed_elf")
        return struct.unpack_from(fmt, data, at)

    programs = [unpack("<IIQQQQQQ", offset + i * 56) for i in range(count)]

    def address(value):
        for p in programs:
            if p[0] == 1 and p[3] <= value < p[3] + p[5]:
                return p[2] + value - p[3]
        refuse("malformed_elf_address")

    dynamic = {}
    interpreter = None
    for p in programs:
        if p[2] + p[5] > len(data):
            refuse("malformed_elf")
        if p[0] == 3:
            interpreter = data[p[2] : p[2] + p[5]].rstrip(b"\0").decode("ascii")
        if p[0] == 2:
            for at in range(p[2], p[2] + p[5], 16):
                tag, value = unpack("<qQ", at)
                if tag == 0:
                    break
                dynamic.setdefault(tag, []).append(value)
    strings = address(dynamic[5][0]) if 5 in dynamic else 0
    stringsize = dynamic.get(10, [0])[0]

    def string(at):
        end = data.find(b"\0", strings + at, strings + stringsize)
        if at < 0 or at >= stringsize or end < 0:
            refuse("malformed_elf_string")
        return data[strings + at : end].decode("ascii")

    requires = {}
    if any(dynamic.get(tag, [0])[0] > 1024 for tag in (0x6FFFFFFF, 0x6FFFFFFD)):
        refuse("malformed_elf_versions")
    at = address(dynamic[0x6FFFFFFE][0]) if 0x6FFFFFFE in dynamic else 0
    for _ in range(dynamic.get(0x6FFFFFFF, [0])[0]):
        _, number, filename, auxiliary, following = unpack("<HHIII", at)
        if number > 1024:
            refuse("malformed_elf_versions")
        provider = string(filename)
        cursor = at + auxiliary
        versions = []
        for _ in range(number):
            _, _, _, name, nextaux = unpack("<IHHII", cursor)
            versions.append(string(name))
            cursor += nextaux
        requires[provider] = sorted(versions)
        at += following
    defines = []
    at = address(dynamic[0x6FFFFFFC][0]) if 0x6FFFFFFC in dynamic else 0
    for _ in range(dynamic.get(0x6FFFFFFD, [0])[0]):
        _, _, _, _, _, auxiliary, following = unpack("<HHHHIII", at)
        name, _ = unpack("<II", at + auxiliary)
        defines.append(string(name))
        at += following
    return {
        "machine": "x86_64",
        "interpreter": interpreter,
        "needed": [string(v) for v in dynamic.get(1, [])],
        "soname": string(dynamic[14][0]) if 14 in dynamic else None,
        "rpath": [string(v) for tag in (15, 29) for v in dynamic.get(tag, [])],
        "requires": requires,
        "defines": sorted(defines),
    }


def verify_elf(actual: dict[str, bytes], pin: dict):
    expected = {r["path"]: r["metadata"] for r in pin["elf"]}
    if len(expected) != len(pin["elf"]) or set(actual) != set(expected):
        refuse("elf_inventory_mismatch")
    metadata = {path: elf_metadata(value) for path, value in actual.items()}
    if metadata != expected:
        refuse("elf_metadata_mismatch")
    providers = {}
    for path, row in metadata.items():
        # The loader also finds a DSO without DT_SONAME by its exact file name.
        # Only the two deliberately mounted library directories are lookup roots.
        names = {row["soname"]} if row["soname"] else set()
        if posixpath.dirname(path) in {"runtime/lib", "python/lib"}:
            names.add(posixpath.basename(path))
        for name in names:
            if name in providers and providers[name][0] != path:
                refuse("ambiguous_elf_provider")
            providers[name] = (path, row)
    for path, row in metadata.items():
        if row["interpreter"] not in {None, "/lib64/ld-linux-x86-64.so.2"}:
            refuse("unsupported_elf_interpreter")
        for required in row["needed"]:
            if required.startswith("$ORIGIN/"):
                local = posixpath.normpath(
                    posixpath.join(posixpath.dirname(path), required[8:])
                )
                if local not in metadata:
                    refuse("missing_elf_origin_provider")
            elif required not in providers:
                refuse("missing_elf_provider")
        for required, versions in row["requires"].items():
            if required not in providers or not set(versions) <= set(
                providers[required][1]["defines"]
            ):
                refuse("elf_provider_version_mismatch")


def inspect_archive(
    path: Path, pin: dict
) -> tuple[list[dict], dict[str, bytes], bytes]:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_size != pin["bundle"]["bytes"]
    ):
        refuse("artifact_size_or_type_mismatch")
    raw = regular_bytes(path, pin["bundle"]["bytes"])
    if hashlib.sha256(raw).hexdigest() != pin["bundle"]["sha256"]:
        refuse("artifact_digest_mismatch")
    records, elf = [], {}
    # Parse the exact immutable bytes just hashed, rather than reopening the path.
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|xz") as archive:
        total = 0
        for member in archive:
            name = relative_path(member.name)
            if member.isdir():
                row = {"path": name, "kind": "directory", "mode": member.mode}
            elif member.issym():
                row = {"path": name, "kind": "symlink", "target": member.linkname}
            elif member.isfile():
                if member.size > MAX_FILE_BYTES or total + member.size > MAX_BYTES:
                    refuse("inventory_byte_budget")
                stream = archive.extractfile(member)
                value = stream.read(member.size + 1)
                if len(value) != member.size:
                    refuse("artifact_member_size_mismatch")
                total += member.size
                row = _file_record(name, member.mode, value)
                if value.startswith(b"\x7fELF"):
                    elf[name] = value
            else:
                refuse("unsupported_member_type")
            records.append(row)
            if len(records) > MAX_FILES:
                refuse("inventory_count_budget")
    verify_inventory(records, pin)
    verify_elf(elf, pin)
    return records, elf, raw


def install_path(path: Path, *, new: bool = False):
    if (
        not path.is_absolute()
        or path.parent != Path("/opt/miy")
        or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", path.name)
    ):
        refuse("cache_install_path_refused")
    for parent in [Path("/"), Path("/opt"), Path("/opt/miy")]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            refuse("unsafe_cache_parent")
    if new:
        if path.exists() or path.is_symlink():
            refuse("existing_stage_refused")
    else:
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o555
        ):
            refuse("unsafe_cache_root")


def extract_verified_archive(snapshot: bytes, destination: Path, records: list[dict]):
    """New destination only; caller verifies full artifact and parent before calling."""
    destination.mkdir(mode=0o700)
    links = []
    bypath = {r["path"]: r for r in records}
    with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r|xz") as archive:
        for member in archive:
            name = relative_path(member.name)
            expected = bypath.get(name)
            if expected is None:
                refuse("artifact_changed_during_stage")
            target = destination / name
            if member.isdir() and expected["kind"] == "directory":
                target.mkdir(mode=0o700)
            elif member.issym() and expected["kind"] == "symlink":
                if member.linkname != expected["target"]:
                    refuse("artifact_changed_during_stage")
                links.append((target, member.linkname))
            elif member.isfile() and expected["kind"] == "file":
                if member.size != expected["bytes"]:
                    refuse("artifact_changed_during_stage")
                stream = archive.extractfile(member)
                value = stream.read(member.size + 1)
                if hashlib.sha256(value).hexdigest() != expected["sha256"]:
                    refuse("artifact_changed_during_stage")
                with target.open("xb") as output:
                    output.write(value)
                target.chmod(expected["mode"])
            else:
                refuse("artifact_changed_during_stage")
    for target, link in links:
        target.symlink_to(link)
    for row in reversed(records):
        if row["kind"] == "directory":
            (destination / row["path"]).chmod(0o555)
    destination.chmod(0o555)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path)
    source.add_argument("--cache-root", type=Path)
    parser.add_argument("--stage-new", type=Path)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="preflight dedicated source mount targets; no app manifest reads",
    )
    args = parser.parse_args()
    try:
        pin = load_pin()
        if args.stage_new and not args.archive:
            refuse("stage_requires_archive")
        if args.archive:
            records, _, snapshot = inspect_archive(args.archive, pin)
            if args.stage_new:
                install_path(args.stage_new, new=True)
                usage = os.statvfs(args.stage_new.parent)
                available = (
                    usage.f_bavail * usage.f_frsize - pin["bundle"]["regular_bytes"]
                )
                if (
                    available < 15 * 1024**3
                    or available / (usage.f_blocks * usage.f_frsize) < 0.15
                ):
                    refuse("insufficient_post_stage_headroom")
                if os.geteuid() != 0:
                    refuse("root_owned_stage_required")
                extract_verified_archive(snapshot, args.stage_new, records)
                install_path(args.stage_new)
                records, elf = scan_tree(args.stage_new, owner=0)
                verify_inventory(records, pin)
                verify_elf(elf, pin)
        else:
            install_path(args.cache_root)
            records, elf = scan_tree(args.cache_root, owner=0)
            verify_inventory(records, pin)
            verify_elf(elf, pin)
        if args.source_root:
            verify_source_mounts(args.source_root, pin)
    except (
        ToolchainRefused,
        OSError,
        tarfile.TarError,
        UnicodeError,
        struct.error,
    ) as error:
        code = (
            str(error)
            if isinstance(error, ToolchainRefused)
            else "toolchain_input_refused"
        )
        print(json.dumps({"verified": False, "reason": code}))
        return 2
    print(
        json.dumps(
            {
                "verified": True,
                "toolchain_id": pin["toolchain_id"],
                "inventory_sha256": pin["bundle"]["inventory_sha256"],
                "packages_executed": False,
                "native_policy_attested": False,
                "service_or_workbench_activated": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
