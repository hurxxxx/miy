"""Core-only acceptance of four fixed source streams in the caller transaction.

No consumer, HTTP authority, activation switch or commit is created here. An
exception requires the caller to roll back; a lost commit ACK is reconciled by
this same event ID, never by re-executing the original business operation.
"""

from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_outbox import (
    lock_projection_source,
    require_current_transaction,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef, record_projection_event


def _core_authority(db: Session) -> None:
    require_current_transaction(db)
    with db.no_autoflush:
        if not db.scalar(
            text(
                "SELECT has_table_privilege(session_user,'public.official_projection_receipts','INSERT') AND has_table_privilege(session_user,'public.retrieval_projection_heads','UPDATE') AND has_table_privilege(session_user,'public.retrieval_projection_events','INSERT')"
            )
        ):
            raise ProjectionOutboxError("projection_core_authority_required")


def lookup_projection_receipt(db: Session, *, event_id: str) -> OfficialProjectionReceipt | None:
    """Absence is only currently unobserved, not proof another COMMIT failed."""
    _core_authority(db)
    return db.get(OfficialProjectionReceipt, str(UUID(event_id)), populate_existing=True)


def pending_projection_intents(db: Session, *, limit: int = 100) -> list[OfficialProjectionOutbox]:
    _core_authority(db)
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ProjectionOutboxError("projection_batch_limit_invalid")
    return list(
        db.scalars(
            select(OfficialProjectionOutbox)
            .where(
                ~exists().where(
                    OfficialProjectionReceipt.event_id == OfficialProjectionOutbox.event_id
                )
            )
            .order_by(OfficialProjectionOutbox.created_at, OfficialProjectionOutbox.event_id)
            .limit(limit)
        )
    )


def accept_projection_intent(
    db: Session, *, event_id: str, expected_digest: str
) -> OfficialProjectionReceipt:
    """Legacy Core acceptance; existing transaction behavior is unchanged."""
    return _accept_projection_intent(
        db, event_id=event_id, expected_digest=expected_digest, prepared_company=False
    )


def accept_prepared_projection_intent(
    db: Session, *, event_id: str, expected_digest: str
) -> OfficialProjectionReceipt:
    """Prepared company streams retain Core metadata SHARE through caller COMMIT."""
    return _accept_projection_intent(
        db, event_id=event_id, expected_digest=expected_digest, prepared_company=True
    )


def accept_prepared_file_projection_intent(
    db: Session, *, event_id: str, expected_digest: str
) -> OfficialProjectionReceipt:
    """Fixed Files control acceptance; pending never starts extraction or jobs."""
    return _accept_projection_intent(
        db,
        event_id=event_id,
        expected_digest=expected_digest,
        prepared_company=False,
        prepared_files=True,
    )


def _accept_projection_intent(
    db: Session,
    *,
    event_id: str,
    expected_digest: str,
    prepared_company: bool,
    prepared_files: bool = False,
) -> OfficialProjectionReceipt:
    _core_authority(db)
    if prepared_files:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='15s'"))
    event = db.get(OfficialProjectionOutbox, str(UUID(event_id)), populate_existing=True)
    if event is None:
        raise ProjectionOutboxError("projection_event_unobserved")
    if prepared_files and event.resource_type != "file_manager_file":
        raise ProjectionOutboxError("projection_consumer_resource_unavailable")
    intent = ProjectionIntent.model_validate_json(event.payload)
    if (event.payload, event.payload_digest, event.resource_type, event.resource_id) != (
        intent.canonical(),
        intent.digest(),
        intent.resource_type,
        intent.resource_id,
    ) or expected_digest != event.payload_digest:
        raise ProjectionOutboxError("projection_event_conflict")
    lock_projection_source(db, event.resource_type, event.resource_id)
    existing = db.get(OfficialProjectionReceipt, event.event_id, populate_existing=True)
    if existing is not None:
        if (
            existing.payload_digest,
            existing.resource_type,
            existing.resource_id,
            existing.source_revision,
        ) != (event.payload_digest, event.resource_type, event.resource_id, event.source_revision):
            raise ProjectionOutboxError("projection_receipt_conflict")
        return existing
    missing_previous = db.scalar(
        select(
            exists().where(
                OfficialProjectionOutbox.resource_type == event.resource_type,
                OfficialProjectionOutbox.resource_id == event.resource_id,
                OfficialProjectionOutbox.source_revision < event.source_revision,
                ~exists().where(
                    OfficialProjectionReceipt.event_id == OfficialProjectionOutbox.event_id
                ),
            )
        )
    )
    if missing_previous:
        raise ProjectionOutboxError("projection_revision_gap")
    newer = db.scalar(
        select(
            exists().where(
                OfficialProjectionOutbox.resource_type == event.resource_type,
                OfficialProjectionOutbox.resource_id == event.resource_id,
                OfficialProjectionOutbox.source_revision > event.source_revision,
            )
        )
    )
    core_event = None
    if not newer:
        file_outcome = None
        if prepared_files:
            file_outcome = _validate_file_partition_and_outcome(db, intent)
        else:
            _validate_partition(db, intent, prepared_company=prepared_company)
        core_event = record_projection_event(
            db, **intent.model_dump(mode="json", exclude={"operation"})
        )
        if prepared_files:
            _stage_file_jobs(db, intent, core_event, outcome=file_outcome)
        elif prepared_company:
            _stage_jobs(db, intent, core_event, publish_after_commit=False)
        else:
            _stage_jobs(db, intent, core_event)
    receipt = OfficialProjectionReceipt(
        event_id=event.event_id,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        source_revision=event.source_revision,
        payload_digest=event.payload_digest,
        status="superseded" if newer else "accepted",
        core_event_sequence=core_event.event_sequence if core_event else None,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _validate_file_partition_and_outcome(db: Session, intent: ProjectionIntent) -> str:
    """Read the fixed current descriptor only; no Source row lock or storage IO."""
    from miy_api.domains.files.artifact_contract import is_file_artifact_checksum
    from miy_api.domains.files.models import (
        FileManagerCorpus,
        FileManagerFile,
        FileManagerFileSourceMetadata,
    )

    partition_id = str(intent.retrieval_partition_id)
    locked = db.scalar(
        text("SELECT public.miy_lock_file_projection_partition(CAST(:partition AS uuid))"),
        {"partition": partition_id},
    )
    partition = db.get(RetrievalPartition, partition_id, populate_existing=True)
    if (
        str(locked) != partition_id
        or partition is None
        or partition.state != "active"
        or partition.source_namespace != "files"
        or partition.candidate_scope_kind != "company"
    ):
        raise ProjectionOutboxError("projection_partition_invalid")
    file = db.execute(
        select(
            FileManagerFile.id,
            FileManagerFile.retrieval_partition_id,
            FileManagerFile.corpus_id,
            FileManagerFile.deleted_at,
            FileManagerFile.extraction_status,
            FileManagerFile.extraction_content_checksum,
        ).where(FileManagerFile.id == intent.resource_id)
    ).one_or_none()
    deleted = intent.desired_state == "deleted"
    if deleted and intent.content_checksum is not None:
        raise ProjectionOutboxError("projection_file_delete_checksum_invalid")
    if file is None:
        if not deleted:
            raise ProjectionOutboxError("projection_source_unobserved")
        head = db.get(
            RetrievalProjectionHead,
            (intent.resource_type, intent.resource_id),
            populate_existing=True,
        )
        if head is not None and head.retrieval_partition_id != partition_id:
            raise ProjectionOutboxError("projection_partition_changed")
        return "deleted"
    if file.retrieval_partition_id != partition_id:
        raise ProjectionOutboxError("projection_partition_changed")
    if file.corpus_id is not None:
        corpus = db.execute(
            select(
                FileManagerCorpus.id,
                FileManagerCorpus.retrieval_partition_id,
                FileManagerCorpus.access_scope_kind,
            ).where(FileManagerCorpus.id == file.corpus_id)
        ).one_or_none()
        if (
            corpus is None
            or corpus.retrieval_partition_id != partition_id
            or corpus.access_scope_kind != "company"
        ):
            raise ProjectionOutboxError("projection_partition_changed")
    metadata = db.execute(
        select(
            FileManagerFileSourceMetadata.file_id,
            FileManagerFileSourceMetadata.corpus_id,
            FileManagerFileSourceMetadata.content_checksum,
        ).where(FileManagerFileSourceMetadata.file_id == file.id)
    ).one_or_none()
    if metadata is not None and metadata.corpus_id != file.corpus_id:
        raise ProjectionOutboxError("projection_partition_changed")
    if deleted:
        if file.deleted_at is not None or (
            file.extraction_status == "unsupported" and file.extraction_content_checksum is None
        ):
            return "deleted"
        raise ProjectionOutboxError("projection_file_delete_source_conflict")
    if file.deleted_at is not None:
        raise ProjectionOutboxError("projection_source_unobserved")
    if intent.content_checksum is None:
        if (
            file.extraction_status in {"pending", "failed"}
            and file.extraction_content_checksum is None
        ):
            return "pending"
        raise ProjectionOutboxError("projection_file_pending_source_conflict")
    if (
        not is_file_artifact_checksum(intent.content_checksum)
        or file.extraction_status != "ready"
        or file.extraction_content_checksum != intent.content_checksum
        or (metadata is not None and metadata.content_checksum != intent.content_checksum)
    ):
        raise ProjectionOutboxError("projection_file_ready_checksum_conflict")
    return "ready"


def _stage_file_jobs(
    db: Session, intent: ProjectionIntent, event: ProjectionEventRef, *, outcome: str
) -> None:
    from miy_api.domains.files.retrieval_contract import FILES_RETRIEVAL_ACTIVE

    if outcome == "pending" or not FILES_RETRIEVAL_ACTIVE or not get_settings().rag_enabled:
        return
    from miy_api.domains.rag.contracts import RagSyncOperation
    from miy_api.domains.rag.outbox import enqueue_rag_sync_job
    from miy_api.domains.search.outbox import enqueue_search_index_job

    enqueue_search_index_job(
        db,
        entity_type="file",
        entity_id=intent.resource_id,
        operation="delete" if outcome == "deleted" else "upsert",
        projection_event=event,
        trace_context=intent.trace_context,
        publish_after_commit=False,
    )
    enqueue_rag_sync_job(
        db,
        scope_kind="company",
        resource_type="file_manager_file",
        resource_id=intent.resource_id,
        operation=RagSyncOperation(intent.operation),
        projection_event=event,
        trace_context=intent.trace_context,
        publish_after_commit=False,
    )


def _validate_partition(
    db: Session, intent: ProjectionIntent, *, prepared_company: bool = False
) -> None:
    from miy_api.domains.retrieval.default_partition_adapters import (
        ensure_retrieval_partition_adapters_registered,
    )
    from miy_api.domains.retrieval.partition_adapter_registry import (
        get_retrieval_partition_adapter_for_resource,
    )
    from miy_api.domains.retrieval.partitioning import RetrievalPartitionUnbound, bind_projection

    ensure_retrieval_partition_adapters_registered()
    adapter = get_retrieval_partition_adapter_for_resource(intent.resource_type)
    partition_id = str(intent.retrieval_partition_id)
    if prepared_company:
        namespace = {
            "docs_native_doc": "docs",
            "pms_task": "pms",
            "meeting": "meeting",
        }.get(intent.resource_type)
        if namespace is None:
            raise ProjectionOutboxError("projection_consumer_resource_unavailable")
        locked = db.scalar(
            text(
                "SELECT public.miy_lock_official_projection_partition(CAST(:partition AS uuid), :namespace)"
            ),
            {"partition": partition_id, "namespace": namespace},
        )
        if locked is None or str(locked) != partition_id:
            raise ProjectionOutboxError("projection_partition_invalid")
    partition = db.get(RetrievalPartition, partition_id, populate_existing=True)
    if (
        adapter is None
        or partition is None
        or partition.state != "active"
        or partition.source_namespace != adapter.source_namespace
        or partition.candidate_scope_kind not in adapter.allowed_candidate_scopes
    ):
        raise ProjectionOutboxError("projection_partition_invalid")
    try:
        binding = bind_projection(
            db, resource_type=intent.resource_type, resource_id=intent.resource_id
        )
    except RetrievalPartitionUnbound:
        # A hard-delete intent survives its source. Its old head, when present,
        # must agree; namespace/state checks above still apply without a head.
        if intent.desired_state != "deleted":
            raise ProjectionOutboxError("projection_source_unobserved") from None
        head = db.get(
            RetrievalProjectionHead,
            (intent.resource_type, intent.resource_id),
            populate_existing=True,
        )
        if head is not None and head.retrieval_partition_id != partition_id:
            raise ProjectionOutboxError("projection_partition_changed") from None
    else:
        if binding.partition_id != partition_id:
            raise ProjectionOutboxError("projection_partition_changed")


def _stage_jobs(
    db: Session,
    intent: ProjectionIntent,
    event: ProjectionEventRef,
    *,
    publish_after_commit: bool = True,
) -> None:
    from miy_api.domains.files.retrieval_contract import FILES_RETRIEVAL_ACTIVE
    from miy_api.domains.rag.contracts import RagSyncOperation
    from miy_api.domains.rag.outbox import enqueue_rag_sync_job
    from miy_api.domains.search.outbox import enqueue_search_index_job

    resource = intent.resource_type
    deleted = intent.desired_state == "deleted"
    publication_options = {} if publish_after_commit else {"publish_after_commit": False}
    # Preserve the existing Files extraction-before-keyword-index gate.
    search = resource != "file_manager_file" or (FILES_RETRIEVAL_ACTIVE and deleted)
    if search:
        entity = {
            "docs_native_doc": "doc",
            "pms_task": "pms_task",
            "meeting": "meeting",
            "file_manager_file": "file",
        }[resource]
        enqueue_search_index_job(
            db,
            entity_type=entity,
            entity_id=intent.resource_id,
            operation="delete" if deleted else "upsert",
            projection_event=event,
            trace_context=intent.trace_context,
            **publication_options,
        )
    if get_settings().rag_enabled and (
        resource == "docs_native_doc"
        or (resource == "file_manager_file" and FILES_RETRIEVAL_ACTIVE)
    ):
        partition = db.get(RetrievalPartition, str(intent.retrieval_partition_id))
        operation = RagSyncOperation(intent.operation)
        enqueue_rag_sync_job(
            db,
            scope_kind=partition.candidate_scope_kind,
            resource_type=resource,
            resource_id=intent.resource_id,
            operation=operation,
            projection_event=event,
            trace_context=intent.trace_context,
            **publication_options,
        )


def receipt_projection_event(db: Session, receipt: OfficialProjectionReceipt) -> ProjectionEventRef:
    _core_authority(db)
    if receipt.core_event_sequence is None:
        raise ProjectionOutboxError("projection_event_superseded")
    event = db.get(RetrievalProjectionEvent, receipt.core_event_sequence)
    if event is None:
        raise ProjectionOutboxError("projection_receipt_event_missing")
    return ProjectionEventRef(
        event_sequence=event.event_sequence,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        projection_version=event.projection_version,
        retrieval_partition_id=event.retrieval_partition_id,
        change_kind=event.change_kind,
        desired_state=event.desired_state,
        content_checksum=event.content_checksum,
        visibility_checksum=event.visibility_checksum,
    )
