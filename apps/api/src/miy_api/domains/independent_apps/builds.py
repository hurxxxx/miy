"""Core-owned, offline development builder. Never run repository commands on the host.

The first profile uses dependencies baked into an explicitly approved local image.
It does not install arbitrary dependencies, pull images, or attest production builds.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from miy_api.domains.independent_apps.contracts import AppDefinition

MAX_ARCHIVE = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_FILES = 4096
MAX_SOURCE_METADATA = 1024 * 1024
MAX_SOURCE_DEPTH = 20
PYTHON = "/opt/miy/venvs/api/bin/python"
NODE = "/usr/local/bin/node"
MODULES = "/opt/miy/node-runtime/node_modules"
BUILD_COMMAND = (NODE, MODULES + "/vite/bin/vite.js", "build", "--outDir", "/workspace/dist")
TEST_COMMAND = (NODE, "--test")
RUNTIME_COMMAND = (
    PYTHON,
    "-m",
    "uvicorn",
    "api:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--no-access-log",
)

# This program is core source, passed as argv. App scripts and configuration execute
# only in the restricted container, with no writable image or host checkout.
PREPARE = r"""
import ast, json, pathlib, shutil, tomllib
source, root = pathlib.Path('/source'), pathlib.Path('/workspace')
for item in source.iterdir():
    if item.is_dir(): shutil.copytree(item, root / item.name)
    else: shutil.copyfile(item, root / item.name)
package = json.loads((root / 'package.json').read_text())
expected = {'react', 'react-dom', '@miy/app-sdk'}
assert set(package.get('dependencies', {})) == expected
assert set(package.get('devDependencies', {})) == {'vite'}
assert package['dependencies']['@miy/app-sdk'] == 'file:./vendor/miy-app-sdk'
modules = root / 'node_modules'
modules.mkdir()
for name in ('react', 'react-dom', 'vite'):
    installed = pathlib.Path('/opt/miy/node-runtime/node_modules') / name
    version = json.loads((installed / 'package.json').read_text())['version']
    assert package.get('dependencies', {}).get(name, package.get('devDependencies', {}).get(name)) == version
    (modules / name).symlink_to(installed, target_is_directory=True)
(modules / '@miy').mkdir()
(modules / '@miy/app-sdk').symlink_to(root / 'vendor/miy-app-sdk', target_is_directory=True)
assert any((root / 'tests').rglob('*.test.mjs'))
ast.parse((root / 'api.py').read_text())
project = tomllib.loads((root / 'pyproject.toml').read_text())
from importlib.metadata import version
for dependency in project['project']['dependencies']:
    name, pin = dependency.split('==')
    assert name in {'fastapi', 'uvicorn', 'httpx', 'pydantic-settings'}
    assert version(name) == pin
"""

LIMIT_CHECK = r"""
from pathlib import Path
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == '2147483648'
assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '256'
quota, period = map(int, Path('/sys/fs/cgroup/cpu.max').read_text().split())
assert quota == 2 * period
assert 'NoNewPrivs:\t1' in Path('/proc/self/status').read_text()
assert int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:')), 16) == 0
"""


EXPORT_OUTPUT = r"""
import sys, tarfile
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|', dereference=False) as archive:
    archive.add('/workspace/dist', arcname='dist')
