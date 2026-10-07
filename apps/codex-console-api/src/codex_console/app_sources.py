"""Owner-selected app checkouts; manifests describe apps and never configure the host."""

import hashlib
import json
import os
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import git
from .errors import ConsoleError
from .storage import database_path


@lru_cache(maxsize=1)
def validator():
    return Draft202012Validator(
        json.loads(
            files("codex_console").joinpath("independent_app_schema.generated.json").read_text()
        )
    )


# Legacy slugs remain valid; independently registered apps use the canonical schema.
_INDEPENDENT_ID_PATTERN = validator().schema["properties"]["app_id"]["pattern"]
APP_ID_PATTERN = (
    r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*|"
    + _INDEPENDENT_ID_PATTERN.removeprefix("^").removesuffix("$")
    + r")$"
)


def repository_identity(value):
    """Compare credential-free HTTP/SSH repository identities without contacting them."""
    scp = re.fullmatch(r"git@([A-Za-z0-9.-]+):([A-Za-z0-9_./-]+)", value)
    if scp:
        host, path = scp.groups()
        port = None
    else:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "ssh")
            or not parsed.hostname
            or parsed.password
            or (parsed.username and parsed.scheme != "ssh")
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Invalid repository identity")
        host, path = parsed.hostname, parsed.path
        port = parsed.port
        if port in (None, 443 if parsed.scheme == "https" else 22):
            port = None
    path = path.strip("/").removesuffix(".git")
    if not path or any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("Invalid repository path")
    return host.lower(), port, path


def directory(root, relative):
    return root if relative == "." else git.safe_path(root, relative)


def require_source_root(settings, value):
    root = Path(value)
    if (
        not root.is_absolute()
        or root.resolve() != root
        or not root.is_dir()
        or not any(root.is_relative_to(allowed) for allowed in settings.app_source_roots)
    ):
        raise ConsoleError("app_source_denied", 403)
    settings.require_allowed_paths(root)
    protected = [
        *settings.protected_workspaces,
        database_path(settings.database_url),
        settings.attachment_cache.expanduser(),
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser(),
        Path.home() / ".agents",
        Path.home() / ".ssh",
        Path.home() / ".config",
    ]
    if any(
        root.is_relative_to(path.resolve()) or path.resolve().is_relative_to(root)
        for path in protected
    ):
        raise ConsoleError("app_source_denied", 403)
    if git.repository_root(root) != root:
        raise ConsoleError("app_source_invalid", 422)
    # Binding roots are ordinary checkouts. Console-created linked worktrees are
    # checked against this pinned metadata separately, never accepted as bindings.
    metadata = root / ".git"
    if not metadata.is_dir() or metadata.is_symlink():
        raise ConsoleError("app_source_denied", 403)
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        reported = Path(git.git(root, "rev-parse", "--path-format=absolute", flag).decode().strip())
        if reported != metadata or reported.resolve() != metadata:
            raise ConsoleError("app_source_denied", 403)
    require_git_policy(root)
    return root


def require_git_policy(root):
    # Git status/checkout can run configured conversion helpers or lazily fetch
    # missing objects. Only inspect configuration names; never return values.
    keys = (
        git.git(root, "config", "--name-only", "--list", limit=65536).decode().lower().splitlines()
    )
    if any(
        re.fullmatch(r"filter\..*\.(clean|smudge|process)|diff\..*\.textconv", key)
        or re.fullmatch(r"remote\..*\.(promisor|partialclonefilter)", key)
        or key == "extensions.partialclone"
        for key in keys
    ):
        raise ConsoleError("app_source_git_policy", 422)
    return root


def read_manifest(settings, root, app_id):
    root = require_source_root(settings, root)
    try:
        raw = git.read_worktree_file(root, "app.manifest.json", missing_ok=False)
        if len(raw) > 65536:
            raise ValueError("Manifest too large")
        manifest = json.loads(raw)
        validator().validate(manifest)
        if manifest["app_id"] != app_id:
            raise ValueError("Mismatched app identity")
        source = manifest["source"]
        if urlsplit(source["repository"]).scheme != "https":
            raise ValueError("Invalid manifest repository")
        remote = git.git(root, "remote", "get-url", "origin", limit=4096).decode().strip()
        if repository_identity(remote) != repository_identity(source["repository"]):
            raise ValueError("Mismatched repository identity")
        app_directory = directory(root, source.get("directory", "."))
        if not app_directory.is_dir():
            raise ValueError("Missing app directory")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        return manifest, digest
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        raise ConsoleError("app_source_invalid", 422) from None


