#!/usr/bin/env python3
"""Finite Core SDK packaging from pinned public inputs; never activate a service."""

import argparse
import base64
import configparser
import csv
import functools
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
import platform
import posixpath
import re
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "ops/codex-console/executor/sdk-toolchain-pin.json"
PIN_SHA256 = "1e174a1e831f831029d92ecc7ca1cf87d8d3a969d26efc4719874f23df4fa76b"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_EXPANDED_BYTES = 2 * 1024**3
MAX_OUTPUT = 65536
CONFIG = (
    "prefer-symlinked-executables=true\nextend-node-path=false\nignore-scripts=true\n"
    "update-notifier=false\nmanage-package-manager-versions=false\n"
)
SDK_FILES = (
    "package.json",
    "README.md",
    "src/index.mjs",
    "src/file-picker.mjs",
    "src/index.test.mjs",
)
OMITTED_NODE_FILES = {".modules.yaml", ".pnpm-workspace-state-v1.json"}
PUBLIC_HOSTS = {
    "nodejs.org",
    "registry.npmjs.org",
    "github.com",
    "release-assets.githubusercontent.com",
    "raw.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "auth.docker.io",
    "registry-1.docker.io",
    "production.cloudflare.docker.com",
    "production.cloudfront.docker.com",
}


class ProducerRefused(Exception):
    """Fixed public refusal codes; never expose remote responses or private paths."""


def refuse(code):
    raise ProducerRefused(code)


@functools.cache
def verifier():
    spec = importlib.util.spec_from_file_location(
        "miy_sdk_verifier", ROOT / "scripts/verify-native-sdk-toolchain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(path, expected_sha256, expected_bytes=None, maximum=128 * 1024**2):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= maximum
            or (expected_bytes is not None and info.st_size != expected_bytes)
        ):
            refuse("public_artifact_size_or_type_refused")
        data = stream.read(info.st_size + 1)
    if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != expected_sha256:
        refuse("public_artifact_digest_refused")
    return data


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\x00" in value:
        refuse("unsafe_archive_path")
    return path


def archive_members(data):
    """Parse a verified snapshot, not a pathname reopened after verification."""
    count = total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for member in archive:
            count += 1
            total += max(0, member.size)
            relative(member.name.removeprefix("./"))
            if (
                count > MAX_ARCHIVE_MEMBERS
                or total > MAX_EXPANDED_BYTES
                or member.size < 0
            ):
                refuse("expanded_archive_budget")
            yield archive, member


