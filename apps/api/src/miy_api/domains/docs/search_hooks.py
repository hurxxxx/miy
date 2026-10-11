from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.official_apps.projection_contracts import ProjectionOutboxError
from miy_api.domains.official_apps.projection_delivery import is_prepared_source_projection
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.outbox import enqueue_search_index_job
from miy_api.domains.search.schemas import SearchEntityType


def enqueue_doc_search_index(
    db: Session,
    *,
    doc: Any,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
    publish_after_commit: bool = True,
) -> None:
    if is_prepared_source_projection(db):
        raise ProjectionOutboxError("projection_core_reference_in_source_composition")
    _enqueue_search_target(
        db,
        entity_id=doc.id,
        operation=operation,
        projection_event=projection_event,
        publish_after_commit=publish_after_commit,
    )


def enqueue_doc_search_index_by_id(
    db: Session,
    *,
    doc_id: str,
    operation: str = "upsert",
    projection_event: ProjectionEventRef | None = None,
    publish_after_commit: bool = True,
) -> None:
    doc = db.get(NativeDoc, doc_id)
    if doc is None:
        return
    enqueue_doc_search_index(
        db,
        doc=doc,
        operation=operation,
        projection_event=projection_event,
        publish_after_commit=publish_after_commit,
    )


def _enqueue_search_target(
    db: Session,
    *,
    entity_id: str,
    operation: str,
    projection_event: ProjectionEventRef | None,
    publish_after_commit: bool,
) -> None:
    enqueue_search_index_job(
        db,
        entity_type=SearchEntityType.DOC,
        entity_id=entity_id,
        operation=operation,
        projection_event=projection_event,
        **({} if publish_after_commit else {"publish_after_commit": False}),
    )


__all__ = ["enqueue_doc_search_index", "enqueue_doc_search_index_by_id"]
