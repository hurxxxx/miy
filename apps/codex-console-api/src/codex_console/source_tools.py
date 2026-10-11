"""Owner-approved local app saving, independent of external registration grants."""

import asyncio
import json
from typing import Literal

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from . import app_checkpoints, app_sources, git, planning, store
from .errors import ConsoleError
from .models import AppSourceBinding, Revision, Task, WorkbenchProject

TOOL_NAME = "miy_app_source"
MAX_PRIOR_PLAN_BYTES = 16 * 1024


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["context", "checkpoint"]


def specs(task):
    context = task.context or {}
    if context.get("purpose") != "development" or not context.get("source_binding"):
        return []
    return [
        {
            "type": "function",
            "name": TOOL_NAME,
            "description": (
                "Save work in this selected app's local checkout. Read context first. "
                "Context includes this project's latest earlier native plan as reference, "
                "never execution authority. "
                "checkpoint creates a bounded local commit under the owner's implementation "
                "approval; it needs no platform registration or delivery grant. It does not "
                "register, publish, deploy or grant app permissions. Git metadata stays "
                "read-only to app commands. After an uncertain result inspect context, "
                "never automatically repeat the write. No paths, credentials or commands "
                "as inputs. Available only in newly created development threads."
            ),
            "inputSchema": Arguments.model_json_schema(),
        }
    ]


def require_binding(db, task):
    context = (task.context or {}) if task else {}
    source = context.get("source_binding") or {}
    if context.get("purpose") != "development" or not source:
        raise ConsoleError("app_source_save_denied", 403)
    if task.workspace_id:
        from .workspaces import require

        workspace = require(db, task.workspace_id)
        if (
            source.get("workspace_id") != workspace.id
            or source.get("repository_root") != workspace.worktree_root
            or source.get("directory") != workspace.source_directory
            or source.get("repository") != workspace.repository
            or context.get("project_id") != workspace.project_id
            or context.get("app_id") != workspace.app_id
            or task.worktree_owned
        ):
            raise ConsoleError("workspace_source_changed", 409)
        return
    binding = db.get(AppSourceBinding, source.get("app_id"))
    if (
        not binding
        or context.get("app_id") != binding.app_id
        or source.get("version") != binding.version
        or source.get("repository_root") != binding.repository_root
        or source.get("repository") != binding.manifest["source"]["repository"]
        or source.get("directory") != binding.manifest["source"].get("directory", ".")
    ):
        raise ConsoleError("app_source_changed", 409)
    if context.get("project_id"):
        project = db.get(WorkbenchProject, context["project_id"])
        if not project or project.app_id != binding.app_id:
            raise ConsoleError("app_source_changed", 409)
    if task.worktree_owned:
        raise ConsoleError("app_checkpoint_worktree_unsupported", 422)


def prior_plan(factory, task):
    project_id = (task.context or {}).get("project_id")
    if not project_id:
        return None
    with factory() as db:
        current = db.get(Task, task.id)
        require_binding(db, current)
        if current.context.get("project_id") != project_id:
            raise ConsoleError("app_source_changed", 409)
        revision = db.scalar(
            select(Revision)
            .join(Task, Task.id == Revision.task_id)
            .where(
                Revision.kind == "plan",
                Revision.source_turn_id.is_not(None),
                Revision.source_turn_id != "",
                Task.id != current.id,
                Task.created_at < current.created_at,
                Task.context["project_id"].as_string() == project_id,
                Task.context["app_id"].as_string() == current.context["app_id"],
            )
            .order_by(Revision.created_at.desc(), Revision.id.desc())
            .limit(1)
        )
        if not revision:
            return None
        encoded = planning.unwrap_proposed_plan(revision.body).encode("utf-8")
        return {
            "task_id": revision.task_id,
            "revision_id": revision.id,
            "version": revision.version,
            "body": encoded[:MAX_PRIOR_PLAN_BYTES].decode("utf-8", errors="ignore"),
            "truncated": len(encoded) > MAX_PRIOR_PLAN_BYTES,
            "reference_only": True,
            "execution_authorized": False,
        }


async def execute(settings, factory, task, action, *, check):
    check()
    if action == "context":
        status = await asyncio.to_thread(git.status, app_sources.task_workspace(settings, task))
        reference = await asyncio.to_thread(prior_plan, factory, task)
        check()
        return {
            "app_id": task.context["source_binding"]["app_id"],
            "source_revision": status["head"],
            "dirty": bool(status["changed"]),
            "checkpoint_scope": "bound ordinary checkout on a named branch",
            "external_authorization_required": False,
            "prior_plan": reference,
        }
    if task.workspace_id:
        from .workspaces import task_checkpoint

        result = await asyncio.to_thread(task_checkpoint, settings, factory, task, check)
    else:
        result = await asyncio.to_thread(app_checkpoints.checkpoint, settings, task, check=check)
    check()
    return result


async def handle(runtime, message, *, generation=None):
    if (
        message.get("method") != "item/tool/call"
        or message.get("params", {}).get("tool") != TOOL_NAME
    ):
        return False
    params = message.get("params", {})
    rpc = runtime.rpc
    if not rpc or (generation and generation != rpc.generation):
        return True
    result, success = {"error": "app_source_save_denied"}, False
    try:
        from .rpc import REMOTE_CONTRACT

        Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallParams"]).validate(params)
        args = Arguments.model_validate(params.get("arguments"))
        if not runtime.remote_task_id:
            raise ConsoleError("app_source_save_denied", 403)

        def current():
            if runtime.rpc is not rpc or (generation and generation != rpc.generation):
                raise ConsoleError("app_source_save_denied", 403)
            with runtime.factory() as db:
                task = db.get(Task, runtime.remote_task_id)
                if (
                    not task
                    or task.thread_id != params.get("threadId")
                    or task.turn_id != params.get("turnId")
                    or task.runtime_generation != rpc.generation
                    or task.executor != runtime.executor
                    or task.status not in store.ACTIVE
                ):
                    raise ConsoleError("app_source_save_denied", 403)
                require_binding(db, task)
                runtime.require_allowed_task(task)
                if args.action == "checkpoint" and not store.implementation_authorized(db, task):
                    raise ConsoleError("app_source_save_denied", 403)
                db.expunge(task)
                return task

        async with runtime.task_gate(runtime.remote_task_id):
            task = current()
            result = await execute(
                runtime.settings, runtime.factory, task, args.action, check=current
            )
        success = True
    except ConsoleError as error:
        result = {"error": error.code}
    except (ValidationError, SchemaError, ValueError, KeyError):
        result = {"error": "app_source_save_invalid_response"}
    if runtime.rpc is rpc and (not generation or generation == rpc.generation):
        response = {
            "contentItems": [{"type": "inputText", "text": json.dumps(result)}],
            "success": success,
        }
        Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallResponse"]).validate(response)
        await rpc.respond(message["id"], response)
    return True