def extract_distribution(data, destination, prefix, selected):
    names = set()
    links = []
    for archive, member in archive_members(data):
        path = relative(member.name)
        if path.parts[0] != prefix:
            refuse("distribution_prefix_refused")
        path = PurePosixPath(*path.parts[1:])
        name = str(path)
        if name == "." or not selected(name):
            continue
        if name in names or member.mode & 0o7000:
            refuse("duplicate_or_setid_distribution_member")
        names.add(name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if member.isdir():
            target.mkdir(exist_ok=True)
        elif member.isfile():
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        elif member.issym():
            resolved = posixpath.normpath(str(path.parent / member.linkname))
            if (
                PurePosixPath(member.linkname).is_absolute()
                or resolved == ".."
                or resolved.startswith("../")
            ):
                refuse("escaping_distribution_link")
            links.append((target, member.linkname))
        else:
            refuse("unsupported_distribution_member")
    # Links are created last so a member cannot write through an archive symlink.
    for target, link in links:
        target.symlink_to(link)
    for target, _ in links:
        try:
            contained = (
                target.resolve().is_relative_to(destination.resolve())
                and target.exists()
            )
        except (RuntimeError, OSError):
            contained = False
        if not contained:
            refuse("distribution_link_cycle_or_missing")


def oci_repository(pin):
    repository = pin["provenance"]["OCI_selected_runtime"]["supplier"].get("repository")
    if repository != "library/node":
        refuse("unsupported_public_oci_repository")
    return repository


def input_specifications(pin):
    provenance = pin["provenance"]
    rows = [
        ("toolchain/" + row["name"], row["sha256"], row["bytes"], row["url"])
        for row in provenance["public_artifacts"]
    ]
    signature = provenance["node_signature"]
    rows.append(
        (
            "toolchain/node-release-keys.kbx",
            signature["keyring_sha256"],
            None,
            signature["url"],
        )
    )
    for row in provenance["selected_node_archives"]:
        rows.append(("npm/" + row["archive"], row["sha256"], row["bytes"], row["url"]))
    for row in provenance["selected_python_wheels"]:
        rows.append(("wheels/" + row["file"], row["sha256"], row["bytes"], None))
    supplier = provenance["OCI_selected_runtime"]["supplier"]
    registry = "https://registry-1.docker.io/v2/" + oci_repository(pin) + "/"
    for kind in ("public_index", "selected_linux_amd64_manifest"):
        digest = supplier[kind]
        rows.append(
            (
                "oci/oci-" + digest.split(":")[1] + ".json",
                digest.split(":")[1],
                None,
                registry + "manifests/" + digest,
            )
        )
    for row in supplier["layers"]:
        rows.append(
            (
                "oci/" + row["path"],
                row["digest"].split(":")[1],
                row["bytes"],
                registry + "blobs/" + row["digest"],
            )
        )
    if len({row[0] for row in rows}) != len(rows):
        refuse("duplicate_public_input")
    for name, _, _, _ in rows:
        relative(name)
    return rows


def verify_inputs(pin, root):
    data = {
        name: snapshot(root / name, digest, size)
        for name, digest, size, _ in input_specifications(pin)
    }
    for row in pin["provenance"]["selected_node_archives"]:
        sri = (
            "sha512-"
            + base64.b64encode(
                hashlib.sha512(data["npm/" + row["archive"]]).digest()
            ).decode()
        )
        if sri != row["integrity"]:
            refuse("npm_sri_refused")
    supplier = pin["provenance"]["OCI_selected_runtime"]["supplier"]
    index = json.loads(
        data["oci/oci-" + supplier["public_index"].split(":")[1] + ".json"]
    )
    matches = [
        row
        for row in index["manifests"]
        if row["digest"] == supplier["selected_linux_amd64_manifest"]
        and row.get("platform", {}).get("os") == "linux"
        and row.get("platform", {}).get("architecture") == "amd64"
    ]
    manifest = json.loads(
        data[
            "oci/oci-"
            + supplier["selected_linux_amd64_manifest"].split(":")[1]
            + ".json"
        ]
    )
    if (
        len(matches) != 1
        or manifest["config"]["digest"] != supplier["config_digest"]
        or [(row["digest"], row["size"]) for row in manifest["layers"]]
        != [(row["digest"], row["bytes"]) for row in supplier["layers"]]
    ):
        refuse("oci_source_chain_refused")
    return data


def public_url(value):
    url = urllib.parse.urlsplit(value)
    try:
        port = url.port
    except ValueError:
        refuse("public_origin_refused")
    if (
        url.scheme != "https"
        or url.hostname not in PUBLIC_HOSTS
        or url.username
        or url.password
        or url.fragment
        or port not in (None, 443)
    ):
        refuse("public_origin_refused")
    for answer in socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(answer[4][0]).is_global:
            refuse("public_address_refused")
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        public_url(newurl)
        redirected = super().redirect_request(
            request, fp, code, message, headers, newurl
        )
        if (
            urllib.parse.urlsplit(request.full_url).hostname
            != urllib.parse.urlsplit(newurl).hostname
        ):
            redirected.remove_header("Authorization")
        return redirected


def fetch(value, maximum, *, headers=None):
    public_url(value)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), PublicRedirect()
    )
    request = urllib.request.Request(value, headers=headers or {})
    with opener.open(request, timeout=20) as response:
        if (
            response.headers.get("Content-Length")
            and int(response.headers["Content-Length"]) > maximum
        ):
            refuse("download_budget")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        refuse("download_budget")
    return data


