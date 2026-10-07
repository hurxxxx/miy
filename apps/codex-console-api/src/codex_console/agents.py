"""Bounded projections of native 0.158 thread trees. No agent orchestration."""

import json
from datetime import datetime

from sqlalchemy import select, update

from .models import Agent, PendingRequest, Task, now

TERMINAL = ("completed", "interrupted", "errored", "shutdown")
THREAD_STATES = ("notLoaded", "idle", "active", "systemError")
TURN_STATES = ("inProgress", "completed", "interrupted", "failed")


def observation_base(row, generation):
    value = dict(row.observation or {})
    if value.get("generation") != generation:
        # Retain historical evidence, but never transfer a live connection claim.
        if value.get("thread_checked_at"):
            value["error_code"] = "unavailable"
        value["generation"] = generation
    return value


def valid_turn(turn):
    return (
        isinstance(turn, dict)
        and isinstance(turn.get("id"), str)
        and 0 < len(turn["id"]) <= 160
        and turn.get("status") in TURN_STATES
    )


def observe_turn(row, turn, generation):
    if not valid_turn(turn):
        return
    value = observation_base(row, generation)
    value["last_turn"] = {
        "id": turn["id"],
        "status": turn["status"],
        "observed_at": now().isoformat(),
    }
    row.observation = value


def observe_status(row, status, generation, *, direct=False):
    if not isinstance(status, dict) or status.get("type") not in THREAD_STATES:
        return False
    value = observation_base(row, generation)
    value.update(thread_status=status["type"], thread_checked_at=now().isoformat())
    if direct:
        value.update(attempted_at=value["thread_checked_at"], error_code=None)
    row.observation = value
    return True


def observe_thread(row, thread, generation):
    if not observe_status(row, thread.get("status"), generation, direct=True):
        return False
    for turn in thread.get("turns", [])[-1:]:
        observe_turn(row, turn, generation)
    return True


def observation_failed(row, generation, code="read_failed"):
    value = observation_base(row, generation)
    value.update(attempted_at=now().isoformat(), error_code=code)
    row.observation = value


def invalidate_observation(row, generation=None):
    if row.observation and (generation is None or row.observation.get("generation") == generation):
        row.observation = {**row.observation, "error_code": "unavailable"}


def observation_out(row):
    value = row.observation
    if not value:
        return None
    result = {
        key: value.get(key)
        for key in ("thread_status", "thread_checked_at", "last_turn", "attempted_at", "error_code")
    }
    if value.get("error_code"):
        freshness = "unavailable"
    elif value.get("thread_checked_at"):
        checked = datetime.fromisoformat(value["thread_checked_at"])
        freshness = "fresh" if 0 <= (now() - checked).total_seconds() <= 30 else "stale"
    else:
        freshness = "unknown"
    return {**result, "freshness": freshness}


def busy_descendants(db, task_id):
    return (
        db.scalar(
            select(Agent.thread_id)
            .where(
                Agent.task_id == task_id,
                Agent.parent_thread_id.is_not(None),
                Agent.status.not_in(TERMINAL),
            )
            .limit(1)
        )
        is not None
    )


def task_for_thread(db, thread_id, *, executor=None):
    if not isinstance(thread_id, str) or not thread_id:
        return None
    task = db.scalar(select(Task).where(Task.thread_id == thread_id))
    if task:
        return task if executor is None or task.executor == executor else None
    agent = db.get(Agent, thread_id) if thread_id else None
    task = db.get(Task, agent.task_id) if agent else None
    return task if task and (executor is None or task.executor == executor) else None


def register(db, thread, *, executor=None, task_id=None):
    thread_id = thread.get("id")
    if not isinstance(thread_id, str) or len(thread_id) > 160:
        return None
    task = db.scalar(select(Task).where(Task.thread_id == thread_id))
    parent = thread.get("parentThreadId")
    if parent == thread_id:
        return None
    if not task and parent:
        task = task_for_thread(db, parent, executor=executor)
    if task and (
        (executor is not None and task.executor != executor)
        or (task_id is not None and task.id != task_id)
    ):
        return None
    if not task or (thread.get("cwd") and thread["cwd"] != task.root):
        return None
    root = db.get(Agent, task.thread_id)
    if root and root.session_id and thread.get("sessionId") != root.session_id:
        return None
    row = db.get(Agent, thread_id)
    if row and (row.task_id != task.id or row.parent_thread_id != parent):
        return None
    if not row:
        row = Agent(
            thread_id=thread_id,
            task_id=task.id,
            parent_thread_id=parent,
            name="Codex",
            flags=[],
            status="notLoaded",
        )
        db.add(row)
    row.session_id = thread.get("sessionId")
    row.name = str(thread.get("agentNickname") or thread.get("name") or "Codex")[:200]
    row.role = str(thread["agentRole"])[:100] if thread.get("agentRole") else None
    state(row, thread.get("status", {}))
    row.updated_at = now()
    db.flush()
    return row


