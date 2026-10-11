from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from miy_api.domains.pms import search_hooks as pms_search_hooks
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.schemas import SearchEntityType


def _projection_event(
    task_id: str,
    *,
    event_sequence: int = 1,
    deleted: bool = False,
) -> ProjectionEventRef:
    return ProjectionEventRef(
        event_sequence=event_sequence,
        resource_type="pms_task",
        resource_id=task_id,
        projection_version=event_sequence,
        retrieval_partition_id="722c2043-fc6f-4446-9811-dc35c263d445",
        change_kind="delete" if deleted else "content",
        desired_state="deleted" if deleted else "active",
        content_checksum=None,
        visibility_checksum=None,
    )


def _record_enqueues(
    monkeypatch: Any,
) -> list[tuple[str, SearchEntityType, str, str, ProjectionEventRef | None]]:
    calls: list[tuple[str, SearchEntityType, str, str, ProjectionEventRef | None]] = []

    def fake_enqueue_search_index_job(
        db: Session,
        *,
        entity_type: SearchEntityType,
        entity_id: str,
        operation: str,
        projection_event: ProjectionEventRef | None = None,
    ) -> None:
        calls.append((entity_type, entity_id, operation, projection_event))

    monkeypatch.setattr(
        pms_search_hooks,
        "enqueue_search_index_job",
        fake_enqueue_search_index_job,
    )
    return calls
