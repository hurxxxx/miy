"""Owner-selected core task environments; app executors keep their own boundaries."""

import asyncio
import contextlib
import json
import os
import re
import signal
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from . import git, store
from .errors import ConsoleError
from .models import Task

KINDS = ("general", "development", "branch", "existing_branch", "production")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z")


def selection(task):
    return (task.context or {}).get("task_environment")


def common_directory(root):
    return Path(
        git.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    ).resolve()


def root_for(settings, kind):
    root = {
        "general": settings.project_root,
        "development": settings.workspace,
        "branch": settings.worktree_root,
        "existing_branch": settings.worktree_root,
        "production": settings.production_workspace,
    }[kind]
    if root is None or (kind != "branch" and not root.is_dir()):
        raise ConsoleError("task_environment_unavailable", 409)
    if root.resolve() != root:
        raise ConsoleError("path_denied", 403)
    if kind == "production":
        if git.repository_root(root) != root or common_directory(root) != common_directory(
            settings.workspace
        ):
            raise ConsoleError("task_environment_unavailable", 409)
        # This explicit read-only environment is the only exception for the exact
        # configured production root. Generic/imported/app tasks stay protected.
        if any(
            root != p.resolve() and root.is_relative_to(p.resolve())
            for p in settings.protected_workspaces
        ):
            raise ConsoleError("path_denied", 403)
    else:
        settings.require_allowed_paths(root)
    if kind == "branch" and not settings.branch_setup_command:
        raise ConsoleError("branch_setup_unconfigured", 409)
    if kind == "existing_branch" and git.repository_root(settings.workspace) != settings.workspace:
        raise ConsoleError("task_environment_unavailable", 409)
    return root


def options(settings):
    result = []
    for kind in KINDS:
        try:
            root = root_for(settings, kind)
            available, reason = True, None
        except ConsoleError as error:
            root = {
                "general": settings.project_root,
                "development": settings.workspace,
                "branch": settings.worktree_root,
                "existing_branch": settings.worktree_root,
                "production": settings.production_workspace,
            }[kind]
            available, reason = False, error.code
        result.append(
            dict(
                kind=kind,
                root=str(root) if root else None,
                available=available,
                reason=reason,
                base_ref=settings.worktree_base_ref if kind == "branch" else None,
                read_only=kind == "production",
            )
        )
    return result


def registered_worktrees(settings, *, branch_name=None):
    """Only registered, named checkouts within this owner's worktree storage."""
    storage = root_for(settings, "existing_branch")
    records = git.git(settings.workspace, "worktree", "list", "--porcelain", "-z").split(b"\0\0")
    if len(records) > 201:
        raise ConsoleError("output_too_large", 409)
    workspace_common = common_directory(settings.workspace)
    result = []
    for record in records:
        fields = dict(field.partition(b" ")[::2] for field in record.split(b"\0") if field)
        branch = fields.get(b"branch", b"").decode("utf-8", "replace")
        if not branch.startswith("refs/heads/"):
            continue
        branch = branch.removeprefix("refs/heads/")
        if branch_name is not None and branch != branch_name:
            continue
        if branch in {"dev", "main", "master", "HEAD"} or len(branch) > 100:
            continue
        root = Path(os.fsdecode(fields.get(b"worktree", b"")))
        if (
            not root.is_absolute()
            or root == storage
            or not root.is_relative_to(storage)
            or root.resolve() != root
            or not root.is_dir()
            or b"prunable" in fields
        ):
            continue
        try:
            settings.require_allowed_paths(root)
            if (
                git.repository_root(root) != root
                or common_directory(root) != workspace_common
                or git.git(root, "symbolic-ref", "--short", "HEAD").decode().strip() != branch
            ):
                continue
        except ConsoleError:
            continue
        result.append(
            dict(
                branch=branch,
                root=str(root),
                available=b"locked" not in fields,
                reason="workspace_busy" if b"locked" in fields else None,
            )
        )
    return sorted(result, key=lambda row: row["branch"])


def worktree_options(settings, db):
    rows = registered_worktrees(settings)
    if not rows:
        return rows
    unfinished = {
        root
        for root, context in db.execute(
            select(Task.root, Task.context).where(
                Task.root.in_([row["root"] for row in rows]),
                Task.context["task_environment"]["kind"].as_string() == "branch",
            )
        )
        if context["task_environment"].get("preparation", {}).get("state") != "ready"
    }
    for row in rows:
        if row["root"] in unfinished:
            row.update(available=False, reason="task_environment_not_ready")
    return rows


