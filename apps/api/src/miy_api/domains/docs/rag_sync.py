from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.domains.docs.models import DocMeetingAccess, NativeDoc
from miy_api.domains.docs.partitioning import ensure_native_doc_partition
from miy_api.domains.meeting.models import Meeting, MeetingDocLink
from miy_api.domains.rag.contracts import RagSyncOperation
from miy_api.domains.rag.docs_projection import NATIVE_DOC_RESOURCE_TYPE
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_delivery import deliver_projection_intent

MEETING_VISIBILITY_SCOPE = "meeting"


def enqueue_native_doc_rag_sync(
    db: Session,
    *,
    doc: NativeDoc,
    operation: RagSyncOperation,
) -> None:
    partition_id = ensure_native_doc_partition(db, doc=doc)
    deliver_projection_intent(
        db,
        intent=ProjectionIntent(
            resource_type=NATIVE_DOC_RESOURCE_TYPE,
            resource_id=doc.id,
            retrieval_partition_id=partition_id,
            change_kind="delete" if operation == RagSyncOperation.DELETE else "content",
            desired_state="deleted" if operation == RagSyncOperation.DELETE else "active",
            operation=operation.value,
        ),
    )


def enqueue_native_doc_rag_sync_by_id(
    db: Session,
    *,
    doc_id: str,
    operation: RagSyncOperation,
) -> None:
    doc = db.scalar(select(NativeDoc).where(NativeDoc.id == doc_id))
    if doc is None:
        return
    enqueue_native_doc_rag_sync(
        db,
        doc=doc,
        operation=operation,
    )


def enqueue_native_doc_visibility(db: Session, *, doc_id: str) -> None:
    """Keep ACL mutation and its current source intent in the caller transaction.

    Refresh under the source row lock so a concurrent trash/content mutation
    cannot leave a cached active document producing an event after a tombstone.
    The legacy bridge still requires Core acceptance authority; this helper does
    not provision a partition reader or activate a source-only runtime.
    """
    doc = db.scalar(
        select(NativeDoc)
        .where(NativeDoc.id == doc_id)
        # PostgreSQL FOR NO KEY UPDATE: serialize content/trash changes without
        # upgrading concurrent grant INSERTs' FK KEY SHARE locks into a cycle.
        # This helper never changes the document's primary key.
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )
    if doc is None:
        return
    enqueue_native_doc_rag_sync(
        db,
        doc=doc,
        operation=(
            RagSyncOperation.DELETE
            if doc.trashed_at is not None
            else RagSyncOperation.VISIBILITY_UPDATE
        ),
    )


def collect_meeting_visibility_doc_ids(
    db: Session,
    *,
    meeting_id: str,
    cursor: dict | None = None,
) -> list[str]:
    doc_ids = {str(doc_id) for doc_id in (cursor or {}).get("doc_ids", []) if doc_id}
    doc_ids.update(
        db.scalars(select(MeetingDocLink.doc_id).where(MeetingDocLink.meeting_id == meeting_id))
    )
    doc_ids.update(
        db.scalars(
            select(DocMeetingAccess.doc_id).where(
                DocMeetingAccess.granted_by_meeting_id == meeting_id
            )
        )
    )
    meeting = db.get(Meeting, meeting_id)
    if meeting is not None and meeting.notes_doc_id:
        doc_ids.add(meeting.notes_doc_id)
    return sorted(doc_id for doc_id in doc_ids if doc_id)


def enqueue_meeting_visibility_recompute(
    db: Session,
    *,
    meeting_id: str,
    doc_ids: list[str] | None = None,
) -> None:
    # Explicit IDs survive detach/delete of the meeting's source relationships.
    # Existing queued scope jobs remain a separate legacy compatibility boundary.
    targets = (
        collect_meeting_visibility_doc_ids(db, meeting_id=meeting_id)
        if doc_ids is None
        else sorted({doc_id for doc_id in doc_ids if doc_id})
    )
    for doc_id in targets:
        enqueue_native_doc_visibility(db, doc_id=doc_id)
