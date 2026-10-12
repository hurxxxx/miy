"""Read projections of existing work. These summaries never grant execution authority."""

from sqlalchemy import func, select

from . import planning
from .models import Item, Maintenance, PendingRequest, Revision, Task, WorkbenchProject


def result_text(payload):
    text = payload.get("text", "")
    if not isinstance(text, str):
        return ""
    parsed = planning.parse(text)
    return planning.unwrap_proposed_plan(parsed.answer if parsed else text)


def final_predicate():
    return (
        Item.payload["type"].as_string() == "agentMessage",
        Item.payload["phase"].as_string() == "final_answer",
    )


def item_order():
    # Recovered records follow the canonical thread order. Later live items
    # use their insertion IDs, which exceed the retained history length.
    return func.coalesce(Item.payload["history_order"].as_integer(), Item.id)


def latest_final_ids(partition, *conditions):
    ranked = (
        select(
            Item.id,
            func.row_number()
            .over(partition_by=partition, order_by=(item_order().desc(), Item.id.desc()))
            .label("rank"),
        )
        .where(*conditions, *final_predicate())
        .subquery()
    )
    return select(ranked.c.id).where(ranked.c.rank == 1)


def summaries(db, task_ids):
    """Fetch summaries in bounded batches rather than reading a transcript per card."""
    ids = list(task_ids)
    output = {key: {"latest_plan": None, "latest_result": None, "pending_kinds": []} for key in ids}
    for start in range(0, len(ids), 200):
        batch = ids[start : start + 200]
        for task_id, title in db.execute(
            select(Task.id, WorkbenchProject.title)
            .join(WorkbenchProject, Task.context["project_id"].as_string() == WorkbenchProject.id)
            .where(Task.id.in_(batch))
        ):
            output[task_id]["project_title"] = title
        latest_plans = (
            select(func.max(Revision.id))
            .where(Revision.task_id.in_(batch), Revision.kind == "plan")
            .group_by(Revision.task_id)
        )
        for row in db.scalars(select(Revision).where(Revision.id.in_(latest_plans))):
            output[row.task_id]["latest_plan"] = {
                "id": row.id,
                "version": row.version,
                "created_at": row.created_at.isoformat(),
            }
        latest_results = latest_final_ids(Item.task_id, Item.task_id.in_(batch))
        for row in db.scalars(select(Item).where(Item.id.in_(latest_results))):
            output[row.task_id]["latest_result"] = {
                "item_id": row.item_id,
                "turn_id": row.turn_id,
                "excerpt": " ".join(result_text(row.payload).split())[:280],
                "completed_at": row.payload.get("completed_at"),
            }
        for task_id, method in db.execute(
            select(PendingRequest.task_id, PendingRequest.method)
            .where(PendingRequest.task_id.in_(batch), PendingRequest.state == "pending")
            .distinct()
        ):
            kind = (
                "question"
                if method == "item/tool/requestUserInput"
                else "approval"
                if method.endswith("requestApproval")
                else "other"
            )
            if kind not in output[task_id]["pending_kinds"]:
                output[task_id]["pending_kinds"].append(kind)
    return output


def results(db, task_id):
    # One result per turn, at most 20. Historical records lacking a timestamp
    # stay undated; task.updated_at is not the completion time of an old result.
    latest = latest_final_ids(Item.turn_id, Item.task_id == task_id)
    rows = list(
        db.scalars(
            select(Item)
            .where(Item.id.in_(latest))
            .order_by(item_order().desc(), Item.id.desc())
            .limit(20)
        )
    )
    turns = [row.turn_id for row in rows]
    evidence = {
        turn: {"commands": [], "changed_files": [], "evidence_truncated": False} for turn in turns
    }
    # Bound output independently of retained conversation history.
    entries = list(
        db.scalars(
            select(Item)
            .where(Item.task_id == task_id, Item.turn_id.in_(turns))
            .order_by(item_order().desc(), Item.id.desc())
            .limit(2001)
        )
    )
    if len(entries) > 2000:
        for record in evidence.values():
            record["evidence_truncated"] = True
    for item in entries[:2000]:
        payload, record = item.payload, evidence[item.turn_id]
        if payload.get("type") == "commandExecution":
            if len(record["commands"]) < 50:
                record["commands"].append(
                    {
                        key: payload[key]
                        for key in ("id", "command", "status", "exitCode")
                        if key in payload
                    }
                )
            else:
                record["evidence_truncated"] = True
        elif payload.get("type") == "fileChange":
            for change in payload.get("changes", []):
                path = change.get("path") if isinstance(change, dict) else None
                if isinstance(path, str) and path not in record["changed_files"]:
                    if len(record["changed_files"]) < 100:
                        record["changed_files"].append(path)
                    else:
                        record["evidence_truncated"] = True
    return [
        {
            "item_id": row.item_id,
            "turn_id": row.turn_id,
            "text": result_text(row.payload),
            "completed_at": row.payload.get("completed_at"),
            **evidence[row.turn_id],
        }
        for row in rows
    ]


def catalog_activity(db, project_ids, app_ids):
    from .store import task_out

    output = {"projects": {}, "apps": {}}
    selected = {}
    groups = []
    for target, field, ids in (
        ("projects", "project_id", project_ids),
        ("apps", "app_id", app_ids),
    ):
        ids = list(ids)
        for start in range(0, len(ids), 200):
            batch = ids[start : start + 200]
            key = Task.context[field].as_string()
            for result_only in (False, True):
                latest_result = (
                    select(Item.id)
                    .where(Item.task_id == Task.id, *final_predicate())
                    .order_by(item_order().desc(), Item.id.desc())
                    .limit(1)
                    .correlate(Task)
                    .scalar_subquery()
                )
                ranked = select(
                    Task.id,
                    key.label("scope"),
                    func.row_number()
                    .over(
                        partition_by=key,
                        order_by=(
                            latest_result.desc() if result_only else Task.updated_at.desc(),
                            Task.id,
                        ),
                    )
                    .label("rank"),
                ).where(key.in_(batch))
                if result_only:
                    ranked = ranked.where(
                        select(Item.id).where(Item.task_id == Task.id, *final_predicate()).exists()
                    )
                ranked = ranked.subquery()
                for task, scope in db.execute(
                    select(Task, ranked.c.scope)
                    .join(ranked, ranked.c.id == Task.id)
                    .where(ranked.c.rank == 1)
                ):
                    selected[task.id] = task
                    groups.append(
                        (
                            target,
                            scope,
                            "latest_result_task" if result_only else "latest_task",
                            task.id,
                        )
                    )
    summary = summaries(db, selected)
    projected = {key: task_out(task, db, summary=summary[key]) for key, task in selected.items()}
    for target, scope, field, task_id in groups:
        output[target].setdefault(scope, {})[field] = projected[task_id]
    for app_id, count in db.execute(
        select(Maintenance.app_id, func.count())
        .where(Maintenance.state.in_(("open", "planned")))
        .group_by(Maintenance.app_id)
    ):
        if app_id in app_ids:
            output["apps"].setdefault(app_id, {})["open_issues"] = count
    return output
