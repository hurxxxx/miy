from __future__ import annotations

from datetime import date
from types import SimpleNamespace


def task(
    title: str,
    *,
    status: str,
    priority: str = "medium",
    due_date: date | None = None,
    assignee_id: str | None = None,
    archived: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"task-{title}",
        title=title,
        task_number=1,
        status=status,
        priority=priority,
        due_date=due_date,
        assignee_id=assignee_id,
        archived=archived,
        task_list=None,
    )


def task_list(
    list_id: str,
    tasks: list[SimpleNamespace],
    *,
    milestones: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    item = SimpleNamespace(
        id=list_id,
        key=list_id.upper(),
        name=f"List {list_id}",
        status_mode="custom",
        team_id=None,
        statuses=[],
        space_statuses=[],
        tasks=tasks,
        milestones=milestones or [],
    )
    for task_item in tasks:
        task_item.task_list = item
    return item
