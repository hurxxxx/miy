"""Build provenance and an offline, one-process check of the inactive API image."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path("/opt/miy")
INPUTS = (
    "apps/api/pyproject.toml",
    "apps/api/uv.lock",
    "apps/api/README.md",
    "apps/api/src",
    "apps/official-suite/api/pyproject.toml",
    "apps/official-suite/api/README.md",
    "apps/official-suite/api/src",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "packages/contracts/package.json",
    "packages/collab-codec-runtime/package.json",
    "packages/core-web/package.json",
    "packages/ui/package.json",
    "config/runtime.json",
    "config/runtime.schema.json",
    "packages/contracts/miy-desktop-update-feed.manifest.json",
    "scripts/blocknote-collab-codec.mjs",
    "ops/official-suite-api/Dockerfile",
    "ops/official-suite-api/verify.py",
)
RUNTIME_FILES = (
    "pnpm-workspace.yaml",
    "config/runtime.json",
    "config/runtime.schema.json",
    "packages/contracts/miy-desktop-update-feed.manifest.json",
    "scripts/blocknote-collab-codec.mjs",
    "ops/official-suite-api/verify.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@contextmanager
def opened_path(directory: int, relative: Path, *, directories: bool = False):
    """Walk each component without following links, retaining only owned FDs."""
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("Artifact paths must stay inside their declared root")
    current = os.dup(directory)
    try:
        try:
            for index, part in enumerate(relative.parts):
                flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
                if directories or index < len(relative.parts) - 1:
                    flags |= os.O_DIRECTORY
                following = os.open(part, flags, dir_fd=current)
                os.close(current)
                current = following
        except OSError:
            raise ValueError(
                "Artifact input is missing, replaced or a symlink"
            ) from None
        yield current
    finally:
        os.close(current)


@contextmanager
def opened_root(root: Path):
    if not root.is_absolute() or root == Path("/") or root.resolve(strict=True) != root:
        raise ValueError("Artifact root must be canonical and contain no symlinks")
    anchor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with opened_path(anchor, root.relative_to("/"), directories=True) as directory:
            yield directory
    finally:
        os.close(anchor)


def checked_name(relative: Path) -> None:
    if any(part.startswith((".env", ".auth_info")) for part in relative.parts):
        raise ValueError("Environment and credential files cannot be artifact inputs")


def regular_identity(descriptor: int) -> tuple[int, ...]:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Artifact inputs must be regular files without hardlinks")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_input(root: Path, relative: str | Path) -> bytes:
    """Validate again when reading; an earlier inventory is not a path grant."""
    relative = Path(relative)
    checked_name(relative)
    with opened_root(root) as directory, opened_path(directory, relative) as descriptor:
        before = regular_identity(descriptor)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            content = stream.read()
        if regular_identity(descriptor) != before:
            raise ValueError("Artifact input changed during reading")
        with opened_path(directory, relative) as current:
            if regular_identity(current) != before:
                raise ValueError("Artifact input was replaced during reading")
    return content


def input_digest(root: Path, path: Path) -> str:
    return hashlib.sha256(read_input(root, path.relative_to(root))).hexdigest()


def input_files(root: Path) -> list[Path]:
    files: list[Path] = []
    with opened_root(root) as directory:

        def visit(relative: Path) -> None:
            if "__pycache__" in relative.parts or relative.suffix in {".pyc", ".pyo"}:
                return
            checked_name(relative)
            with opened_path(directory, relative) as descriptor:
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    for name in sorted(os.listdir(descriptor)):
                        visit(relative / name)
                else:
                    regular_identity(descriptor)
                    files.append(root / relative)

        for relative in INPUTS:
            visit(Path(relative))
    return sorted(files)


@contextmanager
def context_output(root: Path, relative: Path):
    """Create only a new archive, without following a replaced output ancestor."""
    if relative.is_absolute() or ".." in relative.parts or not relative.name:
        raise ValueError("Context output must stay inside its declared root")
    with opened_root(root) as directory:
        current = os.dup(directory)
        try:
            for part in relative.parent.parts:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                following = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                os.close(current)
                current = following
            descriptor = os.open(
                relative.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=current,
            )
            with os.fdopen(descriptor, "wb") as stream:
                yield stream
        finally:
            os.close(current)


def context(args: argparse.Namespace) -> None:
    """Freeze explicit inputs before a potentially long Docker dependency build."""
    root = Path(__file__).resolve().parents[2]
    output = Path(os.path.abspath(args.output))
    if not output.parent.is_relative_to(root / ".runtime/official-api-artifact"):
        raise ValueError("Context output must be inside .runtime/official-api-artifact")
    paths = input_files(root)
    entries = {
        path.relative_to(root).as_posix(): input_digest(root, path) for path in paths
    }
    # Exclusive creation preserves previous artifacts. An interrupted partial
    # archive is not reusable: choose a new path, then use only a completed result.
    with (
        context_output(root, output.relative_to(root)) as stream,
        tarfile.open(fileobj=stream, mode="w") as archive,
    ):
        for path in paths:
            relative = path.relative_to(root).as_posix()
            content = read_input(root, relative)
            if hashlib.sha256(content).hexdigest() != entries[relative]:
                raise ValueError("Artifact inputs changed while freezing the context")
            entry = tarfile.TarInfo(relative)
            entry.size = len(content)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(content))
    current = {
        path.relative_to(root).as_posix(): input_digest(root, path)
        for path in input_files(root)
    }
    if entries != current:
        raise ValueError("Artifact inputs changed while freezing the context")
    print(
        json.dumps(
            {
                "context_sha256": input_digest(root, output),
                "input_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
            },
            sort_keys=True,
        )
    )


def record(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", args.revision or ""):
        raise ValueError(
            "Build requires the checkout revision, including for dirty sources"
        )
    if args.dirty not in {"true", "false"}:
        raise ValueError("Build requires an explicit source dirty flag")
    images = {
        name: getattr(args, name) for name in ("node_image", "python_image", "uv_image")
    }
    if any(
        not re.fullmatch(r".+@sha256:[a-f0-9]{64}", value or "")
        for value in images.values()
    ):
        raise ValueError("Every build base must have an immutable digest")
    entries = {
        path.relative_to(ROOT).as_posix(): input_digest(ROOT, path)
        for path in input_files(ROOT)
    }
    wheels = {path.name: digest(path) for path in sorted(Path("/wheels").glob("*.whl"))}
    if len(wheels) != 2 or not any(
        name.startswith("miy_official_api-") for name in wheels
    ):
        raise ValueError("Artifact requires the two matching API wheels")
    manifest = {
        "schema_version": 1,
        "profile": "official-api-inactive",
        "source_revision": args.revision,
        "source_dirty": args.dirty == "true",
        "images": images,
        "pnpm_version": "10.34.5",
        "inputs": entries,
        "input_sha256": hashlib.sha256(canonical(entries)).hexdigest(),
        "wheels": wheels,
    }
    (ROOT / "artifact.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )


def forbidden(*_args, **_kwargs):
    raise AssertionError(
        "Inactive artifact attempted an external connection or runtime initialization"
    )


def verify() -> None:
    assert os.getuid() == 10001, "Image must use the existing non-root runtime identity"
    assert Path.cwd() == ROOT
    assert not (ROOT / ".env").exists()
    assert not (ROOT / "apps/api/src").exists(), "Smoke must import installed wheels"
    assert not (ROOT / "apps/worker").exists()
    assert not (ROOT / "apps/api/alembic").exists()
    assert not (ROOT / "dist/apps/web").exists()
    manifest = json.loads((ROOT / "artifact.json").read_text())
    assert manifest["profile"] == "official-api-inactive"
    assert (
        manifest["input_sha256"]
        == hashlib.sha256(canonical(manifest["inputs"])).hexdigest()
    )
    assert manifest["source_revision"] == os.environ["MIY_RUNTIME_REVISION"]
    for relative in RUNTIME_FILES:
        assert input_digest(ROOT, ROOT / relative) == manifest["inputs"][relative], (
            relative
        )
    assert importlib.metadata.version("miy-official-api") == importlib.metadata.version(
        "miy-api"
    )
    # The installed artifact must contain both entries. Resolving their location
    # proves packaging without importing the active runtime or initializing storage.
    for entry in ("miy_api.platform_runtime", "miy_official_api.runtime"):
        specification = importlib.util.find_spec(entry)
        assert specification is not None and specification.origin
        assert Path(specification.origin).resolve().is_relative_to(Path(sys.prefix).resolve())

    # This synthetic address is never contacted. Keep production's typed settings
    # requirement, without copying any host environment or using a database fixture.
    os.environ["MIY_POSTGRES_DSN"] = "postgresql+psycopg://127.0.0.1:9/inactive"
    with (
        patch("socket.socket.connect", forbidden),
        patch("socket.create_connection", forbidden),
    ):
        from fastapi.testclient import TestClient
        from miy_api import app as factory
        from miy_api.core.settings import WORKSPACE_ROOT
        from miy_api.openapi_contract import assert_openapi_contract
        from starlette.websockets import WebSocketDisconnect

        assert WORKSPACE_ROOT == ROOT
        names = (
            "init_db",
            "get_session_factory",
            "ensure_bucket",
            "initialize_platform_extensions",
            "prepare_miy_desktop_update_dirs",
            "mount_frontend",
            "mount_miy_desktop_update_feeds",
            "bootstrap_telemetry",
            "install_stack_dump_signal",
        )
        with patch.multiple(factory, **{name: forbidden for name in names}):
            module = importlib.import_module("miy_official_api.main")
            for loaded in (factory, module):
                assert (
                    Path(loaded.__file__)
                    .resolve()
                    .is_relative_to(Path(sys.prefix).resolve())
                )
            assert module.app.state.api_composition == "official"
            with TestClient(module.app) as client:
                health = client.get("/healthz")
                assert (
                    health.status_code == 200
                    and health.json()["activation"] == "inactive"
                )
                ready = client.get("/readyz")
                assert (
                    ready.status_code == 503
                    and ready.json()["code"] == "service_not_activated"
                )
                schema = client.get("/openapi.json")
                assert schema.status_code == 200
                assert_openapi_contract(schema.json())
                assert "/api/v1/docs/hub" in schema.json()["paths"]
                assert "/api/v1/pms/lists" in schema.json()["paths"]
                assert "/api/v1/auth/login" not in schema.json()["paths"]
                for method in ("GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"):
                    response = client.request(method, "/api/v1/docs/hub")
                    assert response.status_code == 503
                    assert response.json() == {"code": "service_not_activated"}
                assert client.post("/healthz").status_code == 503
                try:
                    with client.websocket_connect("/api/v1/docs/ws/fixture"):
                        raise AssertionError("Inactive artifact accepted a WebSocket")
                except WebSocketDisconnect as error:
                    assert error.code == 1013

    # Exercise the real Node/BlockNote/Yjs assets copied to the image, not a mock.
    text = "Official API artifact codec roundtrip"
    block = {
        "id": "artifact-check",
        "type": "paragraph",
        "content": [{"type": "text", "text": text, "styles": {}}],
    }

    def codec(mode: str, payload: dict) -> dict:
        completed = subprocess.run(
            ["node", str(ROOT / "scripts/blocknote-collab-codec.mjs"), mode],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, "Packaged collaboration codec failed"
        return json.loads(completed.stdout)

    encoded = codec("encode", {"blocks": [block]})
    assert encoded["yjs_state"]
    decoded = codec("decode", encoded)
    assert decoded["blocks"][0]["id"] == block["id"]
    assert decoded["blocks"][0]["content"][0]["text"] == text
    print(
        json.dumps(
            {
                "result": "pass",
                "profile": manifest["profile"],
                "source_revision": manifest["source_revision"],
                "source_dirty": manifest["source_dirty"],
                "input_sha256": manifest["input_sha256"],
                "wheels": manifest["wheels"],
                "health": "inactive",
                "ready": False,
                "codec": "roundtrip",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    frozen_context = subparsers.add_parser("context")
    frozen_context.add_argument("--output", required=True)
    provenance = subparsers.add_parser("record")
    for option in ("revision", "dirty", "node-image", "python-image", "uv-image"):
        provenance.add_argument(f"--{option}", required=True)
    subparsers.add_parser("verify")
    arguments = parser.parse_args()
    if arguments.command == "context":
        context(arguments)
    elif arguments.command == "record":
        record(arguments)
    else:
        verify()