def state(row, value):
    kind = value.get("type")
    if kind in ("active", "idle", "notLoaded", "systemError"):
        if not (kind in ("idle", "notLoaded") and row.status in TERMINAL):
            row.status = kind
        row.flags = [
            f
            for f in value.get("activeFlags", [])
            if f in ("waitingOnApproval", "waitingOnUserInput")
        ]


def project(db, task, thread_id, method, params, *, generation=None):
    from . import store

    row = db.get(Agent, thread_id)
    if row and row.task_id != task.id:
        return
    if not row:
        row = Agent(
            thread_id=thread_id,
            task_id=task.id,
            name="Codex",
            flags=[],
            status="active",
            parent_thread_id=None,
        )
        db.add(row)
    turn_id = params.get("turnId") or params.get("turn", {}).get("id")
    if method == "thread/status/changed":
        state(row, params.get("status", {}))
        if generation:
            observe_status(row, params.get("status"), generation)
    elif method == "serverRequest/resolved":
        db.execute(
            update(PendingRequest)
            .where(
                PendingRequest.task_id == task.id,
                PendingRequest.thread_id == thread_id,
                PendingRequest.rpc_id == json.dumps(params.get("requestId")),
            )
            .values(state="resolved")
        )
        row.flags = []
    elif method == "turn/started":
        row.turn_id, row.status, row.flags = turn_id, "active", []
        if generation:
            observe_turn(row, {"id": turn_id, "status": "inProgress"}, generation)
    elif turn_id and row.turn_id and turn_id != row.turn_id:
        return
    elif method == "turn/completed":
        result = params.get("turn", {}).get("status")
        if result not in ("completed", "interrupted", "failed"):
            return
        row.status = "errored" if result == "failed" else result
        if generation:
            observe_turn(row, params["turn"], generation)
        row.flags = []
        store.invalidate_pending(db, task.id, thread_id=thread_id)
    elif method == "turn/plan/updated":
        steps = [
            {"step": str(s.get("step", ""))[:500], "status": s.get("status")}
            for s in params.get("plan", [])[:100]
            if s.get("status") in ("pending", "inProgress", "completed")
        ]
        row.progress = {"steps": steps}
        row.activity = next((s["step"] for s in steps if s["status"] == "inProgress"), None)
    elif method in ("item/started", "item/completed"):
        item = params.get("item", {})
        kind = item.get("type")
        labels = {
            "commandExecution": "command",
            "fileChange": "files",
            "webSearch": "search",
            "collabAgentToolCall": "delegating",
        }
        if kind in labels:
            row.activity = labels[kind]
        if kind == "collabAgentToolCall":
            if item.get("tool") == "spawnAgent" and item.get("senderThreadId") == thread_id:
                for child_id in item.get("receiverThreadIds", [])[:100]:
                    if (
                        isinstance(child_id, str)
                        and len(child_id) <= 160
                        and not db.get(Agent, child_id)
                    ):
                        db.add(
                            Agent(
                                thread_id=child_id,
                                task_id=task.id,
                                parent_thread_id=thread_id,
                                session_id=row.session_id,
                                name="Codex",
                                status="pendingInit",
                                flags=[],
                            )
                        )
                db.flush()
            # Parentage is confirmed through thread/read/list, not inferred from tool text.
            for child_id, value in item.get("agentsStates", {}).items():
                child = db.get(Agent, child_id)
                if (
                    child
                    and child.task_id == task.id
                    and value.get("status")
                    in (
                        "pendingInit",
                        "running",
                        "interrupted",
                        "completed",
                        "errored",
                        "shutdown",
                        "notFound",
                    )
                ):
                    child.status = value["status"]
                    child.updated_at = now()
        elif kind == "agentMessage" and item.get("phase") == "final_answer":
            row.activity = str(item.get("text", ""))[:500] if row.parent_thread_id else None
    if turn_id and not row.turn_id:
        row.turn_id = turn_id
    row.updated_at = now()
    db.flush()
    store.changed(db, task, "agent.updated")


def request_is_current(db, task, request):
    if request.thread_id in (None, task.thread_id):
        return request.turn_id == task.turn_id and task.status in ("starting", "running", "waiting")
    agent = db.get(Agent, request.thread_id)
    return bool(
        agent
        and agent.task_id == task.id
        and agent.turn_id == request.turn_id
        and agent.status not in (*TERMINAL, "notFound", "systemError")
    )
