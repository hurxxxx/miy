"""Current committed registration metadata from the Task's actual workspace."""

import hashlib
import json
import re
from pathlib import Path

from jsonschema import ValidationError

from . import app_sources, git
from .delivery_tools import normalize_manifest
from .errors import ConsoleError
from .models import AppSourceBinding, Task, WorkbenchProject
from .workbench_schemas import SourceRegistrationDraftOut


def require_binding(db, task):
    if not task or (task.context or {}).get("purpose") != "registration":
        raise ConsoleError("registration_denied", 403)
    source = task.context.get("source_binding") or {}
    project = db.get(WorkbenchProject, task.context.get("project_id"))
    binding = db.get(AppSourceBinding, source.get("app_id"))
    if (
        not project
        or not binding
        or project.app_id != binding.app_id
        or task.context.get("app_id") != binding.app_id
        or source.get("version") != binding.version
        or source.get("repository_root") != binding.repository_root
        or source.get("repository") != binding.manifest["source"]["repository"]
        or source.get("directory") != binding.manifest["source"].get("directory", ".")
    ):
        raise ConsoleError("app_source_changed", 409)
    return task.root, task.worktree_owned, dict(source), project.id


def snapshot(settings, factory, task_id):
    def current():
        with factory() as db:
            task = db.get(Task, task_id)
            selected = require_binding(db, task)
            app_sources.require_task_source(settings, task)
            db.expunge(task)
            return task, selected

    task, selected = current()
    root = app_sources.task_workspace(settings, task)
    source = selected[2]
    app_directory = app_sources.directory(root, source["directory"])

    def identity():
        try:
            return tuple(
                (s.st_dev, s.st_ino)
                for s in (
                    root.stat(follow_symlinks=False),
                    (root / ".git").stat(follow_symlinks=False),
                    app_directory.stat(follow_symlinks=False),
                    Path(source["repository_root"]).stat(follow_symlinks=False),
                    (Path(source["repository_root"]) / ".git").stat(follow_symlinks=False),
                    Path(git.git(root, "rev-parse", "--absolute-git-dir").decode().strip()).stat(
                        follow_symlinks=False
                    ),
                )
            )
        except OSError:
            raise ConsoleError("app_source_changed", 409) from None

    def read():
        try:
            raw = git.read_worktree_file(root, "app.manifest.json", missing_ok=False)
            if len(raw) > 65536:
                raise ValueError()
            manifest = json.loads(raw)
            app_sources.validator().validate(manifest)
            if (
                manifest["app_id"] != source["app_id"]
                or manifest["source"].get("directory", ".") != source["directory"]
                or app_sources.repository_identity(manifest["source"]["repository"])
                != app_sources.repository_identity(source["repository"])
            ):
                raise ValueError()
            return manifest, "sha256:" + hashlib.sha256(raw).hexdigest()
        except (ValueError, UnicodeError, RecursionError, ValidationError):
            raise ConsoleError("app_source_invalid", 422) from None

    locations = identity()
    before = git.status(root)
    if before["changed"] or not re.fullmatch(r"[0-9a-f]{40}", before["head"] or ""):
        raise ConsoleError("app_source_dirty", 409)
    manifest, raw_digest = read()
    definition = normalize_manifest(manifest)
    try:
        committed = json.loads(
            git.git(root, "cat-file", "blob", before["head"] + ":app.manifest.json", limit=65536)
        )
        app_sources.validator().validate(committed)
        if normalize_manifest(committed) != definition:
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError, ValidationError, ConsoleError):
        raise ConsoleError("app_source_dirty", 409) from None
    if current()[1] != selected or identity() != locations or read() != (manifest, raw_digest):
        raise ConsoleError("app_source_changed", 409)
    after = git.status(root)
    if after["head"] != before["head"] or after["changed"]:
        raise ConsoleError("app_source_changed", 409)
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return SourceRegistrationDraftOut(
        project_id=selected[3],
        binding_version=source["version"],
        app_id=source["app_id"],
        source_revision=before["head"],
        source_manifest_digest=raw_digest,
        definition_digest=digest,
        definition=definition,
    )