def new_directory(path):
    parent = path.parent
    info = parent.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or parent.resolve() != parent
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
        or path.exists()
        or path.is_symlink()
    ):
        refuse("new_owned_destination_required")
    path.mkdir(mode=0o700)


def acquire(pin, destination):
    """Explicit public acquisition only. No default credentials/proxies/configuration."""
    usage = os.statvfs(destination.parent)
    expected = sum(
        size if size is not None else 2 * 1024**2
        for _, _, size, _ in input_specifications(pin)
    )
    available = usage.f_bavail * usage.f_frsize - expected
    if available < 15 * 1024**3 or available / (usage.f_blocks * usage.f_frsize) < 0.15:
        refuse("insufficient_acquisition_headroom")
    new_directory(destination)
    headers = None
    for name, digest, size, url in input_specifications(pin):
        if url is None:
            filename = PurePosixPath(name).name
            distribution, version = filename.split("-")[:2]
            metadata = json.loads(
                fetch(
                    "https://pypi.org/pypi/" + distribution + "/" + version + "/json",
                    2 * 1024**2,
                )
            )
            matches = [
                row
                for row in metadata["urls"]
                if row["filename"] == filename
                and row["digests"]["sha256"] == digest
                and row["size"] == size
            ]
            if len(matches) != 1:
                refuse("pypi_exact_wheel_unavailable")
            url = matches[0]["url"]
        if urllib.parse.urlsplit(url).hostname == "registry-1.docker.io":
            if headers is None:
                token = json.loads(
                    fetch(
                        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:"
                        + oci_repository(pin)
                        + ":pull",
                        65536,
                    )
                )["token"]
                headers = {
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
                }
            request_headers = headers
        else:
            request_headers = None
        data = fetch(
            url, size if size is not None else 2 * 1024**2, headers=request_headers
        )
        if (size is not None and len(data) != size) or hashlib.sha256(
            data
        ).hexdigest() != digest:
            refuse("downloaded_artifact_digest_refused")
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(data)
    verify_inputs(pin, destination)


def command(argv, cwd, environment, timeout=180):
    """One bounded public package-tool invocation, with no inherited environment."""
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    captured = bytearray()
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                refuse("public_tool_timeout")
            for key, _ in selector.select(min(remaining, 0.5)):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                captured.extend(chunk)
                if len(captured) > MAX_OUTPUT:
                    refuse("public_tool_output_budget")
        if process.wait(timeout=max(0.001, deadline - time.monotonic())):
            refuse("public_tool_failed")
        return bytes(captured)
    finally:
        selector.close()
        process.stdout.close()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def build_environment(work, bundle):
    home = work / "home"
    home.mkdir(mode=0o700)
    config = work / "core.npmrc"
    config.write_text(CONFIG)
    # A Core-owned workspace boundary prevents parent repository config discovery.
    (work / "pnpm-workspace.yaml").write_text("packages:\n  - project\n")
    (work / ".npmrc").write_text(CONFIG)
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_DATA_HOME": str(home / "data"),
        "PNPM_HOME": str(home / "pnpm"),
        "NPM_CONFIG_USERCONFIG": str(config),
        "NPM_CONFIG_GLOBALCONFIG": "/dev/null",
        "npm_config_registry": "https://registry.npmjs.org/",
        "npm_config_fetch_retries": "0",
        "npm_config_fetch_timeout": "20000",
        "PATH": str(bundle / "node/bin") + ":/usr/bin:/bin",
        "CI": "true",
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "TMPDIR": str(work / "temp"),
    }


def copy_sdk(destination):
    for name in SDK_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "packages/app-sdk" / name, target)


def stage_inputs(inputs, work):
    """External tools consume only the verified snapshots in the private build root."""
    destination = work / "verified-inputs"
    destination.mkdir(mode=0o700)
    for name, value in inputs.items():
        target = destination / name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(value)
        target.chmod(0o444)
    return destination


