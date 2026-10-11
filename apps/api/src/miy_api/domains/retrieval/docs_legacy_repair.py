"""Bounded Core conversion of three old Docs jobs, without source mutation.

The low-level repair belongs to the caller transaction. Dispatch commits only
the conversion; uncertain outcomes are reconciled with the SAME origin job ID.
No provider, source writer, partition ensure or source outbox append is used.
Old processing consumers must be drained explicitly, never stolen by age.
"""

import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.auth.app_availability import is_company_app_enabled
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.docs.models import DocMeetingAccess, NativeDoc
from miy_api.domains.meeting.models import Meeting, MeetingDocLink
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_outbox import lock_projection_source
from miy_api.domains.rag.contracts import RagSyncLane, RagSyncOperation
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob
from miy_api.domains.rag.outbox import enqueue_rag_sync_job
from miy_api.domains.retrieval.docs_legacy_repair_contracts import (
    MAX_TARGETS,
    RESOURCE_TYPE,
    DocsLegacyRepairError,
    LegacyDocsJobKind,
    canonical,
    digest,
    identifier,
)
from miy_api.domains.retrieval.docs_legacy_repair_models import (
    DocsLegacyProjectionRepair,
    DocsLegacyProjectionRepairTarget,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import (
    lock_projection_stream,
    record_projection_event,
)
from miy_api.domains.search.models import SearchIndexJob
from miy_api.domains.search.outbox import enqueue_search_index_job

_MODELS = {"scope": RagVisibilityRecomputeJob, "rag": RagSyncJob, "search": SearchIndexJob}
_ORIGIN_COLUMNS = {"scope": "visibility_job_id", "rag": "rag_job_id", "search": "search_job_id"}
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "15s"


def _authority(db: Session) -> None:
    with db.no_autoflush:
        if (
            db.get_bind().dialect.name != "postgresql"
            or db.connection().connection.driver_connection.autocommit is True
            or db.scalar(text("SHOW transaction_isolation")) != "read committed"
        ):
            raise DocsLegacyRepairError("docs_repair_requires_read_committed")
        for table, privilege in (
            ("docs_legacy_projection_repairs", "INSERT"),
            ("docs_legacy_projection_repair_targets", "INSERT"),
            ("retrieval_projection_events", "INSERT"),
            ("retrieval_projection_heads", "UPDATE"),
        ):
            if not db.scalar(
                text("SELECT has_table_privilege(session_user,:table,:privilege)"),
                {
                    "table": "public." + table,
                    "privilege": privilege,
                },
            ):
                raise DocsLegacyRepairError("docs_repair_core_authority_required")


def _receipt_id(kind: LegacyDocsJobKind, job_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"miy:core:docs-legacy-repair:v1:{kind}:{job_id}"))