def configure(settings, task, kind, branch_name=None, *, db=None):
    root = root_for(settings, kind)
    meta = {"kind": kind, "root": str(root), "read_only": kind == "production"}
    if kind == "existing_branch":
        chosen = next(
            (row for row in worktree_options(settings, db) if row["branch"] == branch_name), None
        )
        if chosen is None:
            raise ConsoleError("worktree_unavailable", 409)
        if not chosen["available"]:
            raise ConsoleError(chosen["reason"], 409)
        root = Path(chosen["root"])
        meta.update(root=str(root), branch=chosen["branch"])
    if kind == "branch":
        name = branch_name or f"work/{task.id}"
        if not BRANCH.fullmatch(name) or name in {"dev", "main", "master", "HEAD"}:
            raise ConsoleError("invalid_branch_name", 422)
        try:
            git.git(settings.workspace, "check-ref-format", "--branch", name)
        except ConsoleError:
            raise ConsoleError("invalid_branch_name", 422) from None
        if git.git(
            settings.workspace, "branch", "--list", "--format=%(refname:short)", name
        ).strip():
            raise ConsoleError("branch_exists", 409)
        revision = (
            git.git(
                settings.workspace,
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{settings.worktree_base_ref}^{{commit}}",
            )
            .decode()
            .strip()
        )
        root = root / f"codex-{task.id}"
        settings.require_allowed_paths(root)
        meta.update(
            root=str(root),
            branch=name,
            base_ref=settings.worktree_base_ref,
            base_revision=revision,
            checkout_prepared=False,
            preparation={"state": "pending", "step": "branch", "error_code": None},
        )
        task.status = "starting"
    task.root = str(root)
    task.context = {"task_environment": meta}


def require_task(settings, task, *, ready=True):
    meta = selection(task)
    if not meta:
        return False
    kind = meta.get("kind")
    if kind not in KINDS:
        raise ConsoleError("task_environment_changed", 409)
    configured = root_for(settings, kind)
    if kind == "existing_branch":
        branch_name = meta.get("branch")
        if not isinstance(branch_name, str) or not branch_name:
            raise ConsoleError("task_environment_changed", 409)
        chosen = next(
            iter(registered_worktrees(settings, branch_name=branch_name)),
            None,
        )
        if chosen is None or not chosen["available"]:
            raise ConsoleError("task_environment_changed", 409)
        expected = Path(chosen["root"])
    else:
        expected = configured / f"codex-{task.id}" if kind == "branch" else configured
    if (
        Path(task.root) != expected
        or meta.get("root") != str(expected)
        or expected.resolve() != expected
    ):
        raise ConsoleError("task_environment_changed", 409)
    if any(
        p and Path(p) != expected for p in (task.last_execution_root, task.previous_execution_root)
    ):
        raise ConsoleError("task_environment_changed", 409)
    if kind == "branch":
        if ready and meta.get("preparation", {}).get("state") != "ready":
            raise ConsoleError("task_environment_not_ready", 409)
        if meta.get("checkout_prepared"):
            if (
                git.repository_root(expected) != expected
                or common_directory(expected) != common_directory(settings.workspace)
                or git.git(expected, "symbolic-ref", "--short", "HEAD").decode().strip()
                != meta["branch"]
            ):
                raise ConsoleError("task_environment_changed", 409)
    return kind == "production"


def require_stage(task, stage):
    meta = selection(task) or {}
    if meta.get("kind") == "production" and stage != "plan":
        raise ConsoleError("production_read_only", 403)
    if meta.get("kind") == "branch" and meta.get("preparation", {}).get("state") != "ready":
        raise ConsoleError("task_environment_not_ready", 409)


def implementation_permissions(settings, task):
    meta = selection(task)
    if meta:
        try:
            if require_task(settings, task):
                return []
        except ConsoleError:
            return []
    return None


def git_status(task):
    meta = selection(task) or {}
    if meta.get("kind") == "general" or meta.get("preparation", {}).get("state") in {
        "pending",
        "preparing",
        "failed",
    }:
        return dict(
            available=False,
            root=task.root,
            branch=None,
            head=None,
            detached=False,
            upstream=None,
            ahead=None,
            behind=None,
            staged=0,
            unstaged=0,
            untracked=0,
            conflicts=0,
            changed=0,
            checked_at=datetime.now(UTC).isoformat(),
        )
    return None


