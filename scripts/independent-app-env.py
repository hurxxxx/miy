"""Scaffold an app or print a constrained container plan. Never execute app host commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

from miy_api.domains.independent_apps.contracts import AppDefinition

ROOT = Path(__file__).resolve().parents[1]
IMAGE = re.compile(
    r"^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[a-f0-9]{64})$"
)


def manifest(source: Path) -> AppDefinition:
    path = source / "app.manifest.json"
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("Manifest inspection requires no-follow file-descriptor support")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("Cannot open the app manifest as a regular file") from exc
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("The manifest must be a regular file")
        payload = stream.read(65537)
        if len(payload) > 65536:
            raise ValueError("The manifest must be at most 64 KiB")
    return AppDefinition.model_validate_json(payload)


def container_plan(source: Path, *, image: str, port: int) -> dict:
    source = source.resolve(strict=True)
    definition = manifest(source)
    if not source.is_dir() or not IMAGE.fullmatch(image):
        raise ValueError("Use a source directory and a core-verified image pinned by digest")
    if not 1024 <= port <= 65535:
        raise ValueError("Use an unprivileged loopback port")
    # Include the exact checkout, so separate worktrees never share runtime identity.
    suffix = hashlib.sha256(str(source).encode()).hexdigest()[:12]
    name = f"miy-app-{definition.app_id[:32]}-{suffix}"
    network = f"{name}-net"
    command = [
        "docker",
        "create",
        "--name",
        name,
        "--label",
        "miy.independent-app=1",
        "--label",
        f"miy.app-id={definition.app_id}",
        "--network",
        network,
        "--user",
        "1000:1000",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--init",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m",
        "--workdir",
        "/workspace",
        image,
    ]
    return {
        "schema_version": 1,
        "app_id": definition.app_id,
        "definition_digest": definition.content_digest(),
        "source_directory": str(source),
        "profile": definition.runtime_profile,
        "container_name": name,
        "network_create": [
            "docker",
            "network",
            "create",
            "--internal",
            "--label",
            "miy.independent-app=1",
            network,
        ],
        "create": command,
        "start": ["docker", "start", name],
        "preview_origin": None,
        "requested_preview_origin": f"http://127.0.0.1:{port}",
        "ingress": {
            "publish": f"127.0.0.1:{port}:8080",
            "app_network": network,
            "upstream": f"http://{name}:8000",
            "requires_trusted_proxy": True,
        },
        "stop": ["docker", "stop", name],
        "remove_container": ["docker", "rm", name],
        "remove_network": ["docker", "network", "rm", network],
        "state": "plan_only",
        "required_configuration": [
            "A trusted executor must verify the image and runtime resource enforcement before start.",
            "The immutable image must contain the app code; no checkout or host credentials are mounted.",
            "An internal-only app network cannot be published directly here; a core ingress proxy must own the loopback listener.",
            "Attach only an approved platform API proxy to this internal network; no host Docker socket or credentials.",
            "Inject installation ID and public origins from server-managed configuration, never app manifest environment values.",
        ],
    }


def scaffold(
    destination: Path, *, app_id: str, name: str, repository: str, template: str = "basic"
) -> None:
    if template not in {"basic", "private-notes"}:
        raise ValueError("Unknown independent app template")
    definition = AppDefinition.model_validate(
        {
            "app_id": app_id,
            "display": {"name": name},
            "source": {"repository": repository},
            "runtime_profile": "web-api-postgres-v1"
            if template == "private-notes"
            else "web-api-v1",
            "requested_permissions": ["identity:read", "data:read", "data:write"]
            if template == "private-notes"
            else ["identity:read"],
        }
    )
    # copytree refuses an existing destination and preserves unrelated work.
    shutil.copytree(
        ROOT / "templates/independent-app",
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", "node_modules", "dist", ".venv"
        ),
    )
    if template == "private-notes":
        shutil.copytree(
            ROOT / "templates/independent-app-data",
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", ".pytest_cache", "node_modules", "dist", ".venv"
            ),
        )
    (destination / "AGENTS.md.template").rename(destination / "AGENTS.md")
    vendor = destination / "vendor/miy-app-sdk"
    vendor.mkdir(parents=True)
    shutil.copyfile(ROOT / "packages/app-sdk/package.json", vendor / "package.json")
    shutil.copytree(ROOT / "packages/app-sdk/src", vendor / "src")
    (destination / "app.manifest.json").write_text(
        json.dumps(definition.model_dump(), indent=2, ensure_ascii=False) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "scaffold", help="Create a self-contained React/Vite + FastAPI app"
    )
    create.add_argument("destination", type=Path)
    create.add_argument("--app-id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--repository", required=True)
    create.add_argument("--template", choices=("basic", "private-notes"), default="basic")
    plan = commands.add_parser("plan", help="Print core-profile argv; do not execute Docker")
    plan.add_argument("source", type=Path)
    plan.add_argument("--image", required=True)
    plan.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    try:
        if args.command == "scaffold":
            scaffold(
                args.destination,
                app_id=args.app_id,
                name=args.name,
                repository=args.repository,
                template=args.template,
            )
            print(f"Created {args.destination}")
        else:
            print(
                json.dumps(
                    container_plan(args.source, image=args.image, port=args.port),
                    indent=2,
                )
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