def require_offline_store(path, *, copy_to=None):
    """Copy public dependency bytes without following pnpm project tracking links."""
    if path is None or not path.is_absolute() or path.resolve() != path:
        refuse("explicit_public_store_required")
    count = total = 0
    if not path.exists():
        refuse("explicit_public_store_required")
    if copy_to is not None:
        new_directory(copy_to)
    rootfd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def safe(info, *, tracking=False):
        nonlocal count, total
        count += 1
        if info.st_uid != os.geteuid() or (
            not tracking
            and (
                info.st_mode & 0o022
                or not (
                    stat.S_ISDIR(info.st_mode)
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
                )
            )
        ):
            refuse("unsafe_public_store")
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
        if count > 20_000 or total > 512 * 1024**2:
            refuse("public_store_budget")

    def walk(fd, parts):
        safe(os.fstat(fd))
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                names.append(entry.name)
                if count + len(names) > 20_000:
                    refuse("public_store_budget")
        if not parts and set(names) != {"v10"}:
            refuse("unsafe_public_store")
        if parts == ("v10",) and (
            not {"files", "index"} <= set(names)
            or set(names) - {"files", "index", "projects"}
        ):
            refuse("unsafe_public_store")
        for name in sorted(names):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if parts in ((), ("v10",)) and not stat.S_ISDIR(info.st_mode):
                refuse("unsafe_public_store")
            if parts == ("v10", "projects"):
                if not re.fullmatch(r"[0-9a-f]{32}", name) or not stat.S_ISLNK(
                    info.st_mode
                ):
                    refuse("unsafe_public_store_tracking_metadata")
                safe(info, tracking=True)
                continue  # Do not readlink, follow or copy tracking entries.
            childparts = (*parts, name)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                try:
                    target = (
                        copy_to.joinpath(*childparts) if copy_to is not None else None
                    )
                    if target is not None and childparts != ("v10", "projects"):
                        target.mkdir(mode=0o700)
                    walk(child, childparts)
                finally:
                    os.close(child)
            else:
                safe(info)
                if copy_to is not None:
                    sourcefd = os.open(
                        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                    with os.fdopen(sourcefd, "rb") as source:
                        actual = os.fstat(source.fileno())
                        if (
                            actual.st_dev,
                            actual.st_ino,
                            actual.st_size,
                            actual.st_mode,
                            actual.st_uid,
                            actual.st_nlink,
                        ) != (
                            info.st_dev,
                            info.st_ino,
                            info.st_size,
                            info.st_mode,
                            info.st_uid,
                            info.st_nlink,
                        ):
                            refuse("public_store_changed_during_copy")
                        data = source.read(info.st_size + 1)
                    if len(data) != info.st_size:
                        refuse("public_store_changed_during_copy")
                    with copy_to.joinpath(*childparts).open("xb") as destination:
                        destination.write(data)
                    copy_to.joinpath(*childparts).chmod(
                        0o700 if info.st_mode & 0o111 else 0o600
                    )

    try:
        walk(rootfd, ())
    finally:
        os.close(rootfd)


def select_oci(pin, inputs, bundle):
    provenance = pin["provenance"]["OCI_selected_runtime"]
    selected = {row["path"]: row for row in provenance["files"]}
    found = set()
    for layer in provenance["supplier"]["layers"]:
        for archive, member in archive_members(inputs["oci/" + layer["path"]]):
            name = member.name.removeprefix("./")
            for destination, row in selected.items():
                if (
                    row["source_layer"] != layer["digest"]
                    or row["resolved_source_path"] != name
                ):
                    continue
                if (
                    destination in found
                    or not member.isfile()
                    or member.mode & 0o7000
                    or member.size != row["bytes"]
                ):
                    refuse("selected_oci_member_refused")
                with archive.extractfile(member) as stream:
                    value = stream.read(member.size + 1)
                if (
                    len(value) != member.size
                    or hashlib.sha256(value).hexdigest() != row["sha256"]
                ):
                    refuse("selected_oci_digest_refused")
                target = bundle / destination
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
                target.chmod(0o755)
                found.add(destination)
    if found != set(selected):
        refuse("selected_oci_file_missing")


def verify_installed_npm(pin, inputs, modules):
    for row in pin["provenance"]["selected_node_archives"]:
        compared = 0
        for archive, member in archive_members(inputs["npm/" + row["archive"]]):
            if not member.isfile():
                continue
            path = PurePosixPath(*relative(member.name).parts[1:])
            with archive.extractfile(member) as source:
                value = source.read(member.size + 1)
            actual = modules / row["installed_path"] / str(path)
            snapshot(actual, hashlib.sha256(value).hexdigest(), member.size)
            compared += 1
        if compared != row["all_regular_archive_members_match_installed"]:
            refuse("installed_npm_member_inventory_refused")


def normalize_tree(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode):
                path.chmod(0o555 if mode & 0o111 else 0o444)
            elif not stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                refuse("unsupported_generated_file")
    for directory, _, _ in os.walk(root, topdown=False):
        Path(directory).chmod(0o555)


def omit_python_console_scripts(packages):
    """Keep standard RECORD CSV for retained files; omit only declared CLI rows."""
    checking = verifier()
    scripts = packages / "bin"
    if not stat.S_ISDIR(scripts.lstat().st_mode):
        refuse("python_console_directory_refused")
    actual = set(os.listdir(scripts))
    for name in actual:
        path = scripts / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            refuse("python_console_file_refused")
    declared = set()
    replacements = []
    for metadata in sorted(packages.glob("*.dist-info")):
        if not stat.S_ISDIR(metadata.lstat().st_mode):
            refuse("python_metadata_directory_refused")
        entry_points = metadata / "entry_points.txt"
        own_scripts = set()
        if entry_points.exists():
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            try:
                parser.read_string(
                    checking.regular_bytes(entry_points, 1024**2).decode()
                )
                if parser.has_section("console_scripts"):
                    own_scripts = set(parser["console_scripts"])
            except (configparser.Error, UnicodeError):
                refuse("python_entry_points_refused")
        if any(not name or "/" in name or name in {".", ".."} for name in own_scripts):
            refuse("python_entry_points_refused")
        if declared & own_scripts:
            refuse("python_console_name_conflict")
        declared |= own_scripts
        record = metadata / "RECORD"
        raw = checking.regular_bytes(record, 4 * 1024**2)
        kept, removed, seen = [], set(), set()
        try:
            for row in csv.reader(io.StringIO(raw.decode(), newline=""), strict=True):
                if len(row) != 3 or not row[0] or row[0] in seen:
                    refuse("python_record_refused")
                seen.add(row[0])
                path = PurePosixPath(row[0])
                if path.is_absolute() or "\x00" in row[0]:
                    refuse("python_record_refused")
                if ".." in path.parts:
                    if row[0] not in {"../../bin/" + name for name in own_scripts}:
                        refuse("python_record_escape_refused")
                    removed.add(row[0].removeprefix("../../bin/"))
                else:
                    kept.append(row)
        except (csv.Error, UnicodeError):
            refuse("python_record_refused")
        if removed != own_scripts:
            refuse("python_console_record_mismatch")
        if removed:
            output = io.StringIO(newline="")
            csv.writer(output, lineterminator="\r\n").writerows(kept)
            replacements.append((record, output.getvalue().encode()))
    if actual != declared:
        refuse("python_console_inventory_mismatch")
    # All metadata is validated before changing any generated file.
    for record, value in replacements:
        record.write_bytes(value)
    shutil.rmtree(scripts)


def reserve_vite_scratch(modules):
    """The pinned graph owns one empty mountpoint, never a dependency writer."""
    target = modules / ".vite-temp"
    if target.exists() or target.is_symlink():
        refuse("vite_scratch_target_already_exists")
    target.mkdir(mode=0o755)


def canonical_archive(root, destination, records):
    with tarfile.open(
        destination, "w:xz", format=tarfile.PAX_FORMAT, preset=6
    ) as archive:
        for row in sorted(records, key=lambda value: value["path"]):
            path = root / row["path"]
            info = archive.gettarinfo(str(path), arcname=row["path"])
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if row["kind"] == "file":
                with path.open("rb") as source:
                    archive.addfile(info, source)
            else:
                archive.addfile(info)


def assemble(
    pin, inputs, artifact_root, work, *, prepare_public_store=False, offline_store=None
):
    if (
        platform.system() != "Linux"
        or platform.machine() not in ("x86_64", "amd64")
        or sys.version_info[:2] != (3, 12)
    ):
        refuse("unsupported_builder")
    if not prepare_public_store and offline_store is None:
        refuse("explicit_public_store_required")
    usage = os.statvfs(work.parent)
    available = usage.f_bavail * usage.f_frsize - pin["bundle"]["regular_bytes"] * 4
    if available < 15 * 1024**3 or available / (usage.f_blocks * usage.f_frsize) < 0.15:
        refuse("insufficient_build_headroom")
    new_directory(work)
    artifact_root = stage_inputs(inputs, work)
    bundle = work / "bundle"
    bundle.mkdir(mode=0o700)
    extract_distribution(
        inputs["toolchain/node.tar.xz"],
        bundle / "node",
        "node-v22.23.3-linux-x64",
        lambda name: name in ("bin/node", "LICENSE", "README.md"),
    )
    extract_distribution(
        inputs["toolchain/python.tar.gz"],
        bundle / "python",
        "python",
        lambda name: (
            name.startswith("lib/")
            or name in ("bin/python3.12", "bin/python3", "bin/python", "LICENSE")
        ),
    )
    extract_distribution(
        inputs["toolchain/pnpm.tgz"], bundle / "pnpm", "package", lambda name: True
    )
    select_oci(pin, inputs, bundle)
    environment = build_environment(work, bundle)
    (work / "temp").mkdir(mode=0o700)
    status = command(
        [
            "/usr/bin/gpgv",
            "--homedir",
            environment["HOME"],
            "--status-fd",
            "1",
            "--keyring",
            str(artifact_root / "toolchain/node-release-keys.kbx"),
            str(artifact_root / "toolchain/node-SHASUMS256.txt.sig"),
            str(artifact_root / "toolchain/node-SHASUMS256.txt"),
        ],
        work,
        environment,
    )
    fingerprint = pin["provenance"]["node_signature"]["signing_fingerprint"]
    if b"[GNUPG:] VALIDSIG " + fingerprint.encode() + b" " not in status:
        refuse("node_release_signature_refused")
    project = work / "project"
    project.mkdir(mode=0o700)
    shutil.copyfile(
        ROOT / "templates/independent-app/package.json", project / "package.json"
    )
    shutil.copyfile(
        ROOT / "ops/codex-console/executor/sdk-node-lock.yaml",
        project / "pnpm-lock.yaml",
    )
    copy_sdk(project / "vendor/miy-app-sdk")
    node = [str(bundle / "node/bin/node"), str(bundle / "pnpm/bin/pnpm.cjs")]
    if (
        command([node[0], "--version"], work, environment).strip() != b"v22.23.3"
        or command(node + ["--version"], work, environment).strip() != b"10.34.5"
    ):
        refuse("public_tool_version_refused")
    store = work / "pnpm-store" if prepare_public_store else offline_store
    if store is None:
        refuse("explicit_public_store_required")
    if prepare_public_store:
        environment["npm_config_offline"] = "false"
        command(
            node
            + [
                "store",
                "add",
                "--store-dir",
                str(store),
                *[
                    row["name"] + "@" + row["version"]
                    for row in pin["provenance"]["selected_node_archives"]
                ],
            ],
            work,
            environment,
        )
    else:
        copied_store = work / "pnpm-store"
        require_offline_store(store, copy_to=copied_store)
        store = copied_store
    environment["npm_config_offline"] = "true"
    command(
        node
        + [
            "--dir",
            str(project),
            "install",
            "--ignore-workspace",
            "--offline",
            "--frozen-lockfile",
            "--ignore-scripts",
            "--store-dir",
            str(store),
            "--package-import-method=copy",
            "--reporter=append-only",
        ],
        work,
        environment,
    )
    verify_installed_npm(pin, inputs, project / "node_modules")
    shutil.copytree(
        project / "node_modules",
        bundle / "node_modules",
        symlinks=True,
        ignore=lambda path, names: (
            OMITTED_NODE_FILES if Path(path) == project / "node_modules" else set()
        ),
    )
    python = bundle / "python/bin/python3.12"
    if (
        command([str(python), "--version"], work, environment).strip()
        != b"Python 3.12.14"
    ):
        refuse("public_tool_version_refused")
    command(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(artifact_root / "wheels"),
            "--only-binary=:all:",
            "--require-hashes",
            "--no-compile",
            "--target",
            str(bundle / "python-packages"),
            "--requirement",
            str(ROOT / "ops/codex-console/executor/sdk-python-requirements.txt"),
        ],
        work,
        environment,
    )
    # Standard pip metadata must not retain omitted scripts' build-root shebang hashes.
    omit_python_console_scripts(bundle / "python-packages")
    reserve_vite_scratch(bundle / "node_modules")
    copy_sdk(bundle / "sdk")
    profile = bundle / "profile"
    profile.mkdir()
    for source, destination in (
        (ROOT / "templates/independent-app/package.json", "package.json"),
        (ROOT / "templates/independent-app/pyproject.toml", "pyproject.toml"),
        (ROOT / "ops/codex-console/executor/sdk-node-lock.yaml", "pnpm-lock.yaml"),
    ):
        shutil.copyfile(source, profile / destination)
    (profile / ".npmrc").write_text(CONFIG)
    (bundle / "bin").mkdir()
    (bundle / "bin/pnpm").symlink_to("../pnpm/bin/pnpm.cjs")
    normalize_tree(bundle)
    checking = verifier()
    records, elf = checking.scan_tree(bundle)
    checking.verify_inventory(records, pin)
    checking.verify_elf(elf, pin)
    archive = work / pin["bundle"]["filename"]
    canonical_archive(bundle, archive, records)
    checking.inspect_archive(archive, pin)
    return {
        "archive": str(archive),
        "sha256": pin["bundle"]["sha256"],
        "bytes": pin["bundle"]["bytes"],
        "inventory_sha256": pin["bundle"]["inventory_sha256"],
        "members": len(records),
        "packing_python": sys.version.split()[0],
        "native_or_Task_accepted": False,
        "service_activated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument(
        "--acquire-public",
        action="store_true",
        help="explicitly acquire exact public inputs into a new artifact root",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--prepare-public-store",
        action="store_true",
        help="explicit pinned registry acquisition through public pnpm store add",
    )
    selection.add_argument(
        "--offline-store",
        type=Path,
        help="explicit prior public pnpm store; never fall back to downloading",
    )
    args = parser.parse_args()
    checking = verifier()
    try:
        snapshot(PIN_PATH, PIN_SHA256, maximum=128 * 1024)
        pin = checking.load_pin()
        if args.acquire_public:
            acquire(pin, args.artifact_root)
        inputs = verify_inputs(pin, args.artifact_root)
        result = assemble(
            pin,
            inputs,
            args.artifact_root,
            args.work_root,
            prepare_public_store=args.prepare_public_store,
            offline_store=args.offline_store,
        )
    except (
        ProducerRefused,
        checking.ToolchainRefused,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        reason = (
            str(error)
            if isinstance(error, (ProducerRefused, checking.ToolchainRefused))
            else "producer_input_or_tool_refused"
        )
        print(
            json.dumps(
                {"produced": False, "reason": reason, "service_activated": False}
            )
        )
        return 2
    print(json.dumps({"produced": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