def _job(db: Session, kind: LegacyDocsJobKind, job_id: str, *, lock=False):
    model = _MODELS.get(kind)
    if model is None:
        raise DocsLegacyRepairError("docs_repair_origin_invalid")
    query = select(model).where(model.id == job_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def _is_docs(kind: LegacyDocsJobKind, job) -> bool:
    return job is not None and (
        (kind == "scope" and job.scope_type == "meeting")
        or (kind == "rag" and job.resource_type == RESOURCE_TYPE)
        or (kind == "search" and job.entity_type == "doc")
    )


def _fenced(db: Session, kind: LegacyDocsJobKind, job) -> bool:
    if kind == "scope":
        return False
    values = (
        job.retrieval_partition_id,
        job.projection_event_sequence,
        job.projection_version,
        job.desired_state,
    )
    if not any(value is not None for value in values):
        if kind == "search" and job.resource_type is not None:
            raise DocsLegacyRepairError("docs_repair_partial_fence")
        return False
    if not all(value is not None for value in values):
        raise DocsLegacyRepairError("docs_repair_partial_fence")
    event = db.get(RetrievalProjectionEvent, job.projection_event_sequence, populate_existing=True)
    resource_id = job.entity_id if kind == "search" else job.resource_id
    if event is None or (
        event.resource_type,
        event.resource_id,
        event.retrieval_partition_id,
        event.projection_version,
        event.desired_state,
    ) != (RESOURCE_TYPE, resource_id, values[0], values[2], values[3]):
        raise DocsLegacyRepairError("docs_repair_fence_conflict")
    if job.resource_type != RESOURCE_TYPE or (job.operation == "delete") != (
        event.desired_state == "deleted"
    ):
        raise DocsLegacyRepairError("docs_repair_fence_conflict")
    if kind == "rag" and (job.content_checksum, job.visibility_checksum) != (
        event.content_checksum,
        event.visibility_checksum,
    ):
        raise DocsLegacyRepairError("docs_repair_fence_conflict")
    return True


def _input(kind: LegacyDocsJobKind, job) -> str:
    payload = {"schema_version": 1, "kind": kind, "job_id": identifier(job.id)}
    if kind == "scope":
        cursor = job.cursor or {}
        if not isinstance(cursor, dict) or set(cursor) - {"doc_ids"}:
            raise DocsLegacyRepairError("docs_repair_cursor_invalid")
        ids = cursor.get("doc_ids", [])
        if not isinstance(ids, list) or len(ids) > 1000:
            raise DocsLegacyRepairError("docs_repair_input_budget")
        payload.update(
            scope_id=identifier(job.scope_id),
            operation="visibility_update",
            captured_ids=sorted({identifier(value) for value in ids}),
            lane="realtime",
        )
    else:
        payload.update(
            resource_id=identifier(job.entity_id if kind == "search" else job.resource_id),
            operation=job.operation,
            lane=job.lane if kind == "rag" else "realtime",
        )
        if kind == "rag":
            payload.update(
                scope_kind=job.scope_kind,
                content_checksum=job.content_checksum,
                visibility_checksum=job.visibility_checksum,
            )
    return canonical(payload)


def _targets(db: Session, kind: LegacyDocsJobKind, payload: dict) -> list[str]:
    if kind != "scope":
        return [payload["resource_id"]]
    ids = set(payload["captured_ids"])
    meeting = payload["scope_id"]
    for column, predicate in (
        (MeetingDocLink.doc_id, MeetingDocLink.meeting_id == meeting),
        (DocMeetingAccess.doc_id, DocMeetingAccess.granted_by_meeting_id == meeting),
        (Meeting.notes_doc_id, Meeting.id == meeting),
    ):
        ids.update(
            identifier(value)
            for value in db.scalars(
                select(column)
                .where(predicate, column.is_not(None))
                .distinct()
                .limit(MAX_TARGETS + 1)
            )
        )
    if len(ids) > MAX_TARGETS:
        raise DocsLegacyRepairError("docs_repair_target_budget")
    return sorted(ids)


def _admission(db: Session, kind: LegacyDocsJobKind) -> bool:
    if not is_company_app_enabled(db, "docs"):
        raise DocsLegacyRepairError("docs_repair_app_disabled")
    rag = bool(get_settings().rag_enabled)
    if kind != "search" and not rag:
        raise DocsLegacyRepairError("docs_repair_rag_disabled")
    return rag


def _verify_receipt(db: Session, receipt, *, kind: LegacyDocsJobKind, payload: str):
    if (
        receipt.schema_version != 1
        or receipt.input_payload != payload
        or receipt.input_digest != digest(payload)
        or getattr(receipt, _ORIGIN_COLUMNS[kind]) != json.loads(payload)["job_id"]
    ):
        raise DocsLegacyRepairError("docs_repair_receipt_conflict")
    targets = list(
        db.scalars(
            select(DocsLegacyProjectionRepairTarget)
            .where(DocsLegacyProjectionRepairTarget.receipt_id == receipt.id)
            .order_by(DocsLegacyProjectionRepairTarget.resource_id)
        )
    )
    if (
        len(targets) != receipt.target_count
        or canonical([t.resource_id for t in targets]) != receipt.targets_payload
    ):
        raise DocsLegacyRepairError("docs_repair_receipt_conflict")
    for target in targets:
        event = db.get(RetrievalProjectionEvent, target.core_event_sequence, populate_existing=True)
        if (
            event is None
            or event.resource_type != RESOURCE_TYPE
            or event.resource_id != target.resource_id
            or event.change_kind != "repair"
            or (event.desired_state == "deleted") != (target.operation == "delete")
            or receipt.rag_enabled != (target.rag_job_id is not None)
        ):
            raise DocsLegacyRepairError("docs_repair_receipt_conflict")
    return receipt


def _current_source(db: Session, resource_id: str, requested_operation: str):
    pending = db.scalar(
        select(
            exists().where(
                OfficialProjectionOutbox.resource_type == RESOURCE_TYPE,
                OfficialProjectionOutbox.resource_id == resource_id,
                ~exists().where(
                    OfficialProjectionReceipt.event_id == OfficialProjectionOutbox.event_id
                ),
            )
        )
    )
    if pending:
        raise DocsLegacyRepairError("docs_repair_source_intent_pending")
    # Plain source SELECT only. FOR SHARE/UPDATE would require source UPDATE
    # privilege and invert the canonical source-row -> stream lock order.
    source = db.execute(
        select(NativeDoc.retrieval_partition_id, NativeDoc.trashed_at).where(
            NativeDoc.id == resource_id
        )
    ).one_or_none()
    head = db.scalar(
        select(RetrievalProjectionHead)
        .where(
            RetrievalProjectionHead.resource_type == RESOURCE_TYPE,
            RetrievalProjectionHead.resource_id == resource_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if head is not None:
        current_event = db.scalar(
            select(RetrievalProjectionEvent).where(
                RetrievalProjectionEvent.resource_type == RESOURCE_TYPE,
                RetrievalProjectionEvent.resource_id == resource_id,
                RetrievalProjectionEvent.projection_version == head.projection_version,
            )
        )
        if current_event is None or (
            current_event.retrieval_partition_id,
            current_event.desired_state,
        ) != (head.retrieval_partition_id, head.desired_state):
            raise DocsLegacyRepairError("docs_repair_head_conflict")
    if source is None and head is None:
        raise DocsLegacyRepairError("docs_repair_source_unobserved")
    partition_id = (
        source.retrieval_partition_id if source is not None else head.retrieval_partition_id
    )
    if not partition_id or (head is not None and head.retrieval_partition_id != partition_id):
        raise DocsLegacyRepairError("docs_repair_partition_conflict")
    partition = db.scalar(
        select(RetrievalPartition)
        .where(RetrievalPartition.id == partition_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        partition is None
        or partition.state != "active"
        or partition.source_namespace != "docs"
        or partition.candidate_scope_kind != "company"
    ):
        raise DocsLegacyRepairError("docs_repair_partition_invalid")
    deleted = source is None or source.trashed_at is not None
    if not deleted and (head is not None and head.desired_state == "deleted"):
        raise DocsLegacyRepairError("docs_repair_tombstone_conflict")
    if not deleted and requested_operation == "delete" and head is None:
        raise DocsLegacyRepairError("docs_repair_restore_unproven")
    operation = (
        "delete"
        if deleted
        else ("upsert" if requested_operation == "delete" else requested_operation)
    )
    return partition, operation


def repair_docs_legacy_job(db: Session, *, kind: LegacyDocsJobKind, job_id: str):
    """Return an exact receipt or None for unrelated/already-fenced work; never commit."""
    with db.no_autoflush:
        job = _job(db, kind, identifier(job_id))
        if not _is_docs(kind, job):
            return None
        if _fenced(db, kind, job):
            return None
        _authority(db)
        if db.new or db.dirty or db.deleted:
            raise DocsLegacyRepairError("docs_repair_clean_transaction_required")
        payload = _input(kind, job)
        receipt_id = _receipt_id(kind, job_id)
        receipt = db.get(DocsLegacyProjectionRepair, receipt_id, populate_existing=True)
        if receipt is not None:
            return _verify_receipt(db, receipt, kind=kind, payload=payload)
        if job.status != "pending":
            raise DocsLegacyRepairError("docs_repair_origin_not_pending")
        rag_enabled = _admission(db, kind)
        parsed = json.loads(payload)
        targets = _targets(db, kind, parsed)
        for setting, value in (
            ("lock_timeout", LOCK_TIMEOUT),
            ("statement_timeout", STATEMENT_TIMEOUT),
        ):
            db.execute(
                text("SELECT set_config(:setting,:value,true)"),
                {"setting": setting, "value": value},
            )
        for resource_id in targets:
            lock_projection_source(db, RESOURCE_TYPE, resource_id)
            lock_projection_stream(db, resource_type=RESOURCE_TYPE, resource_id=resource_id)
            db.scalar(
                select(RetrievalProjectionHead)
                .where(
                    RetrievalProjectionHead.resource_type == RESOURCE_TYPE,
                    RetrievalProjectionHead.resource_id == resource_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        job = _job(db, kind, job_id, lock=True)
        if not _is_docs(kind, job) or _input(kind, job) != payload:
            raise DocsLegacyRepairError("docs_repair_origin_changed")
        receipt = db.get(DocsLegacyProjectionRepair, receipt_id, populate_existing=True)
        if receipt is not None:
            return _verify_receipt(db, receipt, kind=kind, payload=payload)
        if job.status != "pending" or _fenced(db, kind, job):
            raise DocsLegacyRepairError("docs_repair_origin_changed")
        if _targets(db, kind, parsed) != targets or _admission(db, kind) != rag_enabled:
            raise DocsLegacyRepairError("docs_repair_snapshot_changed")
        current = [
            (resource_id, *_current_source(db, resource_id, parsed["operation"]))
            for resource_id in targets
        ]
        receipt = DocsLegacyProjectionRepair(
            id=receipt_id,
            **{_ORIGIN_COLUMNS[kind]: job_id},
            schema_version=1,
            input_payload=payload,
            input_digest=digest(payload),
            targets_payload=canonical(targets),
            target_count=len(targets),
            rag_enabled=rag_enabled,
        )
        # A pending keyword upsert can otherwise reuse the origin row, which
        # would subsequently be cancelled as its own replacement.
        job.status = "succeeded" if kind == "scope" else "cancelled"
        job.last_error = "docs_repair_replaced" if kind != "scope" else None
        job.updated_at = utcnow_naive()
        job.next_retry_at = None
        db.add(receipt)
        db.flush()
        for resource_id, partition, operation in current:
            event = record_projection_event(
                db,
                resource_type=RESOURCE_TYPE,
                resource_id=resource_id,
                retrieval_partition_id=partition.id,
                change_kind="repair",
                desired_state="deleted" if operation == "delete" else "active",
            )
            search = enqueue_search_index_job(
                db,
                entity_type="doc",
                entity_id=resource_id,
                operation="delete" if operation == "delete" else "upsert",
                projection_event=event,
            )
            rag = None
            if rag_enabled:
                rag = enqueue_rag_sync_job(
                    db,
                    scope_kind=partition.candidate_scope_kind,
                    resource_type=RESOURCE_TYPE,
                    resource_id=resource_id,
                    operation=RagSyncOperation(operation),
                    lane=RagSyncLane(parsed["lane"]),
                    projection_event=event,
                )
            db.add(
                DocsLegacyProjectionRepairTarget(
                    receipt_id=receipt_id,
                    resource_id=resource_id,
                    core_event_sequence=event.event_sequence,
                    operation=operation,
                    search_job_id=search.id,
                    rag_job_id=rag.id if rag else None,
                )
            )
        db.flush()
        if _admission(db, kind) != rag_enabled:
            raise DocsLegacyRepairError("docs_repair_snapshot_changed")
        return receipt


def dispatch_docs_legacy_repair(db: Session, *, kind: LegacyDocsJobKind, job_id: str) -> str | None:
    """Before ordinary claim/provider dispatch; bypass generic retry/merge on failure."""
    try:
        receipt = repair_docs_legacy_job(db, kind=kind, job_id=job_id)
        if receipt is None:
            return None
        outcome = "docs-repair-converted" if receipt.target_count else "docs-repair-empty"
        db.commit()
        return outcome
    except Exception as error:
        try:
            db.rollback()
        except Exception:
            raise DocsLegacyRepairError("docs_repair_outcome_unknown") from None
        if isinstance(error, DocsLegacyRepairError):
            raise
        # Includes COMMIT ACK loss. Never feed it to a business retry or erase
        # its job/receipt; reconciling the same origin ID is the only replay.
        raise DocsLegacyRepairError("docs_repair_outcome_unknown") from None
