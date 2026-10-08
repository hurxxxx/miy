"""Strict prepared Files composition sharing the existing batch/runner protocol.

Factories are explicit core-owned adapters. Real gateway/provider bounds and
service cutover remain separate; this inactive composition has no default route.
"""

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from miy_api.domains.rag.contracts import RagScopeKind, RagSyncOperation, RagSyncResult
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.official_apps.file_materialization_effect_models import (
    FileMaterializationOperation,
)
from miy_api.domains.retrieval.files_generation_materializer import (
    FilesCachedProjectionMaterializer,
    KeywordClientFactory,
    RagServiceFactory,
    _require_partitioned_keyword_generation_client,
)
from miy_api.domains.retrieval.files_generation_runner import (
    FilesGenerationPairSpec,
    FilesGenerationRuntimeSettings,
)
from miy_api.domains.retrieval.models import RetrievalProjectionEvent, RetrievalProjectionHead
from miy_api.domains.retrieval.prepared_file_effects import (
    FileMaterializationEffectReceipt,
    FileMaterializationEffectSpec,
    FileMaterializationEffectUnknown,
    FileMaterializationRefused,
    PreparedFileEffectRunner,
    PreparedFileGenerationPair,
    SessionFactory,
    owned_file_materialization_session,
)
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.models import SearchIndexJob

_EVENT_FIELDS = tuple(field.name for field in fields(ProjectionEventRef))