"""


class BuildFailure(RuntimeError):
    """Sanitized failure; subprocess output is never an error message."""


@dataclass(frozen=True)
class BuildEvidence:
    app_id: str
    source_revision: str
    definition_digest: str
    source_archive_sha256: str
    artifact_digest: str
    builder_profile_digest: str
    checks: dict[str, int]
    target_environment: str = "development"


def _command(argv, *, timeout=30, limit=1024 * 1024, env=None):
    # Both Git and Docker must use core-owned configuration, never source .env or
    # the user's credential helpers. An isolated Docker config is supplied below.
    try:
        with subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        ) as process:
            output = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if not selector.select(timeout=0.1):
                            continue
                        data = os.read(process.stdout.fileno(), 65536)
                        if not data:
                            break
                        output.extend(data)
                        if len(output) > limit:
                            raise BuildFailure("build_output_limit")
                    else:
                        raise BuildFailure("build_timeout")
                return process.wait(timeout=1), bytes(output)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    except (OSError, subprocess.TimeoutExpired):
        raise BuildFailure("build_tool_unavailable") from None


def _required(argv, **kwargs):
    code, output = _command(argv, **kwargs)
    if code:
        raise BuildFailure("build_command_failed")
    return output


def _identity(value):
    scp = re.fullmatch(r"git@([A-Za-z0-9.-]+):([A-Za-z0-9_./-]+)", value)
    if scp:
        host, path = scp.groups()
        port = None
    else:
        parsed = urlsplit(value)
        if parsed.scheme not in ("https", "ssh") or not parsed.hostname or parsed.password:
            raise BuildFailure("build_source_mismatch")
        if parsed.query or parsed.fragment or (parsed.username and parsed.scheme != "ssh"):
            raise BuildFailure("build_source_mismatch")
        host, path, port = parsed.hostname, parsed.path, parsed.port
        if port == (443 if parsed.scheme == "https" else 22):
            port = None
    return host.lower(), port, path.strip("/").removesuffix(".git")


def _unpack(raw, destination):
    """Reject links, devices, traversal, credentials and oversized archive members."""
    if len(raw) > MAX_ARCHIVE:
        raise BuildFailure("build_archive_limit")
    seen, total = set(), 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                parts = name.parts
                if (
                    not parts
                    or name.is_absolute()
                    or ".." in parts
                    or "\\" in member.name
                    or name.as_posix() in seen
                    or len(seen) >= MAX_FILES
                    or not (member.isdir() or member.isreg())
                    or member.sparse
                    or member.size < 0
                    or member.size > MAX_FILE
                    or any(
                        part
                        in {
                            ".git",
                            ".codex",
                            ".ssh",
                            "node_modules",
                            "auth.json",
                            "id_rsa",
                            "id_ed25519",
                        }
                        or (part.startswith(".env") and part != ".env.example")
                        for part in parts
                    )
                ):
                    raise BuildFailure("build_archive_unsafe")
                seen.add(name.as_posix())
                total += member.size
                if total > MAX_ARCHIVE:
                    raise BuildFailure("build_archive_limit")
                target = destination.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output:
                        shutil.copyfileobj(archive.extractfile(member), output)
                    target.chmod(0o755 if member.mode & 0o100 else 0o644)
    except (tarfile.TarError, OSError, ValueError):
        raise BuildFailure("build_archive_unsafe") from None


def _verified_source_archive(git, revision):
    """Export only bytes whose object hashes descend from the requested commit.

    Git's object lookup and archive trust object filenames and replacement refs.
    Verify each read and retain those same bytes, rather than checking a mutable
    object database before a second, unverified export. Attributes never transform
    the source: the snapshot contains the literal committed files.
    """

    deadline = time.monotonic() + 60

    def object_bytes(kind, oid):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BuildFailure("build_timeout")
        content = git(
            "cat-file",
            kind,
            oid,
            limit=MAX_FILE if kind == "blob" else MAX_SOURCE_METADATA,
            timeout=remaining,
        )
        header = kind.encode() + b" " + str(len(content)).encode() + b"\0"
        if hashlib.sha1(header + content).hexdigest() != oid:
            raise BuildFailure("build_source_object_invalid")
        return content

    commit = object_bytes("commit", revision)
    tree_header = re.fullmatch(rb"tree ([a-f0-9]{40})", commit.split(b"\n", 1)[0])
    if tree_header is None:
        raise BuildFailure("build_source_object_invalid")
    output = io.BytesIO()
    count = total = 0
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:

        def visit(oid, prefix, depth):
            nonlocal count, total
            if depth > MAX_SOURCE_DEPTH:
                raise BuildFailure("build_archive_limit")
            content = object_bytes("tree", oid)
            offset, seen = 0, set()
            while offset < len(content):
                end = content.find(b"\0", offset)
                if end == -1 or end + 21 > len(content):
                    raise BuildFailure("build_source_object_invalid")
                try:
                    mode, name = content[offset:end].split(b" ", 1)
                    name = name.decode("utf-8")
                except (ValueError, UnicodeError):
                    raise BuildFailure("build_source_object_invalid") from None
                if not name or name in (".", "..") or "/" in name or "\\" in name or name in seen:
                    raise BuildFailure("build_archive_unsafe")
                seen.add(name)
                child = content[end + 1 : end + 21].hex()
                offset = end + 21
                count += 1
                if count > MAX_FILES:
                    raise BuildFailure("build_archive_limit")
                info = tarfile.TarInfo(prefix + name)
                if mode == b"40000":
                    info.type, info.mode = tarfile.DIRTYPE, 0o755
                    archive.addfile(info)
                    visit(child, info.name + "/", depth + 1)
                elif mode in (b"100644", b"100755"):
                    blob = object_bytes("blob", child)
                    total += len(blob)
                    if total > MAX_ARCHIVE:
                        raise BuildFailure("build_archive_limit")
                    info.size = len(blob)
                    info.mode = 0o755 if mode == b"100755" else 0o644
                    archive.addfile(info, io.BytesIO(blob))
                else:
                    raise BuildFailure("build_archive_unsafe")
                if output.tell() > MAX_ARCHIVE:
                    raise BuildFailure("build_archive_limit")

        visit(tree_header.group(1).decode(), "", 0)
    if output.tell() > MAX_ARCHIVE:
        raise BuildFailure("build_archive_limit")
    return output.getvalue()


def _snapshot(source, revision, expected, destination):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise BuildFailure("build_revision_required")
    if not source.is_absolute() or source.resolve() != source or not source.is_dir():
        raise BuildFailure("build_source_denied")
    metadata = source / ".git"
    if not metadata.is_dir() or metadata.is_symlink():
        raise BuildFailure("build_source_denied")
    env = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
    }
    prefix = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "log.showSignature=false",
        "-C",
        str(source),
    ]

    def git(*args, **kwargs):
        return _required([*prefix, *args], env=env, **kwargs)

    for flag, expected_path in (
        ("--show-toplevel", source),
        ("--absolute-git-dir", metadata),
        ("--git-common-dir", metadata),
    ):
        if Path(git("rev-parse", "--path-format=absolute", flag).decode().strip()) != expected_path:
            raise BuildFailure("build_source_denied")
    if _identity(git("remote", "get-url", "origin").decode().strip()) != _identity(
        expected.source.repository
    ):
        raise BuildFailure("build_source_mismatch")
    keys = git("config", "--name-only", "--list").decode().lower().splitlines()
    if any(
        re.fullmatch(r"filter\..*\.(clean|smudge|process)|tar\..*\.command|diff\..*\.textconv", key)
        or re.fullmatch(r"remote\..*\.(promisor|partialclonefilter)", key)
        or key == "extensions.partialclone"
        for key in keys
    ):
        raise BuildFailure("build_source_git_policy")
    if git("rev-parse", "--verify", revision + "^{commit}").decode().strip() != revision:
        raise BuildFailure("build_revision_required")
    raw = _verified_source_archive(git, revision)
    _unpack(raw, destination)
    try:
        path = destination / "app.manifest.json"
        if path.stat().st_size > 65536:
            raise ValueError("manifest")
        actual = AppDefinition.model_validate_json(path.read_bytes())
        if actual.content_digest() != expected.content_digest():
            raise ValueError("manifest")
    except (ValueError, OSError):
        raise BuildFailure("build_definition_mismatch") from None
    return hashlib.sha256(raw).hexdigest()


def build_app(
    *,
    source: Path,
    revision: str,
    expected_definition: dict,
    toolchain_image: str,
    work_root: Path,
    docker_bin: str = "docker",
    build_id: str | None = None,
) -> BuildEvidence:
    """Only trusted callers select toolchain_image and work_root; no public input binding."""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", toolchain_image):
        raise BuildFailure("build_toolchain_required")
    if not work_root.is_absolute() or work_root.resolve() != work_root or not work_root.is_dir():
        raise BuildFailure("build_workspace_denied")
    try:
        definition = AppDefinition.model_validate(expected_definition)
    except ValueError:
        raise BuildFailure("build_definition_mismatch") from None
    try:
        build_uuid = UUID(build_id) if build_id is not None else uuid4()
    except ValueError:
        raise BuildFailure("build_identity_invalid") from None
    identity = "miy-build-" + build_uuid.hex
    base_tag = "miy-build-base:" + identity
    profile = {
        "version": 1,
        "image": toolchain_image,
        "builder_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "prepare": PREPARE,
        "limits": LIMIT_CHECK,
        "export": EXPORT_OUTPUT,
        "build": BUILD_COMMAND,
        "test": TEST_COMMAND,
        "runtime": RUNTIME_COMMAND,
    }
    profile_digest = (
        "sha256:" + hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
    )
    with tempfile.TemporaryDirectory(prefix=identity + "-", dir=work_root) as temporary:
        root = Path(temporary)
        checkout, context = root / "source", root / "context"
        checkout.mkdir()
        context.mkdir()
        archive_digest = _snapshot(source, revision, definition, checkout)
        app_source = checkout / definition.source.directory
        if not app_source.is_dir():
            raise BuildFailure("build_source_mismatch")
        if definition.source.directory != ".":
            shutil.copyfile(checkout / "app.manifest.json", app_source / "app.manifest.json")
        (root / "docker-config").mkdir()
        docker_env = {"PATH": os.defpath, "DOCKER_CONFIG": str(root / "docker-config")}

        def docker(*args, **kwargs):
            return _required([docker_bin, *args], env=docker_env, **kwargs)

        config = json.loads(docker("image", "inspect", toolchain_image))[0]
        if (
            config["Id"] != toolchain_image
            or config["Config"].get("OnBuild")
            or config["Config"].get("Volumes")
        ):
            raise BuildFailure("build_toolchain_invalid")
        create_attempted = tag_attempted = False
        checks = {}
        try:
            create_attempted = True
            docker(
                "create",
                "--name",
                identity,
                "--pull=never",
                "--label",
                "miy.trusted-build=1",
                "--label",
                f"miy.independent-build={build_uuid}",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "256",
                "--memory",
                "2g",
                "--memory-swap",
                "2g",
                "--cpus",
                "2",
                "--user",
                "1000:1000",
                "--init",
                "--no-healthcheck",
                "--log-driver=none",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=64m",
                "--tmpfs",
                "/workspace:rw,nosuid,nodev,size=256m,uid=1000,gid=1000",
                "--mount",
                f"type=bind,src={app_source},dst=/source,readonly",
                "--workdir",
                "/workspace",
                "--entrypoint",
                PYTHON,
                toolchain_image,
                "-I",
                "-c",
                "import time; time.sleep(3600)",
            )
            docker("start", identity)
            for label, command in (
                ("resource_limits", (PYTHON, "-I", "-c", LIMIT_CHECK)),
                ("profile", (PYTHON, "-I", "-c", PREPARE)),
                ("test", TEST_COMMAND),
                ("build", BUILD_COMMAND),
            ):
                code, _ = _command(
                    [docker_bin, "exec", identity, *command], env=docker_env, timeout=180
                )
                checks[label] = code
                if code:
                    raise BuildFailure("build_check_failed:" + label)
            # Docker cp cannot read tmpfs. Its documented exec/archive alternative
            # avoids writable host mounts; host extraction rejects links and bounds bytes.
            raw = docker(
                "exec", identity, PYTHON, "-I", "-c", EXPORT_OUTPUT, limit=MAX_ARCHIVE, timeout=60
            )
            payload = context / "payload"
            shutil.copytree(app_source, payload)
            if (payload / "dist").exists():
                shutil.rmtree(payload / "dist")
            _unpack(raw, payload)
            if not (payload / "dist/index.html").is_file():
                raise BuildFailure("build_artifact_missing")
            tag_attempted = True
            docker("image", "tag", toolchain_image, base_tag)
            if (
                docker("image", "inspect", base_tag, "--format", "{{.Id}}").decode().strip()
                != toolchain_image
            ):
                raise BuildFailure("build_toolchain_changed")
            (context / "Dockerfile").write_text(
                f"FROM {base_tag}\nWORKDIR /workspace\nCOPY payload/ ./\nUSER 1000:1000\n"
                f"ENTRYPOINT {json.dumps(RUNTIME_COMMAND)}\n"
            )
            docker(
                "build",
                "--pull=false",
                "--network=none",
                "--label",
                "miy.independent-app=1",
                "--label",
                f"miy.independent-build={build_uuid}",
                "--label",
                f"miy.app-id={definition.app_id}",
                "--label",
                f"miy.source-revision={revision}",
                "--label",
                f"miy.definition-digest={definition.content_digest()}",
                "--label",
                f"miy.builder-profile={profile_digest}",
                "--iidfile",
                str(root / "image-id"),
                "--file",
                str(context / "Dockerfile"),
                str(context),
                timeout=180,
            )
            artifact = (root / "image-id").read_text().strip()
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact):
                raise BuildFailure("build_artifact_invalid")
            if (
                docker("image", "inspect", artifact, "--format", "{{.Id}}").decode().strip()
                != artifact
            ):
                raise BuildFailure("build_artifact_invalid")
            checks["package"] = 0
            return BuildEvidence(
                definition.app_id,
                revision,
                definition.content_digest(),
                archive_digest,
                artifact,
                profile_digest,
                checks,
            )
        finally:
            cleanup_failed = False
            if create_attempted:
                try:
                    # A create response may be lost after the daemon created the
                    # object. Reconcile the exact identity before deleting it;
                    # failed inspection never proves that creation did not occur.
                    record = json.loads(docker("container", "inspect", identity))[0]
                    labels = record.get("Config", {}).get("Labels", {})
                    if (
                        record.get("Image") != toolchain_image
                        or labels.get("miy.trusted-build") != "1"
                        or labels.get("miy.independent-build") != str(build_uuid)
                    ):
                        raise BuildFailure("build_cleanup_identity_mismatch")
                    code, _ = _command([docker_bin, "rm", "--force", record["Id"]], env=docker_env)
                    cleanup_failed |= code != 0
                except (BuildFailure, ValueError, KeyError, IndexError, TypeError):
                    cleanup_failed = True
            if tag_attempted:
                try:
                    if (
                        docker("image", "inspect", base_tag, "--format", "{{.Id}}").decode().strip()
                        != toolchain_image
                    ):
                        raise BuildFailure("build_cleanup_identity_mismatch")
                    code, _ = _command([docker_bin, "image", "rm", base_tag], env=docker_env)
                    cleanup_failed |= code != 0
                except BuildFailure:
                    cleanup_failed = True
            if cleanup_failed:
                raise BuildFailure("build_cleanup_required")