def snapshot(binding):
    revision = (
        git.git(Path(binding.repository_root), "rev-parse", "--verify", "HEAD^{commit}")
        .decode()
        .strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ConsoleError("app_source_invalid", 422)
    return {
        "app_id": binding.app_id,
        "repository_root": binding.repository_root,
        "repository": binding.manifest["source"]["repository"],
        "directory": binding.manifest["source"].get("directory", "."),
        "manifest_digest": binding.manifest_digest,
        "version": binding.version,
        "revision": revision,
    }


def context_root(settings, context):
    source = (context or {}).get("source_binding")
    if not source:
        return settings.workspace
    root = Path(source["repository_root"])
    manifest, _ = read_manifest(settings, root, source["app_id"])
    # Edits may change app logic/display, but changing the source directory cannot
    # move a task that was already created. New tasks require a refreshed binding.
    if manifest["source"].get("directory", ".") != source["directory"]:
        raise ConsoleError("app_source_changed", 409)
    return directory(root, source["directory"])


def require_task_source(settings, task):
    source = (task.context or {}).get("source_binding")
    if not source:
        return
    root = require_source_root(settings, source["repository_root"])
    remote = git.git(root, "remote", "get-url", "origin", limit=4096).decode().strip()
    try:
        if repository_identity(remote) != repository_identity(source["repository"]):
            raise ValueError("Repository identity changed")
    except (ValueError, UnicodeError):
        raise ConsoleError("app_source_changed", 409) from None
    # Existing sessions can repair a deleted/malformed manifest. Their immutable
    # source identity and directory, not newly edited app instructions, own cwd.
    expected = directory(root, source["directory"])
    template_directory = (task.template_snapshot or {}).get("definition", {}).get("directory", ".")
    expected = directory(expected, template_directory)
    if task.worktree_owned:
        relative = expected.relative_to(Path(source["repository_root"]))
        worktree = settings.worktree_root / f"codex-{task.id}"
        if worktree.resolve() != worktree or git.repository_root(worktree) != worktree:
            raise ConsoleError("app_source_changed", 409)
        common = Path(
            git.git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
            .decode()
            .strip()
        )
        if common != root / ".git" or common.resolve() != common:
            raise ConsoleError("app_source_changed", 409)
        metadata = Path(git.git(worktree, "rev-parse", "--absolute-git-dir").decode().strip())
        if (
            metadata.resolve() != metadata
            or metadata.parent != common / "worktrees"
            or metadata.name != worktree.name
            or git.read_worktree_file(metadata, "gitdir", missing_ok=False).decode().strip()
            != str(worktree / ".git")
        ):
            raise ConsoleError("app_source_changed", 409)
        require_git_policy(worktree)
        expected = directory(worktree, relative.as_posix())
        settings.require_allowed_paths(expected)
    if Path(task.root) != expected or expected.resolve() != expected:
        raise ConsoleError("app_source_changed", 409)


def task_workspace(settings, task):
    if task.worktree_owned:
        return settings.worktree_root / f"codex-{task.id}"
    source = (task.context or {}).get("source_binding")
    return Path(source["repository_root"]) if source else settings.workspace


def registration_draft(settings, factory, project_id):
    """Observe a current source definition; this is not a build/source attestation."""
    return registration_snapshot(settings, factory, project_id)[0]


def registration_snapshot(settings, factory, project_id):
    """Keep local identity evidence internal for comparison across a bounded read."""
    from .delivery_tools import normalize_manifest
    from .models import AppSourceBinding, WorkbenchProject
    from .workbench_schemas import SourceRegistrationDraftOut

    def binding_state():
        # Each call uses a fresh snapshot. Holding a SQLite read transaction across
        # Git I/O would hide a concurrent, explicitly requested source rebind.
        with factory() as db:
            project = db.get(WorkbenchProject, project_id)
            if project is None:
                raise ConsoleError("not_found", 404)
            binding = db.get(AppSourceBinding, project.app_id)
            if binding is None:
                raise ConsoleError("app_source_unavailable", 422)
            return {
                "app_id": project.app_id,
                "reuse_decision": project.reuse_decision,
                "root": binding.repository_root,
                "version": binding.version,
                "manifest": binding.manifest,
                "manifest_digest": binding.manifest_digest,
            }

    selected = binding_state()
    root = require_source_root(settings, selected["root"])
    original_source = selected["manifest"]["source"]
    source_directory = directory(root, original_source.get("directory", "."))

    def identity():
        try:
            return tuple(
                (info.st_dev, info.st_ino)
                for info in (
                    root.stat(follow_symlinks=False),
                    (root / ".git").stat(follow_symlinks=False),
                    source_directory.stat(follow_symlinks=False),
                )
            )
        except OSError:
            raise ConsoleError("app_source_changed", 409) from None

    locations = identity()
    before = git.status(root)
    if before["changed"] or not re.fullmatch(r"[0-9a-f]{40}", before["head"] or ""):
        raise ConsoleError("app_source_dirty", 409)
    manifest, raw_digest = read_manifest(settings, root, selected["app_id"])
    try:
        if repository_identity(manifest["source"]["repository"]) != repository_identity(
            original_source["repository"]
        ) or manifest["source"].get("directory", ".") != original_source.get("directory", "."):
            raise ValueError("Source identity changed")
    except ValueError:
        raise ConsoleError("app_source_changed", 409) from None
    definition = normalize_manifest(manifest)
    # A status-only check can miss assume-unchanged/skip-worktree edits. Confirm
    # the exported definition also exists at this fixed commit. JSON formatting
    # and Git's line-ending conversion do not change the canonical definition.
    try:
        committed = json.loads(
            git.git(root, "cat-file", "blob", before["head"] + ":app.manifest.json", limit=65536)
        )
        validator().validate(committed)
        if normalize_manifest(committed) != definition:
            raise ValueError("Uncommitted manifest definition")
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        raise ConsoleError("app_source_dirty", 409) from None
    except ConsoleError as error:
        if error.code == "git_unavailable":
            # A present but ignored/untracked manifest is not part of this HEAD.
            raise ConsoleError("app_source_dirty", 409) from None
        raise
    current_manifest, current_digest = read_manifest(settings, root, selected["app_id"])
    after = git.status(root)
    require_source_root(settings, root)
    if (
        locations != identity()
        or before["head"] != after["head"]
        or raw_digest != current_digest
        or manifest != current_manifest
        or selected != binding_state()
    ):
        raise ConsoleError("app_source_changed", 409)
    if after["changed"]:
        raise ConsoleError("app_source_dirty", 409)
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    draft = SourceRegistrationDraftOut(
        project_id=project_id,
        binding_version=selected["version"],
        app_id=selected["app_id"],
        source_revision=before["head"],
        source_manifest_digest=raw_digest,
        definition_digest="sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        definition=definition,
    )
    return draft, selected, locations