def change_preparation(factory, task_id, state, step, error=None, **extra):
    with factory.begin() as db:
        task = store.require_task(db, task_id, locked=True)
        meta = dict(selection(task))
        meta.update(extra)
        meta["preparation"] = {"state": state, "step": step, "error_code": error}
        task.context = {**task.context, "task_environment": meta}
        task.status = "idle" if state == "ready" else "failed" if state == "failed" else "starting"
        task.error_code = error
        if state in {"ready", "failed"}:
            store.release(db, task_id)
        if meta.get("checkout_prepared"):
            task.worktree_owned = True
        store.changed(db, task, "task.environment.updated")


async def prepare(settings, factory, task_id, gate):
    process = None
    try:
        async with gate:
            with factory() as db:
                task = store.require_task(db, task_id)
                require_task(settings, task, ready=False)
                meta = dict(selection(task))
            change_preparation(factory, task_id, "preparing", "branch")
            if not meta["checkout_prepared"]:
                await asyncio.to_thread(
                    git.prepare_workspace,
                    settings.workspace,
                    task_id,
                    base_ref=meta["base_revision"],
                    worktree_root=settings.worktree_root,
                    validate_target=settings.require_allowed_paths,
                    branch_name=meta["branch"],
                )
                change_preparation(
                    factory, task_id, "preparing", "dependencies", checkout_prepared=True
                )
            else:
                change_preparation(factory, task_id, "preparing", "dependencies")
            env = {
                k: os.environ[k] for k in ("PATH", "LANG", "HOME", "PYTHONPATH") if k in os.environ
            }
            process = await asyncio.create_subprocess_exec(
                *settings.branch_setup_command,
                cwd=settings.workspace,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            payload = json.dumps(
                {
                    "task_id": task_id,
                    "root": meta["root"],
                    "source": str(settings.workspace),
                    "revision": meta["base_revision"],
                }
            ).encode()
            await asyncio.wait_for(process.communicate(payload), timeout=1800)
            if process.returncode:
                raise ConsoleError("branch_setup_failed", 409)
            with factory() as db:
                require_task(settings, store.require_task(db, task_id), ready=False)
            change_preparation(factory, task_id, "ready", "complete")
    except asyncio.CancelledError:
        change_preparation(factory, task_id, "failed", "interrupted", "branch_setup_interrupted")
        raise
    except Exception as error:
        change_preparation(
            factory,
            task_id,
            "failed",
            "setup",
            error.code if isinstance(error, ConsoleError) else "branch_setup_failed",
        )
    finally:
        if process and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()


def schedule(app, task_id):
    jobs = app.state.task_environment_jobs
    if task_id in jobs:
        return
    job = asyncio.create_task(
        prepare(app.state.settings, app.state.factory, task_id, app.state.task_environment_gate)
    )
    jobs[task_id] = job
    job.add_done_callback(lambda _: jobs.pop(task_id, None))


def recover_startup(factory):
    with factory() as db:
        ids = [
            task.id
            for task in db.scalars(select(Task).where(Task.executor == "session"))
            if (selection(task) or {}).get("preparation", {}).get("state")
            in {"pending", "preparing"}
        ]
    for task_id in ids:
        change_preparation(factory, task_id, "failed", "interrupted", "branch_setup_interrupted")


async def stop(app):
    jobs = list(app.state.task_environment_jobs.values())
    for job in jobs:
        job.cancel()
    await asyncio.gather(*jobs, return_exceptions=True)


def install(app, secured):
    from .schemas import TaskEnvironmentOption, TaskWorktreeOption

    @app.get(
        "/api/task-environments", dependencies=secured, response_model=list[TaskEnvironmentOption]
    )
    def task_environment_options():
        return options(app.state.settings)

    @app.get(
        "/api/task-environments/worktrees",
        dependencies=secured,
        response_model=list[TaskWorktreeOption],
    )
    def existing_worktree_options():
        with app.state.factory() as db:
            return worktree_options(app.state.settings, db)

    @app.post("/api/tasks/{task_id}/prepare", dependencies=secured)
    async def retry_task_environment(task_id):
        with app.state.factory.begin() as db:
            task = store.require_task(db, task_id, locked=True)
            require_task(app.state.settings, task, ready=False)
            meta = selection(task) or {}
            if meta.get("kind") != "branch":
                raise ConsoleError("invalid_input", 422)
            if (
                meta.get("preparation", {}).get("state") == "ready"
                or task_id in app.state.task_environment_jobs
            ):
                return {"ok": True}
            if task.status != "failed":
                raise ConsoleError("task_busy", 409)
            store.lease(
                db,
                task.id,
                workspace=Path(task.root),
                stage="implement",
                limit=app.state.settings.max_active_tasks,
            )
            task.status = "starting"
            store.changed(db, task, "task.environment.retry")
        schedule(app, task_id)
        return {"ok": True}
