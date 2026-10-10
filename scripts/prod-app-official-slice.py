"""Fail closed unless a reviewed source change stays inside official ownership.

Router/task owners come from the existing source inventories. Shared contracts,
locks, migrations, ORM models and runtime definitions require a full release.
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import tarfile
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


def worker_inventory(source: str) -> dict[str, str]:
    """Read only literal module keys and owners, never evaluate task expressions."""
    inventories = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "WORKER_TASK_MODULES"
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
    ]
    if len(inventories) != 1 or not isinstance(inventories[0], ast.Dict):
        raise ValueError("official_task_inventory_required")
    result = {}
    for key, value in zip(inventories[0].keys, inventories[0].values):
        if (
            not isinstance(key, ast.Constant)
            or not isinstance(key.value, str)
            or not re.fullmatch(r"miy_worker\.tasks\.[a-z_][a-z0-9_]*", key.value)
        ):
            raise ValueError("official_task_inventory_required")
        if not isinstance(value, ast.Tuple) or len(value.elts) != 2:
            raise ValueError("official_task_inventory_required")
        owner = value.elts[0]
        if (
            not isinstance(owner, ast.Constant)
            or owner.value not in ("platform", "official")
            or key.value in result
        ):
            raise ValueError("official_task_inventory_required")
        result[key.value] = owner.value
    if not result:
        raise ValueError("official_task_inventory_required")
    return result


def worker_owners(source: str) -> set[str]:
    return {
        "apps/worker/src/" + module.replace(".", "/") + ".py"
        for module, owner in worker_inventory(source).items()
        if owner == "official"
    }


def owned_paths(official: str, platform: str, worker: str) -> tuple[set[str], set[str]]:
    domains = domain_owners(official) - domain_owners(platform)
    if not domains:
        raise ValueError("official_router_inventory_required")
    return (
        {f"apps/api/src/miy_api/domains/{domain}/" for domain in domains},
        worker_owners(worker),
    )


def assert_owned(
    paths: list[str], domains: set[str], tasks: set[str], shared: set[str] | None = None
) -> None:
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
        basename = Path(name).name
        if basename in ("package.json", "project.json") or basename.startswith(
            ("tsconfig.", "vite.config.")
        ):
            raise ValueError("shared_build_config_change_requires_full_release")
        if shared is not None and name in shared:
            raise ValueError("shared_consumer_change_requires_full_release")
        if name.endswith(("/models.py", ".sql")) or "/models/" in name:
            raise ValueError("shared_storage_change_requires_full_release")
        if name not in tasks and not name.startswith(prefixes):
            raise ValueError("shared_source_change_requires_full_release")


SOURCE_ROOTS = (
    "apps/api/src/",
    "apps/worker/src/",
    "apps/official-suite/api/src/",
    "apps/official-suite/worker/src/",
)

UI_ROOTS = (
    "apps/web/",
    "apps/official-suite/",
    "packages/",
    "tsconfig.base.json",
    "package.json",
)
UI_TEXT = re.compile(r"\.(?:[cm]?[jt]sx?|css|html|json|md|mdx)$")


def ui_sources(root: Path, revision: str) -> dict[str, str | None]:
    """Archive tracked frontend blobs; assets need only their exact tracked name."""
    archive = git(root, "archive", "--format=tar", revision, "--", *UI_ROOTS)
    result = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for entry in tree.getmembers():
            if entry.issym() or entry.islnk():
                raise ValueError("unresolved_frontend_symlink_owner")
            if entry.isfile():
                result[entry.name] = (
                    tree.extractfile(entry).read().decode()
                    if UI_TEXT.search(entry.name)
                    else None
                )
    return result


def shared_ui_consumers(sources: dict[str, str | None]) -> set[str]:
    """The pinned TypeScript parser reads blobs, never imports application code."""
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("prod-app-official-ui.mjs"))],
        input=json.dumps(sources).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=True,
    )
    names = json.loads(result.stdout)
    if not isinstance(names, list) or any(
        not isinstance(name, str) or name not in sources for name in names
    ):
        raise ValueError("unresolved_frontend_input_owner")
    return set(names)


def python_sources(root: Path, revision: str) -> dict[str, str]:
    archive = git(root, "archive", "--format=tar", revision, "--", *SOURCE_ROOTS)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        return {
            entry.name: tree.extractfile(entry).read().decode()
            for entry in tree.getmembers()
            if entry.isfile() and entry.name.endswith(".py")
        }


def shared_consumers(
    sources: dict[str, str], domains: set[str], tasks: set[str]
) -> set[str]:
    """Conservatively project shared imports, without executing reviewed code.

    Router composition and worker profile loading are existing inventory-owned
    boundaries. AI registration's dynamic imports are bound to app_registration
    declarations. Other unresolved dynamic imports cannot prove slice ownership.
    """
    modules = {}
    for name in sources:
        source_root = next(
            (prefix for prefix in SOURCE_ROOTS if name.startswith(prefix)), None
        )
        if source_root is None:
            raise ValueError("unknown_python_source_owner")
        module = name[len(source_root) : -3].replace("/", ".")
        module = module.removesuffix(".__init__")
        if module in modules:
            raise ValueError("ambiguous_python_module_owner")
        modules[module] = name
    packages = {
        module.rsplit(".", index)[0]
        for module in modules
        for index in range(1, module.count(".") + 1)
    }
    parsed = {module: ast.parse(sources[name]) for module, name in modules.items()}
    capabilities = set()
    for tree in parsed.values():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "app_registration"
            ):
                for keyword in node.keywords:
                    if keyword.arg == "ai_capability_modules":
                        declared = ast.literal_eval(keyword.value)
                        if not isinstance(declared, tuple) or not all(
                            isinstance(value, str) for value in declared
                        ):
                            raise ValueError("unresolved_capability_module_owner")
                        capabilities.update(declared)

    def resolve(module: str) -> set[str]:
        if not module.startswith(
            ("miy_api", "miy_worker", "miy_official_api", "miy_official_worker")
        ):
            return set()
        if module not in modules and module not in packages:
            raise ValueError("unresolved_internal_module_owner")
        # Importing a child executes its real parent package initializers too.
        parts = module.split(".")
        return {
            ".".join(parts[:index])
            for index in range(1, len(parts) + 1)
            if ".".join(parts[:index]) in modules
        }

    def imports(module: str) -> set[str]:
        tree = parsed[module]
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        dependencies = set()
        importer_names = {"__import__"}
        importlib_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "importlib":
                        importlib_names.add(alias.asname or alias.name)
                    dependencies.update(resolve(alias.name))
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    package = (
                        module
                        if modules[module].endswith("/__init__.py")
                        else module.rpartition(".")[0]
                    )
                    parts = package.split(".")
                    if not package or node.level > len(parts):
                        raise ValueError("unresolved_relative_module_owner")
                    base = ".".join(
                        parts[: len(parts) - node.level + 1] + ([base] if base else [])
                    )
                if base == "importlib":
                    importer_names.update(
                        alias.asname or alias.name
                        for alias in node.names
                        if alias.name == "import_module"
                    )
                # Composition selects this separately owned registry only for
                # official/legacy; exact route projection is checked elsewhere.
                if (
                    module == "miy_api.api_registry"
                    and base == "miy_api.official_api_registry"
                ):
                    parent = parents.get(node)
                    if not (
                        isinstance(parent, ast.If)
                        and isinstance(parent.test, ast.Compare)
                        and isinstance(parent.test.left, ast.Name)
                        and parent.test.left.id == "selected"
                        and len(parent.test.ops) == 1
                        and isinstance(parent.test.ops[0], ast.In)
                        and len(parent.test.comparators) == 1
                        and ast.literal_eval(parent.test.comparators[0])
                        == ("legacy", "official")
                        and isinstance(parents.get(parent), ast.FunctionDef)
                        and parents[parent].name == "router_specs"
                    ):
                        raise ValueError("unresolved_router_composition_owner")
                    continue
                dependencies.update(resolve(base))
                for alias in node.names:
                    if alias.name == "*":
                        raise ValueError("unresolved_wildcard_module_owner")
                    child = base + "." + alias.name
                    if child in modules:
                        dependencies.update(resolve(child))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dynamic = isinstance(node.func, ast.Name) and node.func.id in importer_names
            dynamic = dynamic or (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in importlib_names
                and node.func.attr == "import_module"
            )
            if not dynamic:
                continue
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                target = node.args[0].value
                if target.startswith("."):
                    raise ValueError("unresolved_dynamic_relative_module_owner")
                dependencies.update(resolve(target))
            elif (
                module == "miy_api.domains.ai.registry"
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "module_name"
                and len(node.keywords) == 1
                and node.keywords[0].arg == "fromlist"
                and ast.literal_eval(node.keywords[0].value)
                == ["register_ai_capabilities"]
            ):
                for target in capabilities:
                    dependencies.update(resolve(target))
            else:
                raise ValueError("unresolved_dynamic_module_owner")
        return dependencies

    # Core/common source, platform domains and platform task modules are roots.
    # The official registry is a selected owner inventory, not a platform router.
    pending = {
        module
        for module, name in modules.items()
        if name.startswith(SOURCE_ROOTS[:2])
        and not name.startswith(tuple(domains))
        and name not in tasks
        and module != "miy_api.official_api_registry"
    }
    reached = set()
    while pending:
        module = pending.pop()
        if module in reached:
            continue
        reached.add(module)
        pending.update(imports(module) - reached)
    return {modules[module] for module in reached}


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
    shared = set()
    if any(name.endswith(".py") for name in paths):
        shared = shared_consumers(python_sources(root, revision), *previous)
        shared.update(shared_consumers(python_sources(root, target), *current))
    if any(
        name.startswith(("apps/official-suite/src/", "packages/official-suite-web/"))
        for name in paths
    ):
        shared.update(shared_ui_consumers(ui_sources(root, revision)))
        shared.update(shared_ui_consumers(ui_sources(root, target)))
    assert_owned(paths, *current, shared)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 -- Fail closed without echoing reviewed source.
        print(
            "Official slice includes shared source or cannot prove ownership; use a coordinated full release.",
            file=sys.stderr,
        )
        sys.exit(1)
