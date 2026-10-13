"""Explicit display-only Git associations; never infer ownership from shell prose."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from . import git, store
from .errors import ConsoleError
from .models import TaskGitLink

TOOL_NAME = "miy_task_git"


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["register", "list"]
    root: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def needs_root(self):
        if (self.action == "register") != (self.root is not None):
            raise ValueError("Only registration requires an absolute checkout root")
        return self


def specs():
    return [
        {
            "type": "function",
            "name": TOOL_NAME,
            "description": "Register or list Git checkouts used by this task in its Changes panel. "
            "Register an additional checkout/worktree after creating or first using it. "
            "On resuming Git work, reviewing changes, or a related user request, list links "
            "and register missing paths verified relevant to the current work. "
            "Registration is idempotent; reuse known links and avoid redundant calls. "
            "Do not register unrelated checkouts or paths the user asked to leave unlinked. "
            "This only records a display association; it does not change cwd, permissions or Git. "
            "Supply its canonical absolute repository root, including detached worktrees.",
            "inputSchema": Arguments.model_json_schema(),
        }
    ]


def identity(root):
    if (
        not root.is_absolute()
        or root.resolve() != root
        or not root.is_dir()
        or (root / ".git").is_symlink()
    ):
        raise ConsoleError("path_denied", 403)
    if git.repository_root(root) != root:
        raise ConsoleError("git_root_required", 422)
    common = (
        git.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    )
    metadata = git.git(root, "rev-parse", "--absolute-git-dir").decode().strip()
    if Path(common).resolve() != Path(common) or Path(metadata).resolve() != Path(metadata):
        raise ConsoleError("path_denied", 403)
    return common, metadata


def validate(settings, task, root):
    settings.require_allowed_paths(root)
    if any((task.context or {}).get(key) for key in ("source_binding", "app_id", "project_id")):
        raise ConsoleError("path_denied", 403)
    allowed = (Path(task.root), settings.workspace, settings.worktree_root)
    if not any(root.is_relative_to(base) for base in allowed):
        raise ConsoleError("path_denied", 403)
    common, metadata = identity(root)
    settings.require_allowed_paths(common, metadata)
    return common, metadata


def initial_root(task):
    root = Path(task.root)
    if root.resolve() != root:
        raise ConsoleError("path_denied", 403)
    return git.repository_root(root)


def register(db, settings, task, root, source):
    path = Path(root)
    common, metadata = validate(settings, task, path)
    row = db.scalar(
        select(TaskGitLink).where(TaskGitLink.task_id == task.id, TaskGitLink.root == str(path))
    )
    if row:
        if (row.common_dir, row.git_dir) != (common, metadata):
            raise ConsoleError("git_link_changed", 409)
        return row.id
    try:
        if initial_root(task) == path:
            return "root"
    except ConsoleError:
        pass
    if len(list(db.scalars(select(TaskGitLink.id).where(TaskGitLink.task_id == task.id)))) >= 32:
        raise ConsoleError("git_link_limit", 422)
    row = TaskGitLink(
        task_id=task.id, root=str(path), common_dir=common, git_dir=metadata, source=source
    )
    db.add(row)
    db.flush()
    store.changed(db, task, "task.git_linked", details={"link_id": row.id})
    return row.id


def resolve(db, settings, task, link_id=None):
    if link_id is None or link_id == "root":
        return initial_root(task)
    row = db.get(TaskGitLink, link_id)
    if not row or row.task_id != task.id:
        raise ConsoleError("git_link_unavailable", 404)
    root = Path(row.root)
    if validate(settings, task, root) != (row.common_dir, row.git_dir):
        raise ConsoleError("git_link_changed", 409)
    return root


def listing(db, settings, task):
    result = []
    roots = set()
    try:
        root = initial_root(task)
        result.append(dict(id="root", root=str(root), source="initial", state=git.status(root)))
        roots.add(str(root))
    except ConsoleError as exc:
        kind = (task.context or {}).get("task_environment", {}).get("kind")
        if (
            kind in {"development", "production", "branch", "existing_branch"}
            or task.worktree_owned
        ):
            result.append(
                dict(id="root", root=task.root, source="initial", state=None, error_code=exc.code)
            )
    for row in db.scalars(
        select(TaskGitLink)
        .where(TaskGitLink.task_id == task.id)
        .order_by(TaskGitLink.created_at, TaskGitLink.id)
    ):
        if row.root in roots:
            continue
        entry = dict(id=row.id, root=row.root, source=row.source, state=None)
        try:
            entry["state"] = git.status(resolve(db, settings, task, row.id))
        except ConsoleError as exc:
            entry["error_code"] = exc.code
        result.append(entry)
    return result
