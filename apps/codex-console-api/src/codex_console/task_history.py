"""Durable owner-visible activity; never copy prompts, outputs or credentials."""

from typing import Literal

from sqlalchemy import or_, select

from .models import Event

NOISE = (
    "item/agentMessage/delta",
    "item/plan/delta",
    "item/commandExecution/outputDelta",
    "thread/tokenUsage/updated",
    "agents.refreshed",
    "task.preferences.updated",
)


def snapshot(task, kind, details=None):
    if kind in NOISE:
        return None
    data = {"status": task.status, "stage": task.stage, "error_code": task.error_code}
    if kind == "turn/plan/updated":
        progress = task.progress or {}
        steps = progress.get("steps", [])
        data["steps"] = [
            {"step": row["step"][:500], "status": row["status"]}
            for row in steps[:100]
            if isinstance(row, dict) and isinstance(row.get("step"), str)
        ]
        data["explanation"] = str(progress.get("explanation") or "")[:1000]
        data["truncated"] = (
            len(steps) > 100
            or len(str(progress.get("explanation") or "")) > 1000
            or any(len(row.get("step", "")) > 500 for row in steps)
        )
    if kind.startswith("task.environment."):
        meta = (task.context or {}).get("task_environment") or {}
        preparation = meta.get("preparation") or {}
        data.update(
            environment=meta.get("kind"),
            preparation_state=preparation.get("state"),
            step=preparation.get("step"),
        )
    # Callers supply only the deterministic projection below or request identity.
    return {**data, **(details or {})}


def native_details(method, params):
    if method == "turn/completed":
        return {"turn_status": (params.get("turn") or {}).get("status")}
    if method not in {"item/started", "item/completed"}:
        return None
    item = params.get("item") or {}
    kind = item.get("type")
    data = {"item_id": item.get("id"), "item_type": kind, "item_status": item.get("status")}
    if kind == "commandExecution":
        data.update(command=str(item.get("command") or "")[:2000], exit_code=item.get("exitCode"))
        data["truncated"] = len(str(item.get("command") or "")) > 2000
    elif kind == "fileChange":
        changes = item.get("changes") or []
        data["files"] = [
            row["path"][:500]
            for row in changes[:100]
            if isinstance(row, dict) and isinstance(row.get("path"), str)
        ]
        data["truncated"] = len(changes) > 100 or any(
            isinstance(row, dict) and len(str(row.get("path") or "")) > 500 for row in changes
        )
    elif kind == "agentMessage":
        if item.get("questions"):
            data["visible"] = False
            return data
        data["visible"] = method == "item/completed" and item.get("phase") == "final_answer"
    elif kind == "plan":
        data["visible"] = method == "item/completed"
    else:
        data["visible"] = False
    return data


def page(db, task_id, *, before=None, limit=50, category="all"):
    query = select(Event).where(
        Event.task_id == task_id,
        Event.kind.not_in(NOISE),
        Event.details["visible"].as_boolean().is_not(False),
        or_(Event.kind != "agent.updated", Event.details["visible"].as_boolean().is_(True)),
    )
    if before is not None:
        query = query.where(Event.id < before)
    if category == "requests":
        query = query.where(
            or_(
                Event.kind.like("question.%"),
                Event.kind.in_(
                    (
                        "request.pending",
                        "request.answered",
                        "request.sent",
                        "serverRequest/resolved",
                    )
                ),
            )
        )
    elif category == "tools":
        query = query.where(
            Event.kind.in_(("item/started", "item/completed")),
            Event.details["item_type"].as_string().in_(("commandExecution", "fileChange")),
        )
    elif category == "execution":
        query = query.where(
            Event.kind.in_(
                (
                    "turn.submitting",
                    "turn.accepted",
                    "turn.failed",
                    "turn/completed",
                    "turn/plan/updated",
                    "turn.interrupt_requested",
                    "runtime.disconnected",
                    "thread.recovered",
                    "submission.recovered",
                    "agent.updated",
                )
            )
        )
    rows = list(db.scalars(query.order_by(Event.id.desc()).limit(limit + 1)))
    selected = rows[:limit]
    return {
        "items": [
            {
                "id": row.id,
                "event": row.kind,
                "created_at": row.created_at.isoformat(),
                "details": row.details,
            }
            for row in selected
        ],
        "next_before": selected[-1].id if len(rows) > limit else None,
    }


def install(app, secured):
    from fastapi import Query

    from . import store
    from .schemas import TaskHistoryPage

    @app.get("/api/tasks/{task_id}/history", dependencies=secured, response_model=TaskHistoryPage)
    def task_history(
        task_id: str,
        before: int | None = Query(default=None, ge=1),
        limit: int = Query(default=50, ge=1, le=100),
        category: Literal["all", "execution", "requests", "tools"] = "all",
    ):
        with app.state.factory() as db:
            store.require_task(db, task_id)
            return page(db, task_id, before=before, limit=limit, category=category)
