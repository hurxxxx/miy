"""Task-bound native host tools share one authorization and generation check."""

import asyncio
import json

from pydantic import ValidationError

from . import agents, store, task_git, task_timeline
from .errors import ConsoleError


async def handle(runtime, message, *, generation=None):
    params = message.get("params", {})
    if message.get("method") != "item/tool/call" or params.get("tool") not in (
        task_git.TOOL_NAME,
        task_timeline.TOOL_NAME,
    ):
        return False
    rpc = runtime.rpc
    if not rpc or (generation and generation != rpc.generation):
        return True
    success, result = False, {"error": "path_denied"}
    try:
        module = task_git if params["tool"] == task_git.TOOL_NAME else task_timeline
        args = module.Arguments.model_validate(params.get("arguments"))
        with runtime.factory() as db:
            task = agents.task_for_thread(db, params.get("threadId"), executor=runtime.executor)
            if not task or not runtime.owns(task) or runtime.remote_task_id is not None:
                raise ConsoleError("path_denied", 403)
            task_id = task.id
        async with runtime.task_gate(task_id):

            def execute():
                with runtime.factory.begin() as db:
                    task = store.require_task(db, task_id)
                    native = db.get(agents.Agent, params.get("threadId"))
                    if (
                        runtime.rpc is not rpc
                        or task.runtime_generation != rpc.generation
                        or not native
                        or native.turn_id != params.get("turnId")
                        or native.status in (*agents.TERMINAL, "systemError")
                    ):
                        raise ConsoleError("path_denied", 403)
                    runtime.require_allowed_task(task)
                    if module is task_timeline:
                        return task_timeline.execute(db, runtime.settings, task, args)
                    if args.action == "register":
                        return {
                            "id": task_git.register(db, runtime.settings, task, args.root, "agent")
                        }
                    return {"links": task_git.listing(db, runtime.settings, task)}

            result = await asyncio.to_thread(execute)
            success = True
    except (ConsoleError, ValidationError) as exc:
        result = {"error": exc.code if isinstance(exc, ConsoleError) else "invalid_input"}
    if runtime.rpc is not rpc or (generation and generation != rpc.generation):
        return True
    await rpc.respond(
        message["id"],
        {"success": success, "contentItems": [{"type": "inputText", "text": json.dumps(result)}]},
    )
    return True
