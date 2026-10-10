"""Fail closed unless a reviewed source change stays inside official ownership.

Router/task owners come from the existing source inventories. Shared contracts,
locks, migrations, ORM models and runtime definitions require a full release.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
    )


def domain_owners(source: str) -> set[str]:
    return {
        node.module.split(".")[2]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("miy_api.domains.")
        and len(node.module.split(".")) >= 4
    }


def worker_owners(source: str) -> set[str]:
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "WORKER_TASK_MODULES":
                inventory = ast.literal_eval(node.value)
                return {
                    "apps/worker/src/" + module.replace(".", "/") + ".py"
                    for module, (owner, _) in inventory.items()
                    if owner == "official"
                }
    raise ValueError("official_task_inventory_required")


def owned_paths(official: str, platform: str, worker: str) -> tuple[set[str], set[str]]:
    domains = domain_owners(official) - domain_owners(platform)
    if not domains:
        raise ValueError("official_router_inventory_required")
    return (
        {f"apps/api/src/miy_api/domains/{domain}/" for domain in domains},
        worker_owners(worker),
    )


def assert_owned(paths: list[str], domains: set[str], tasks: set[str]) -> None:
    prefixes = (
        "apps/official-suite/api/",
        "apps/official-suite/worker/",
        "apps/official-suite/src/",
        "packages/official-suite-web/",
        "ops/official-suite-api/",
        "ops/official-suite-worker/",
        *sorted(domains),
    )
    for name in paths:
        if name.endswith("/models.py") or "/models/" in name or name.endswith(".sql"):
            raise ValueError("shared_storage_change_requires_full_release")
        if name not in tasks and not name.startswith(prefixes):
            raise ValueError("shared_source_change_requires_full_release")


def main() -> None:
    if len(sys.argv) not in (3, 4) or not re.fullmatch(r"[a-f0-9]{40}", sys.argv[2]):
        raise ValueError("official_source_revision_required")
    root, revision = Path(sys.argv[1]), sys.argv[2]
    target = sys.argv[3] if len(sys.argv) == 4 else "HEAD"
    if target != "HEAD" and not re.fullmatch(r"[a-f0-9]{40}", target):
        raise ValueError("official_target_revision_required")
    if (
        git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").strip().decode()
        != revision
    ):
        raise ValueError("official_source_revision_required")
    files = (
        "apps/api/src/miy_api/official_api_registry.py",
        "apps/api/src/miy_api/platform_api_registry.py",
        "apps/api/src/miy_api/core/worker_queue_contract.py",
    )
    current = owned_paths(
        *(git(root, "show", f"{target}:{name}").decode() for name in files)
    )
    previous = owned_paths(
        *(git(root, "show", f"{revision}:{name}").decode() for name in files)
    )
    if current != previous:
        raise ValueError("ownership_change_requires_full_release")
    paths = [
        name.decode()
        for name in git(
            root, "diff", "--name-only", "--no-renames", "-z", revision, target
        ).split(b"\0")
        if name
    ]
    assert_owned(paths, *current)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            "Official slice includes shared source or cannot prove ownership; use a coordinated full release.",
            file=sys.stderr,
        )
        sys.exit(1)
