from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from miy_api.domains.meeting.models import Meeting
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
from miy_api.domains.source_access.resource_types import MEETING_RESOURCE_TYPE


def enqueue_meeting_search_index(
    db: Session,
    *,
    meeting: Any,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
) -> None:
    if projection_event is None:
        _record_meeting_projection_event(db, meeting=meeting, operation=operation)
        return
    if is_prepared_source_projection(db):
        raise ProjectionOutboxError("projection_core_reference_in_source_composition")
    _enqueue_search_target(
        db,
        entity_id=meeting.id,
        operation=operation,
        projection_event=projection_event,
    )


def enqueue_meeting_search_index_by_id(
    db: Session,
    *,
    meeting_id: str,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
) -> None:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        return
    enqueue_meeting_search_index(
        db,
        meeting=meeting,
        operation=operation,
        projection_event=projection_event,
    )


def _enqueue_search_target(
    db: Session,
    *,
    entity_id: str,
    operation: str,
    projection_event: ProjectionEventRef | None,
) -> None:
    enqueue_search_index_job(
        db,
        entity_type=SearchEntityType.MEETING,
        entity_id=entity_id,
        operation=operation,
        projection_event=projection_event,
    )


def _record_meeting_projection_event(
    db: Session,
    *,
    meeting: Any,
    operation: str,
) -> None:
    if operation not in {"upsert", "delete"}:
        raise ValueError(f"Unsupported search index operation: {operation}")
    partition_id = str(getattr(meeting, "retrieval_partition_id", None) or "").strip()
    if not partition_id or is_prepared_source_projection(db):
        partition_id = assign_company_projection_partition(
            db,
            target=meeting,
            source_namespace="meeting",
        )
    deleted = operation == "delete"
    deliver_projection_intent(
        db,
        intent=ProjectionIntent(
            resource_type=MEETING_RESOURCE_TYPE,
            resource_id=meeting.id,
            retrieval_partition_id=partition_id,
            change_kind="delete" if deleted else "content",
            desired_state="deleted" if deleted else "active",
            operation=operation,
        ),
    )


__all__ = ["enqueue_meeting_search_index", "enqueue_meeting_search_index_by_id"]