def resolve_prepared_file_projection_jobs(db: Session, event: ProjectionEventRef) -> None:
    """Same fenced legacy semantics, without loading private job payloads."""
    now = datetime.now(UTC).replace(tzinfo=None)
    for model, resource_column in (
        (SearchIndexJob, SearchIndexJob.entity_id),
        (RagSyncJob, RagSyncJob.resource_id),
    ):
        common = (
            model.status.in_(("pending", "processing")),
            model.resource_type == event.resource_type,
            resource_column == event.resource_id,
            model.projection_version.is_not(None),
        )
        db.execute(
            update(model)
            .where(*common, model.projection_version < event.projection_version)
            .values(
                status="cancelled",
                last_error="superseded_by_projection_head:generation_materializer",
                next_retry_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        operation = "delete"
        if event.desired_state != "deleted":
            operation = (
                "visibility_update"
                if model is RagSyncJob and event.change_kind == "visibility"
                else "upsert"
            )
        db.execute(
            update(model)
            .where(
                *common,
                model.projection_version == event.projection_version,
                model.projection_event_sequence == event.event_sequence,
                model.retrieval_partition_id == event.retrieval_partition_id,
                model.desired_state == event.desired_state,
                model.operation == operation,
            )
            .values(
                status="succeeded",
                attempts=model.attempts + 1,
                last_error=None,
                next_retry_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )


class PreparedFilesCachedProjectionMaterializer(FilesCachedProjectionMaterializer):
    requires_empty_reconciliation = True

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: FilesGenerationRuntimeSettings,
        generation_pair: PreparedFileGenerationPair,
        partition_metadata_version: int,
        keyword_client_factory: KeywordClientFactory,
        rag_service_factory: RagServiceFactory,
        retain_operation_id: Callable[[ProjectionEventRef, PreparedFileGenerationPair], str],
    ):
        super().__init__(
            session_factory=session_factory,
            settings=settings,
            keyword_client_factory=keyword_client_factory,
            rag_service_factory=rag_service_factory,
        )
        self._pair = generation_pair
        self._partition_version = partition_metadata_version
        if not callable(retain_operation_id):
            raise FileMaterializationRefused("materialization_retained_operation_required")
        self._retain_operation_id = retain_operation_id
        self._effects = PreparedFileEffectRunner(session_factory)

    def _open_session(self):
        return owned_file_materialization_session(self._session_factory)

    def materialize_batch(self, *, spec, after_event_sequence, through_event_sequence, limit):
        if (
            spec.generation_key != self._pair.generation_key
            or spec.opensearch_physical_name != self._pair.keyword_physical_name
            or spec.qdrant_physical_name != self._pair.vector_physical_name
        ):
            raise FileMaterializationRefused("materialization_batch_target_mismatch")
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(after_event_sequence) is not int
            or type(through_event_sequence) is not int
            or not 0 <= after_event_sequence <= through_event_sequence <= 9_223_372_036_854_775_807
        ):
            raise FileMaterializationRefused("materialization_batch_bounds_invalid")
        return super().materialize_batch(
            spec=spec,
            after_event_sequence=after_event_sequence,
            through_event_sequence=through_event_sequence,
            limit=limit,
        )

    def _outstanding_jobs(self, db: Session) -> tuple[int, int]:
        keyword, vector = super()._outstanding_jobs(db)
        # The observer protocol has no target argument. A conservative global
        # hold is explicit; no mutable last-spec can conceal older unknowns.
        unknown = int(
            db.scalar(
                select(func.count())
                .select_from(FileMaterializationOperation)
                .where(FileMaterializationOperation.state == "armed")
            )
            or 0
        )
        return keyword + unknown, vector + unknown

    def _materialize_events(
        self, *, spec: FilesGenerationPairSpec, events: list[int], complete: bool
    ):
        succeeded = 0
        for sequence in events:
            with self._open_session() as db:
                row = (
                    db.execute(
                        select(
                            *(getattr(RetrievalProjectionEvent, field) for field in _EVENT_FIELDS)
                        ).where(RetrievalProjectionEvent.event_sequence == sequence)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise FileMaterializationRefused("materialization_event_missing")
                event = ProjectionEventRef(**row)
                head_fields = (
                    "projection_version",
                    "retrieval_partition_id",
                    "desired_state",
                    "content_checksum",
                    "visibility_checksum",
                )
                head = db.execute(
                    select(
                        *(getattr(RetrievalProjectionHead, field) for field in head_fields)
                    ).where(
                        RetrievalProjectionHead.resource_type == event.resource_type,
                        RetrievalProjectionHead.resource_id == event.resource_id,
                    )
                ).one_or_none()
                if head is None:
                    raise FileMaterializationRefused("materialization_head_missing")
                if tuple(head) != tuple(getattr(event, field) for field in head_fields):
                    if head.projection_version > event.projection_version:
                        continue
                    raise FileMaterializationRefused("materialization_head_mismatch")
                historical = (
                    db.execute(
                        select(FileMaterializationOperation.__table__).where(
                            FileMaterializationOperation.event_sequence == sequence,
                            FileMaterializationOperation.keyword_generation_id
                            == self._pair.keyword_generation_id,
                            FileMaterializationOperation.vector_generation_id
                            == self._pair.vector_generation_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            operation_id = (
                historical["operation_id"]
                if historical
                else self._retain_operation_id(event, self._pair)
            )
            effect_spec = FileMaterializationEffectSpec(
                operation_id, event, self._pair, self._partition_version
            )
            armed = self._effects.arm(effect_spec)
            if isinstance(armed, FileMaterializationEffectReceipt):
                if armed.state != "complete":
                    raise FileMaterializationEffectUnknown("historical", armed)
                continue  # Historical ACK never reconstructs an effect permit.

            def effect(db, materialization, fence):
                keyword = _require_partitioned_keyword_generation_client(
                    self._keyword_client_factory(self._pair.keyword_physical_name)
                )
                rag = self._rag_service_factory(self._pair.vector_physical_name)
                if event.desired_state == "deleted":
                    fence()
                    outcome = keyword.delete_partitioned_document(
                        resource_type=event.resource_type,
                        resource_id=event.resource_id,
                        projection_version=event.projection_version,
                    )
                    _require_keyword_ack(outcome, "deleted")
                    fence()
                    result = rag.delete_projection(
                        scope_kind=RagScopeKind.COMPANY,
                        resource_type=event.resource_type,
                        resource_id=event.resource_id,
                        collection=self._pair.vector_physical_name,
                        retrieval_partition_id=event.retrieval_partition_id,
                    )
                    expected = RagSyncOperation.DELETE
                else:
                    keyword_ack = False

                    def before_vector_write():
                        nonlocal keyword_ack
                        if keyword_ack:
                            raise FileMaterializationRefused("materialization_callback_repeated")
                        fence()
                        outcome = keyword.upsert_partitioned_document(
                            materialization.keyword_document
                        )
                        _require_keyword_ack(outcome, "upserted")
                        keyword_ack = True

                    result = rag.sync_projection_with_fence(
                        materialization.rag_projection,
                        collection=self._pair.vector_physical_name,
                        before_vector_write=before_vector_write,
                    )
                    expected = RagSyncOperation.UPSERT
                    if not keyword_ack:
                        raise FileMaterializationRefused("materialization_keyword_ack_missing")
                if (
                    not isinstance(result, RagSyncResult)
                    or result.collection != self._pair.vector_physical_name
                    or result.operation != expected
                ):
                    raise FileMaterializationRefused("materialization_vector_ack_invalid")
                if expected is RagSyncOperation.UPSERT and result.chunk_count != len(
                    materialization.rag_projection.chunks
                ):
                    raise FileMaterializationRefused("materialization_vector_count_unproven")
                fence()
                keyword.refresh_partitioned_index()
                fence()
                resolve_prepared_file_projection_jobs(db, event)

            self._effects.execute(armed, effect)
            succeeded += 1
        return succeeded, succeeded


def _require_keyword_ack(outcome, expected: str) -> None:
    # Equal-version 'unchanged' says nothing about the stored body/result stamp.
    if type(outcome) is not str or outcome != expected:
        raise FileMaterializationRefused("materialization_keyword_ack_unproven")


__all__ = ["PreparedFilesCachedProjectionMaterializer", "resolve_prepared_file_projection_jobs"]
