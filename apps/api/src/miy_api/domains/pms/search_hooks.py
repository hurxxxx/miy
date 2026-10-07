from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.domains.pms.models import Task, TaskLabel, TaskList
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_delivery import (
    deliver_projection_intent,
    is_prepared_source_projection,
)
from miy_api.domains.retrieval.prepared_company_partitions import (
    assign_company_projection_partition,
)
from miy_api.domains.retrieval.projection_fencing import (
    ProjectionEventRef,
)
from miy_api.domains.search.outbox import enqueue_search_index_job
from miy_api.domains.search.schemas import SearchEntityType
from miy_api.domains.source_access.resource_types import PMS_TASK_RESOURCE_TYPE


def enqueue_task_search_index(
    db: Session,
    *,
    task: Any,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
) -> None:
    if projection_event is None:
        _record_task_projection_event(db, task=task, operation=operation)
        return
    if is_prepared_source_projection(db):
        raise ProjectionOutboxError("projection_core_reference_in_source_composition")
    _enqueue_search_target(
        db,
        entity_id=task.id,
        operation=operation,
        projection_event=projection_event,
    )


def enqueue_task_search_index_by_id(
    db: Session,
    *,
    task_id: str,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
) -> None:
    task = db.get(Task, task_id)
    if task is None:
        return
    if projection_event is None:
        _record_task_projection_event(db, task=task, operation=operation)
        return
    if is_prepared_source_projection(db):
        raise ProjectionOutboxError("projection_core_reference_in_source_composition")
    _enqueue_search_target(
        db,
        entity_id=task_id,
        operation=operation,
        projection_event=projection_event,
    )


def enqueue_task_list_task_search_recompute(
    db: Session,
    *,
    task_list: Any,
    operation: str = "upsert",
) -> None:
    task_ids = db.scalars(select(Task.id).where(Task.list_id == task_list.id)).all()
    _enqueue_pms_task_targets(db, task_ids=task_ids, operation=operation)


def enqueue_label_task_search_recompute(
    db: Session,
    *,
    label: Any,
    task_ids: list[str] | None = None,
    operation: str = "upsert",
) -> None:
    resolved_task_ids = task_ids
    if resolved_task_ids is None:
        resolved_task_ids = list(
            db.scalars(select(TaskLabel.task_id).where(TaskLabel.label_id == label.id))
        )
    _enqueue_pms_task_targets(
        db,
        task_ids=resolved_task_ids,
        operation=operation,
        unique=True,
    )


def enqueue_task_list_status_task_search_recompute(
    db: Session,
    *,
    task_status: Any,
    operation: str = "upsert",
) -> None:
    task_list = db.get(TaskList, task_status.list_id)
    if task_list is None:
        return
    enqueue_task_list_task_search_recompute(db, task_list=task_list, operation=operation)


def _enqueue_pms_task_targets(
    db: Session,
    *,
    task_ids: Iterable[str | None],
    operation: str,
    unique: bool = False,
) -> None:
    present_task_ids = [str(task_id) for task_id in task_ids if task_id]
    resolved_task_ids = set(present_task_ids) if unique else present_task_ids
    for task_id in sorted(resolved_task_ids):
        task = db.get(Task, task_id)
        if task is None:
            continue
        _record_task_projection_event(db, task=task, operation=operation)


def _enqueue_search_target(
    db: Session,
    *,
    entity_id: str,
    operation: str,
    projection_event: ProjectionEventRef | None,
) -> None:
    enqueue_search_index_job(
        db,
        entity_type=SearchEntityType.PMS_TASK,
        entity_id=entity_id,
        operation=operation,
        projection_event=projection_event,
    )


def _record_task_projection_event(
    db: Session,
    *,
    task: Any,
    operation: str,
) -> None:
    if operation not in {"upsert", "delete"}:
        raise ValueError(f"Unsupported search index operation: {operation}")
    partition_id = str(getattr(task, "retrieval_partition_id", None) or "").strip()
    if not partition_id or is_prepared_source_projection(db):
        partition_id = assign_company_projection_partition(
            db,
            target=task,
            source_namespace="pms",
        )
    deleted = operation == "delete"
    deliver_projection_intent(
        db,
        intent=ProjectionIntent(
            resource_type=PMS_TASK_RESOURCE_TYPE,
            resource_id=task.id,
            retrieval_partition_id=partition_id,
            change_kind="delete" if deleted else "content",
            desired_state="deleted" if deleted else "active",
            operation=operation,
        ),
    )


__all__ = [
    "enqueue_label_task_search_recompute",
    "enqueue_task_list_status_task_search_recompute",
    "enqueue_task_list_task_search_recompute",
    "enqueue_task_search_index",
    "enqueue_task_search_index_by_id",
]
