"""Durable single-owner workspaces on native Codex, Git and platform boundaries."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Request
from sqlalchemy import and_, exists, select, update

from . import agents, app_sources, git, store, workspace_git, workspace_gitlab
from .errors import ConsoleError
from .models import (
    Agent,
    AppSourceBinding,
    Operation,
    PendingRequest,
    ResourceLease,
    Task,
    WorkbenchProject,
    WorkbenchWorkspace,
    WorkspaceOperation,
    now,
)
from .workspace_schemas import WorkspaceAction, WorkspaceCreate, WorkspaceList, WorkspaceOut

IN_FLIGHT = ("pending", "running", "unknown")


def require(db, workspace_id):
    row = db.get(WorkbenchWorkspace, str(workspace_id))
    if row is None:
        raise ConsoleError("workspace_not_found", 404)
    return row


def snapshot(row):
    """Private server adapter input; this object is never returned by the UI API."""
    return {
        "id": row.id,
        "app_id": row.app_id,
        "repository_root": row.repository_root,
        "worktree_path": row.worktree_root,
        "app_directory": row.source_directory,
        "branch": row.branch,
        "base_revision": row.base_revision,
        "source_revision": row.source_revision,
        "profile_id": row.profile,
        "git_dir": row.git_dir,
        "common_dir": row.common_dir,
        "resources": row.environment or {},
        "preview_installation_id": (row.preview or {}).get("installation_id"),
        "preview": row.preview or {},
    }


def source_item(source):
    selected = source.get("managed_workspace") or {}
    return SimpleNamespace(
        **selected,
        worktree_root=selected.get("worktree_path"),
        source_directory=selected.get("app_directory"),
        repository=source.get("repository"),
    )


def detached(row):
    return SimpleNamespace(
        **{
            column.name: getattr(row, column.name)
            for column in WorkbenchWorkspace.__table__.columns
        }
    )


def output(db, row):
    return WorkspaceOut(
        **{
            name: getattr(row, name)
            for name in WorkspaceOut.model_fields
            if name not in ("preview", "integration", "cleanup", "operations")
        },
        preview=row.preview or {},
        integration=row.integration or {},
        cleanup=row.cleanup or {},
        operations=[
            {
                "operation_id": op.id,
                "kind": op.kind,
                "state": op.state,
                "source_revision": op.source_revision,
                "failure_code": op.failure_code,
                "unknown": op.state == "unknown",
                "continuable": op.state == "waiting"
                and op.source_revision == row.source_revision
                and not busy(db, row.id),
                "retryable": op.state in {"failed", "blocked"}
                and row.state != "cleaned"
                and not busy(db, row.id),
                "created_at": op.created_at,
                "updated_at": op.updated_at,
            }
            for op in db.scalars(
                select(WorkspaceOperation)
                .where(WorkspaceOperation.workspace_id == row.id)
                .order_by(WorkspaceOperation.created_at.desc())
                .limit(30)
            )
        ],
    )


def read(factory, workspace_id):
    with factory() as db:
        return output(db, require(db, workspace_id))


def busy(db, workspace_id):
    ids = list(db.scalars(select(Task.id).where(Task.workspace_id == workspace_id)))
    if not ids:
        return False
    # A native thread can be created before a first turn fails to submit. Its
    # idle root projection is not execution, but every other fence remains.
    before_first_turn = and_(
        Task.status == "failed",
        Task.turn_id.is_(None),
        Task.runtime_generation.is_(None),
        Task.thread_id.is_not(None),
        Agent.thread_id == Task.thread_id,
        Agent.parent_thread_id.is_(None),
        Agent.status == "idle",
        Agent.turn_id.is_(None),
        Agent.flags == [],
        exists().where(
            Operation.id == Task.current_operation_id,
            Operation.task_id == Task.id,
            Operation.state == "failed",
        ),
        ~exists().where(Operation.task_id == Task.id, Operation.state != "failed"),
    )
    return any(
        (
            db.scalar(
                select(Task.id)
                .where(Task.id.in_(ids), Task.status.in_((*store.ACTIVE, "uncertain")))
                .limit(1)
            ),
            db.scalar(
                select(Agent.thread_id)
                .join(Task, Agent.task_id == Task.id)
                .where(
                    Task.id.in_(ids),
                    Agent.status.not_in(agents.TERMINAL),
                    ~before_first_turn,
                )
                .limit(1)
            ),
            db.scalar(
                select(PendingRequest.id)
                .where(
                    PendingRequest.task_id.in_(ids),
                    PendingRequest.state.in_(("pending", "answering")),
                )
                .limit(1)
            ),
            db.scalar(
                select(Operation.id)
                .where(
                    Operation.task_id.in_(ids),
                    Operation.state.in_(("pending", "preparing", "submitting", "uncertain")),
                )
                .limit(1)
            ),
            db.scalar(select(ResourceLease.task_id).where(ResourceLease.task_id.in_(ids)).limit(1)),
        )
    )


def admission(db, task):
    if not task.workspace_id:
        return
    row = require(db, task.workspace_id)
    if row.state != "ready" or not row.admission_open:
        raise ConsoleError("workspace_stopped", 409)
    if (task.context or {}).get("workspace_id") != row.id:
        raise ConsoleError("workspace_source_changed", 409)


def context(settings, db, value):
    row = require(db, value["workspace_id"])
    if not settings.managed_workspaces_enabled or row.state != "ready" or not row.admission_open:
        raise ConsoleError("workspace_stopped", 409)
    if value.get("project_id") not in (None, row.project_id) or value.get("app_id") not in (
        None,
        row.app_id,
    ):
        raise ConsoleError("invalid_input", 422)
    if (
        value.get("purpose", "development") not in ("development", "registration")
        or value.get("installation_id")
        or value.get("maintenance_id")
    ):
        raise ConsoleError("workspace_task_denied", 403)
    project = db.get(WorkbenchProject, row.project_id)
    root, app, _ = workspace_git.validate(settings, row)
    from . import workspace_environment
    from .remote_environments import fingerprint

    environment = workspace_environment.environment_for(settings, snapshot(row))
    source = {
        "workspace_id": row.id,
        "app_id": row.app_id,
        "repository_root": str(root),
        "repository": row.repository,
        "directory": row.source_directory,
        "executor_root": str(app),
        "manifest_digest": row.source_digest,
        "version": row.version,
        "revision": row.source_revision,
        "remote_environment_key": environment.key,
        "remote_environment_digest": fingerprint(environment),
        "managed_workspace": {
            key: val
            for key, val in snapshot(row).items()
            if key not in ("resources", "preview_installation_id", "preview")
        },
    }
    return {
        **value,
        "workspace_id": row.id,
        "project_id": row.project_id,
        "app_id": row.app_id,
        "project_summary": project.summary,
        "reuse_decision": project.reuse_decision,
        "reuse_notes": project.reuse_notes,
        "source_binding": source,
        "app_title": project.title,
        "source_paths": [row.source_directory],
        "release_unit": None,
    }


def reserve(factory, workspace_id, kind, body, *, source_revision=None):
    operation_id = str(body.operation_id)
    with factory.begin() as db:
        row = require(db, workspace_id)
        existing = db.get(WorkspaceOperation, operation_id)
        if existing:
            if existing.workspace_id != row.id or (
                existing.kind != kind and (existing.kind, kind) != ("auto_refresh", "refresh")
            ):
                raise ConsoleError("conflict", 409)
            if existing.state != "waiting":
                return detached(row), existing.id, False
            if row.version != body.expected_version:
                raise ConsoleError("conflict", 409)
            if kind == "cleanup" and (row.integration or {}).get("state") != "succeeded":
                raise ConsoleError("workspace_not_integrated", 409)
            if (
                kind in {"refresh", "integrate"}
                and row.state != "ready"
                and (row.integration or {}).get("state") != "succeeded"
            ):
                raise ConsoleError("workspace_stopped", 409)
            if (
                existing.source_revision != row.source_revision
                or busy(db, row.id)
                or db.scalar(
                    select(WorkspaceOperation.id)
                    .where(
                        WorkspaceOperation.workspace_id == row.id,
                        WorkspaceOperation.id != existing.id,
                        WorkspaceOperation.state.in_(IN_FLIGHT),
                    )
                    .limit(1)
                )
            ):
                raise ConsoleError("workspace_busy", 409)
            existing.state = "running"
            existing.updated_at = now()
            row.admission_open = False
            row.version += 1
            db.flush()
            item = detached(row)
            item.continuing = True
            return item, existing.id, True
        if row.version != body.expected_version:
            raise ConsoleError("conflict", 409)
        if db.scalar(
            select(WorkspaceOperation.id)
            .where(
                WorkspaceOperation.workspace_id == row.id, WorkspaceOperation.state.in_(IN_FLIGHT)
            )
            .limit(1)
        ):
            raise ConsoleError("workspace_operation_unknown", 409)
        if row.state == "cleaned":
            raise ConsoleError("workspace_cleaned", 409)
        if (
            kind in {"refresh", "integrate"}
            and row.state != "ready"
            and (row.integration or {}).get("state") != "succeeded"
        ):
            raise ConsoleError("workspace_stopped", 409)
        if kind != "stop" and busy(db, row.id):
            raise ConsoleError("workspace_busy", 409)
        if kind == "cleanup" and (row.integration or {}).get("state") != "succeeded":
            raise ConsoleError("workspace_not_integrated", 409)
        # A new explicit intent supersedes only known waiting work for an old
        # source. Keep its remote receipt; pending/unknown work still blocks above.
        for previous in db.scalars(
            select(WorkspaceOperation).where(
                WorkspaceOperation.workspace_id == row.id,
                WorkspaceOperation.state == "waiting",
            )
        ):
            if previous.source_revision != row.source_revision:
                previous.state = "blocked"
                previous.failure_code = "workspace_source_changed"
                previous.updated_at = now()
        payload = {
            "workspace_id": row.id,
            "kind": kind,
            "version": body.expected_version,
            "source_revision": source_revision or row.source_revision,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind=kind,
                digest=digest,
                state="running",
                source_revision=source_revision or row.source_revision,
            )
        )
        if kind == "integrate" and (row.integration or {}).get("mr_id"):
            db.flush()
            db.get(WorkspaceOperation, operation_id).receipt = dict(row.integration)
        row.admission_open = False
        row.state = (
            "stopping" if kind == "stop" else "cleanup_pending" if kind == "cleanup" else row.state
        )
        row.version += 1
        row.updated_at = now()
        db.flush()
        return detached(row), operation_id, True


def persist(
    factory,
    workspace_id,
    operation_id,
    *,
    receipt=None,
    operation_state=None,
    unknown_updated_at=None,
    **values,
):
    with factory.begin() as db:
        if unknown_updated_at is not None:
            # A GET may finish after another observer or an approved continuation.
            # Claim only its unchanged unknown snapshot in this same transaction.
            claimed = db.execute(
                update(WorkspaceOperation)
                .where(
                    WorkspaceOperation.id == operation_id,
                    WorkspaceOperation.workspace_id == workspace_id,
                    WorkspaceOperation.state == "unknown",
                    WorkspaceOperation.updated_at == unknown_updated_at,
                )
                .values(updated_at=now())
            )
            if claimed.rowcount != 1:
                return
        row = require(db, workspace_id)
        operation = db.get(WorkspaceOperation, operation_id)
        if not operation or operation.workspace_id != row.id:
            raise ConsoleError("conflict", 409)
        if receipt is not None:
            operation.receipt = receipt
        if operation_state is not None:
            operation.state = operation_state
        operation.updated_at = row.updated_at = now()
        for key, value in values.items():
            setattr(row, key, value)
        if "source_revision" in values:
            operation.source_revision = values["source_revision"]
        row.version += 1


async def environment_action(settings, item, kind, operation_id, revision=None, *, factory=None):
    from . import workspace_environment

    function = getattr(workspace_environment, kind)
    selected = snapshot(item)
    if factory is not None:
        with factory() as db:
            selected["operation_receipt"] = dict(
                db.get(WorkspaceOperation, operation_id).receipt or {}
            )

        def record(evidence):
            with factory.begin() as db:
                operation = db.get(WorkspaceOperation, operation_id)
                operation.receipt = {**(operation.receipt or {}), "core": evidence}
                operation.updated_at = now()
            selected["operation_receipt"]["core"] = evidence

        selected["record"] = record
    values = (settings, selected)
    if kind == "refresh":
        return await function(*values, operation_id, revision)
    if kind == "integrate":
        return await function(*values, operation_id, revision)
    return await function(*values)


def environment_values(result):
    if not isinstance(result, dict):
        raise ConsoleError("workspace_environment_unavailable", 503)
    values = {}
    if "environment" in result:
        values["environment"] = result["environment"]
    if "preview" in result:
        values["preview"] = result["preview"]
    return values


def failure(factory, item, operation_id, error, *, unknown=False):
    code = error.code if isinstance(error, ConsoleError) else "workspace_environment_unavailable"
    persist(
        factory,
        item.id,
        operation_id,
        operation_state="unknown" if unknown else "failed",
        failure_code=code,
    )
    with factory.begin() as db:
        row = require(db, item.id)
        op = db.get(WorkspaceOperation, operation_id)
        op.failure_code = code
        # Uncertain external mutations close admission until explicit reconciliation.
        if (
            not unknown
            and row.state == "ready"
            and (row.integration or {}).get("state") not in {"merged", "succeeded"}
        ):
            row.admission_open = True


async def create(settings, factory, project_id, body):
    if not settings.managed_workspaces_enabled:
        raise ConsoleError("workspace_unconfigured", 422)
    operation_id = str(body.operation_id)
    workspace_id = str(uuid5(NAMESPACE_URL, "miy-workspace:" + operation_id))
    original = workspace_git.repository(settings)
    remote = git.git(original, "remote", "get-url", "origin", limit=4096).decode().strip()
    # The manifest contract uses HTTPS identity even when native Git uses SSH.
    host, port, path = app_sources.repository_identity(remote)
    repository = "https://" + host + (":" + str(port) if port else "") + "/" + path
    with factory.begin() as db:
        project = db.get(WorkbenchProject, str(project_id))
        if project is None:
            raise ConsoleError("app_not_found", 404)
        existing = db.get(WorkspaceOperation, operation_id)
        if existing:
            row = require(db, existing.workspace_id)
            if (
                existing.kind != "create"
                or row.project_id != project.id
                or existing.digest != hashlib.sha256(body.model_dump_json().encode()).hexdigest()
            ):
                raise ConsoleError("conflict", 409)
            return output(db, row)
        relative = "personal-apps/" + project.app_id
        row = WorkbenchWorkspace(
            id=workspace_id,
            project_id=project.id,
            app_id=project.app_id,
            title=body.title or project.title,
            profile=body.profile,
            repository_root=str(original),
            repository=repository,
            source_directory=relative,
            worktree_root=str(settings.worktree_root / "managed" / workspace_id),
            common_dir=str(original / ".git"),
            branch="feature/wb-" + project.app_id[:80] + "-" + workspace_id[:8],
            auto_refresh=body.auto_refresh,
        )
        db.add(row)
        db.flush()
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="create",
                digest=hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
                state="running",
            )
        )
        db.flush()
        binding = db.get(AppSourceBinding, project.app_id)
        initial_source = (
            None
            if binding is None
            else {
                "repository_root": binding.repository_root,
                "directory": binding.manifest["source"].get("directory", "."),
            }
        )
        item, selected_project = (
            detached(row),
            SimpleNamespace(
                id=project.id,
                title=project.title,
                reuse_decision=project.reuse_decision,
                initial_source=initial_source,
            ),
        )
    try:
        source = await asyncio.to_thread(workspace_git.create, settings, item, selected_project)
        persist(
            factory,
            item.id,
            operation_id,
            **{key: value for key, value in source.items() if key != "created"},
        )
        for key, value in source.items():
            setattr(item, key, value)
        result = await environment_action(settings, item, "prepare", operation_id, factory=factory)
        ready = result.get("state") == "ready"
        persist(
            factory,
            item.id,
            operation_id,
            operation_state="unknown"
            if result.get("operation_unknown")
            else "succeeded"
            if ready
            else "failed",
            **environment_values(result),
            admission_open=ready and not result.get("operation_unknown"),
            failure_code=result.get("failure_code"),
            **{"state": "ready" if ready else "error"},
        )
    except asyncio.CancelledError:
        failure(
            factory,
            item,
            operation_id,
            ConsoleError("workspace_operation_unknown", 409),
            unknown=True,
        )
        raise
    except Exception as error:
        persist(
            factory,
            item.id,
            operation_id,
            git_dir=item.git_dir,
            base_revision=item.base_revision,
            source_revision=item.source_revision,
        )
        uncertain = isinstance(error, ConsoleError) and error.code == "workspace_operation_unknown"
        failure(factory, item, operation_id, error, unknown=uncertain)
        persist(factory, item.id, operation_id, **{"state": "error"})
    return read(factory, item.id)


def queue_refresh(db, task, turn_id):
    if not task.workspace_id:
        return
    row = require(db, task.workspace_id)
    if not row.auto_refresh or row.state != "ready" or not row.admission_open:
        return
    operation_id = str(uuid5(NAMESPACE_URL, f"miy-workspace-refresh:{row.id}:{task.id}:{turn_id}"))
    if db.get(WorkspaceOperation, operation_id):
        return
    if db.scalar(
        select(WorkspaceOperation.id)
        .where(WorkspaceOperation.workspace_id == row.id, WorkspaceOperation.state.in_(IN_FLIGHT))
        .limit(1)
    ):
        return
    db.add(
        WorkspaceOperation(
            id=operation_id,
            workspace_id=row.id,
            kind="auto_refresh",
            state="pending",
            source_revision=row.source_revision,
            digest=hashlib.sha256((row.id + ":" + task.id + ":" + turn_id).encode()).hexdigest(),
            receipt={"task_id": task.id, "turn_id": turn_id, "checkpoint_pending": True},
        )
    )
    row.admission_open = False
    # Checkpointing does not change the last verified app runtime. Keep that
    # evidence until the saved source shows that another deployment is needed.
    row.version += 1
    row.updated_at = now()


async def finish_refresh(settings, factory, workspace_id):
    """One finite lifecycle action after native completion; no model or retry loop."""
    with factory.begin() as db:
        row = require(db, workspace_id)
        operation = db.scalar(
            select(WorkspaceOperation)
            .where(
                WorkspaceOperation.workspace_id == row.id,
                WorkspaceOperation.kind == "auto_refresh",
                WorkspaceOperation.state == "pending",
            )
            .limit(1)
        )
        if not operation or busy(db, row.id) or row.state != "ready":
            return
        operation.state = "running"
        operation.updated_at = now()
        item, operation_id = detached(row), operation.id
    try:
        saved = await asyncio.to_thread(workspace_git.checkpoint, settings, item)
        with factory.begin() as db:
            current = require(db, item.id)
            selected = db.get(WorkspaceOperation, operation_id)
            if (
                selected is None
                or selected.workspace_id != current.id
                or selected.kind != "auto_refresh"
                or selected.state != "running"
                or selected.source_revision != item.source_revision
            ):
                return
            code = (
                "workspace_source_changed"
                if current.source_revision != item.source_revision
                else "workspace_stopped"
                if current.state != "ready"
                else "workspace_busy"
                if busy(db, current.id)
                else "workspace_operation_unknown"
                if db.scalar(
                    select(WorkspaceOperation.id)
                    .where(
                        WorkspaceOperation.workspace_id == current.id,
                        WorkspaceOperation.id != operation_id,
                        WorkspaceOperation.state.in_(IN_FLIGHT),
                    )
                    .limit(1)
                )
                else None
            )
            if code:
                # A later stop or uncertain operation cannot be turned into a
                # successful runtime by this earlier checkpoint observation.
                selected.state = "blocked"
                selected.failure_code = code
                selected.updated_at = now()
                return
            for key in ("source_revision", "source_manifest", "source_digest"):
                setattr(current, key, saved[key])
            selected.source_revision = saved["source_revision"]
            selected.receipt = {**(selected.receipt or {}), "checkpoint_pending": False}
            selected.updated_at = current.updated_at = now()
            current.version += 1
            preview = current.preview or {}
            if (
                preview.get("state") == "ready"
                and preview.get("runtime_revision") == saved["source_revision"]
            ):
                selected.state = "succeeded"
                selected.failure_code = current.failure_code = None
                current.admission_open = True
                return
            current.preview = {**preview, "state": "preparing"}
            item.preview = current.preview
        item.source_revision = saved["source_revision"]
        item.source_manifest, item.source_digest = saved["source_manifest"], saved["source_digest"]
        result = await environment_action(
            settings, item, "refresh", operation_id, item.source_revision, factory=factory
        )
        ready = result.get("state") == "ready"
        persist(
            factory,
            item.id,
            operation_id,
            operation_state="succeeded"
            if ready
            else "unknown"
            if result.get("state") == "unknown"
            else "blocked",
            **environment_values(result),
            admission_open=result.get("state") != "unknown",
            failure_code=result.get("failure_code"),
        )
    except asyncio.CancelledError:
        failure(
            factory,
            item,
            operation_id,
            ConsoleError("workspace_operation_unknown", 409),
            unknown=True,
        )
        raise
    except Exception as error:
        failure(
            factory,
            item,
            operation_id,
            error,
            unknown=isinstance(error, ConsoleError) and error.code == "workspace_operation_unknown",
        )


def task_checkpoint(settings, factory, task, check):
    with factory() as db:
        row = require(db, task.workspace_id)
        item = detached(row)
    saved = workspace_git.checkpoint(settings, item, check=check)
    with factory.begin() as db:
        row = require(db, task.workspace_id)
        if row.source_revision != item.source_revision:
            raise ConsoleError("workspace_source_changed", 409)
        for key in ("source_revision", "source_manifest", "source_digest"):
            setattr(row, key, saved[key])
        row.version += 1
        row.updated_at = now()
    return {"source_revision": saved["source_revision"], "created": saved["created"]}


async def stop_tasks(app, item):
    factory = app.state.factory
    with factory() as db:
        tasks = list(db.scalars(select(Task).where(Task.workspace_id == item.id)))
    for task in tasks:
        with factory() as db:
            current = db.get(Task, task.id)
            active = current is not None and (
                current.status in (*store.ACTIVE, "uncertain")
                or agents.busy_descendants(db, task.id)
            )
        # Historical idle Tasks do not need a live executor. A partial cleanup
        # may already have stopped that SDK; all remaining fences are checked below.
        if not active:
            continue
        runtime = app.state.runtime.for_task(task.id)
        await runtime.refresh_agents(task.id)
        with factory() as db:
            current = db.get(Task, task.id)
            active = current is not None and (
                current.status in (*store.ACTIVE, "uncertain")
                or agents.busy_descendants(db, task.id)
            )
        if active:
            await runtime.interrupt(task.id)
    with factory() as db:
        if busy(db, item.id):
            raise ConsoleError("workspace_busy", 409)


async def action(app, workspace_id, kind, body):
    settings, factory = app.state.settings, app.state.factory
    if not settings.managed_workspaces_enabled:
        raise ConsoleError("workspace_unconfigured", 422)
    item, operation_id, claimed = reserve(factory, workspace_id, kind, body)
    if not claimed:
        return read(factory, workspace_id)
    try:
        if getattr(item, "continuing", False) and kind in {"refresh", "integrate"}:
            root, _, _ = workspace_git.validate(settings, item)
            with factory() as db:
                saved_receipt = db.get(WorkspaceOperation, operation_id).receipt or {}
            if workspace_git.revision(root) != item.source_revision or (
                git.status(root)["changed"] and not saved_receipt.get("checkpoint_pending")
            ):
                raise ConsoleError("workspace_source_changed", 409)
        if kind == "integrate" and (item.integration or {}).get("state") == "succeeded":
            await cleanup(app, item, operation_id)
        elif kind == "stop":
            await stop_tasks(app, item)
            result = await environment_action(settings, item, "stop", operation_id, factory=factory)
            if result.get("state") != "stopped":
                persist(factory, item.id, operation_id, **environment_values(result))
                raise ConsoleError(
                    result.get("failure_code") or "workspace_environment_unavailable", 409
                )
            persist(
                factory,
                item.id,
                operation_id,
                operation_state="succeeded",
                **environment_values(result),
                admission_open=False,
                failure_code=None,
                **{"state": "stopped"},
            )
        elif kind == "resume":
            if (
                item.state == "error"
                and item.base_revision is None
                and item.source_revision is None
                and item.git_dir is None
            ):
                with factory() as db:
                    creation = db.scalar(
                        select(WorkspaceOperation).where(
                            WorkspaceOperation.workspace_id == item.id,
                            WorkspaceOperation.kind == "create",
                        )
                    )
                    if creation is None or creation.state != "failed":
                        raise ConsoleError("workspace_operation_unknown", 409)
                    project = db.get(WorkbenchProject, item.project_id)
                    if project is None:
                        raise ConsoleError("app_not_found", 404)
                    binding = db.get(AppSourceBinding, item.app_id)
                    selected_project = SimpleNamespace(
                        id=project.id,
                        title=project.title,
                        reuse_decision=project.reuse_decision,
                        initial_source=None
                        if binding is None
                        else {
                            "repository_root": binding.repository_root,
                            "directory": binding.manifest["source"].get("directory", "."),
                        },
                    )
                source = await asyncio.to_thread(
                    workspace_git.create, settings, item, selected_project
                )
                persist(
                    factory,
                    item.id,
                    operation_id,
                    **{key: value for key, value in source.items() if key != "created"},
                )
                for key, value in source.items():
                    setattr(item, key, value)
            else:
                workspace_git.validate(settings, item)
            result = await environment_action(
                settings,
                item,
                "prepare" if item.state == "error" else "resume",
                operation_id,
                factory=factory,
            )
            ready = result.get("state") == "ready"
            persist(
                factory,
                item.id,
                operation_id,
                operation_state="unknown"
                if result.get("operation_unknown") or result.get("state") == "unknown"
                else "succeeded"
                if ready
                else "failed",
                **environment_values(result),
                admission_open=ready and not result.get("operation_unknown"),
                failure_code=result.get("failure_code"),
                **{"state": "ready" if ready else "error"},
            )
        elif kind == "refresh":
            saved = await asyncio.to_thread(workspace_git.checkpoint, settings, item)
            persist(
                factory,
                item.id,
                operation_id,
                **{key: val for key, val in saved.items() if key != "created"},
            )
            item.source_revision = saved["source_revision"]
            item.source_manifest, item.source_digest = (
                saved["source_manifest"],
                saved["source_digest"],
            )
            result = await environment_action(
                settings, item, "refresh", operation_id, item.source_revision, factory=factory
            )
            ready = result.get("state") == "ready"
            persist(
                factory,
                item.id,
                operation_id,
                operation_state="succeeded"
                if ready
                else "unknown"
                if result.get("state") == "unknown"
                else "blocked",
                **environment_values(result),
                admission_open=result.get("state") != "unknown",
                failure_code=result.get("failure_code"),
            )
        elif kind == "integrate":
            with factory() as db:
                operation = db.get(WorkspaceOperation, operation_id)
                op = SimpleNamespace(
                    id=operation.id,
                    receipt=operation.receipt,
                    source_revision=operation.source_revision,
                )

            def remote_receipt(receipt, state):
                values = (
                    {"integration": receipt, "admission_open": False}
                    if receipt.get("state") == "merged"
                    else {}
                )
                persist(
                    factory, item.id, operation_id, receipt=receipt, operation_state=state, **values
                )

            result = await workspace_gitlab.integrate(settings, item, op, remote_receipt)
            persist(
                factory,
                item.id,
                operation_id,
                receipt=result,
                operation_state="waiting"
                if result.get("state") == "reviewing"
                else "unknown"
                if result.get("state") == "unknown"
                else "running"
                if result.get("state") == "merged"
                else "blocked",
                integration=result,
                admission_open=result.get("state") in ("reviewing", "blocked"),
            )
            if result.get("state") == "merged":
                delivered = await environment_action(
                    settings,
                    item,
                    "integrate",
                    operation_id,
                    result["merged_revision"],
                    factory=factory,
                )
                success = delivered.get("state") == "ready"
                integration = {
                    **result,
                    "state": "succeeded" if success else "merged",
                    "dev_runtime_revision": delivered.get("dev_runtime_revision"),
                    "failure_code": delivered.get("failure_code"),
                }
                persist(
                    factory,
                    item.id,
                    operation_id,
                    operation_state="succeeded"
                    if success
                    else "unknown"
                    if delivered.get("state") == "unknown" or delivered.get("operation_unknown")
                    else "blocked",
                    integration=integration,
                    admission_open=False,
                )
                if success:
                    with factory() as db:
                        current = detached(require(db, item.id))
                    await cleanup(app, current, operation_id)
        elif kind == "cleanup":
            await cleanup(app, item, operation_id)
        else:
            raise ConsoleError("invalid_input", 422)
    except asyncio.CancelledError:
        failure(
            factory,
            item,
            operation_id,
            ConsoleError("workspace_operation_unknown", 409),
            unknown=True,
        )
        raise
    except Exception as error:
        # Native remote adapters mark attempts before dispatch. Preserve ambiguous
        # remote outcomes; local known failures may be retried explicitly.
        with factory() as db:
            receipt = db.get(WorkspaceOperation, operation_id).receipt or {}
        uncertain = (
            (isinstance(error, ConsoleError) and error.code == "workspace_operation_unknown")
            or kind in {"integrate", "cleanup"}
            and any(
                receipt.get(key)
                for key in (
                    "push_attempted",
                    "create_attempted",
                    "merge_attempted",
                    "cleanup_remote_attempted",
                )
            )
        )
        if kind == "stop" and isinstance(error, ConsoleError) and error.code == "workspace_busy":
            persist(
                factory, item.id, operation_id, operation_state="waiting", failure_code=error.code
            )
        else:
            failure(factory, item, operation_id, error, unknown=uncertain)
    return read(factory, workspace_id)


async def cleanup(app, item, operation_id):
    settings, factory = app.state.settings, app.state.factory
    if (item.integration or {}).get("state") != "succeeded":
        raise ConsoleError("workspace_not_integrated", 409)
    persist(
        factory,
        item.id,
        operation_id,
        operation_state="running",
        state="cleanup_pending",
        cleanup={"state": "cleanup_pending"},
        admission_open=False,
    )
    await stop_tasks(app, item)
    stopped = await environment_action(settings, item, "stop", operation_id, factory=factory)
    if stopped.get("state") != "stopped":
        raise ConsoleError("workspace_busy", 409)
    result = await environment_action(settings, item, "cleanup", operation_id, factory=factory)
    if result.get("state") != "cleaned":
        raise ConsoleError(result.get("failure_code") or "workspace_cleanup_incomplete", 409)
    persist(factory, item.id, operation_id, **environment_values(result))
    if result.get("source_handoff_complete") is not True:
        raise ConsoleError("workspace_source_handoff_required", 409)

    def remote_cleanup_receipt(attempted):
        with factory.begin() as db:
            operation = db.get(WorkspaceOperation, operation_id)
            operation.receipt = {**(operation.receipt or {}), "cleanup_remote_attempted": attempted}
            operation.updated_at = now()

    await workspace_gitlab.remove_remote(settings, item, remote_cleanup_receipt)
    await asyncio.to_thread(workspace_git.remove, settings, item)
    persist(
        factory,
        item.id,
        operation_id,
        operation_state="succeeded",
        cleanup={"state": "cleaned"},
        admission_open=False,
        state="cleaned",
    )


def recover_startup(factory):
    """The session process is the sole workspace operator; loss closes admission."""
    with factory.begin() as db:
        for operation in db.scalars(
            select(WorkspaceOperation).where(WorkspaceOperation.state.in_(("running", "pending")))
        ):
            pending = operation.state == "pending" and operation.kind == "auto_refresh"
            operation.state = "waiting" if pending else "unknown"
            operation.failure_code = (
                "workspace_refresh_pending" if pending else "workspace_operation_unknown"
            )
            operation.updated_at = now()
            row = require(db, operation.workspace_id)
            row.admission_open = False
            row.failure_code = operation.failure_code
            row.version += 1


async def observe(settings, factory, workspace_id):
    from . import workspace_environment

    with factory() as db:
        row = require(db, workspace_id)
        operation = db.scalar(
            select(WorkspaceOperation)
            .where(
                WorkspaceOperation.workspace_id == row.id,
                WorkspaceOperation.state == "unknown",
            )
            .order_by(WorkspaceOperation.created_at.desc())
            .limit(1)
        )
        if not operation:
            return output(db, row)
        item = detached(row)
        op = SimpleNamespace(
            id=operation.id,
            kind=operation.kind,
            source_revision=operation.source_revision,
            receipt=dict(operation.receipt or {}),
            updated_at=operation.updated_at,
            cleanup_quiescent=row.state == "cleanup_pending"
            and not row.admission_open
            and not busy(db, row.id)
            and db.scalar(
                select(WorkspaceOperation.id)
                .where(
                    WorkspaceOperation.workspace_id == row.id,
                    WorkspaceOperation.id != operation.id,
                    WorkspaceOperation.state.in_(IN_FLIGHT),
                )
                .limit(1)
            )
            is None,
        )

    def persist_observed(**values):
        persist(factory, item.id, op.id, unknown_updated_at=op.updated_at, **values)

    try:
        # Merely observing a remote result never pushes, creates an MR, or deploys.
        if (
            op.kind in {"integrate", "cleanup"}
            and (item.integration or {}).get("state") == "succeeded"
        ):
            if op.receipt.get("cleanup_remote_attempted"):
                if await workspace_gitlab.cleanup_observed(settings, item):
                    persist_observed(
                        receipt={**op.receipt, "cleanup_remote_attempted": False},
                        operation_state="waiting",
                        failure_code=None,
                        admission_open=False,
                    )
            else:
                selected = {
                    **snapshot(item),
                    "operation_receipt": op.receipt,
                    "cleanup_quiescent": op.cleanup_quiescent,
                }
                observed = await workspace_environment.observe(
                    settings, selected, op.id, "cleanup", op.source_revision
                )
                if observed:
                    persist_observed(
                        operation_state="waiting",
                        failure_code=None,
                        admission_open=False,
                    )
        elif op.kind == "integrate" and (item.integration or {}).get("state") != "merged":
            observed = await workspace_gitlab.observe(settings, item, op)
            if observed:
                persist_observed(
                    receipt=observed,
                    integration=observed,
                    operation_state="waiting",
                    failure_code=None,
                    admission_open=False,
                )
        else:
            revision = (
                (item.integration or {}).get("merged_revision")
                if op.kind == "integrate"
                else op.source_revision
            )
            selected = {**snapshot(item), "operation_receipt": op.receipt}
            observed = await workspace_environment.observe(
                settings, selected, op.id, op.kind, revision
            )
            if observed:
                state = observed.get("state")
                if state == "waiting" or op.kind in {"integrate", "cleanup"}:
                    # An exact deployment acknowledgement still needs the approved
                    # intent's source handoff and owned cleanup, performed by POST.
                    persist_observed(
                        operation_state="waiting",
                        failure_code=None,
                        admission_open=False,
                    )
                elif state in {"ready", "stopped", "failed"}:
                    values = environment_values(observed)
                    if op.kind in {"create", "resume", "stop"}:
                        values["state"] = "stopped" if state == "stopped" else "ready"
                    persist_observed(
                        operation_state="succeeded" if state in {"ready", "stopped"} else "blocked",
                        admission_open=state != "stopped",
                        failure_code=observed.get("failure_code"),
                        **values,
                    )
    except (ConsoleError, ValueError):
        # Missing/denied/unavailable evidence remains unknown, never inferred failed.
        pass
    return read(factory, workspace_id)


def mount(app, secured):
    @app.get(
        "/api/workbench/projects/{project_id}/workspaces",
        dependencies=secured,
        response_model=WorkspaceList,
    )
    def listing(project_id: UUID):
        with app.state.factory() as db:
            if db.get(WorkbenchProject, str(project_id)) is None:
                raise ConsoleError("app_not_found", 404)
            return WorkspaceList(
                available=app.state.settings.managed_workspaces_enabled,
                items=[
                    output(db, row)
                    for row in db.scalars(
                        select(WorkbenchWorkspace)
                        .where(WorkbenchWorkspace.project_id == str(project_id))
                        .order_by(WorkbenchWorkspace.created_at.desc())
                    )
                ],
            )

    @app.post(
        "/api/workbench/projects/{project_id}/workspaces",
        dependencies=secured,
        response_model=WorkspaceOut,
    )
    async def new_workspace(project_id: UUID, body: WorkspaceCreate):
        return await create(app.state.settings, app.state.factory, project_id, body)

    @app.get(
        "/api/workbench/workspaces/{workspace_id}",
        dependencies=secured,
        response_model=WorkspaceOut,
    )
    async def detail(workspace_id: UUID):
        return await observe(app.state.settings, app.state.factory, workspace_id)

    for kind in ("stop", "resume", "refresh", "integrate", "cleanup"):

        def handler(selected):
            async def execute(workspace_id: UUID, body: WorkspaceAction, request: Request):
                return await action(request.app, str(workspace_id), selected, body)

            return execute

        app.add_api_route(
            "/api/workbench/workspaces/{workspace_id}/" + kind,
            handler(kind),
            methods=["POST"],
            dependencies=secured,
            response_model=WorkspaceOut,
            name="workspace_" + kind,
        )
