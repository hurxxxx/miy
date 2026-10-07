"""Inactive Files effects: acknowledged durable arm, one live permit, exact history.

The fixed SQL capability owns lifecycle/Source locks and header integrity. These
owned Sessions supply COMMIT-ACK semantics that SQL cannot observe. No provider,
queue, Source writer or service is enabled by importing this module.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.domains.files.core_projection import prepared_core_file_projection
from miy_api.domains.auth.models import User
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.materialization_source import (
    FileMaterializationProjection,
    FileMaterializationSourceWitness,
    load_prepared_file_materialization,
    require_file_materialization_identity,
    require_unchanged_file_materialization,
)
from miy_api.domains.official_apps.file_materialization_effect_models import (
    FileMaterializationOperation,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionGeneration,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.models import SearchIndexJob

SessionFactory = Callable[[], Session]
_OPERATIONS = FileMaterializationOperation.__table__
_EVENT_FIELDS = tuple(ProjectionEventRef.__dataclass_fields__)
_PERMIT_KEY = object()
_QUERY_MODELS = (
    User,
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
    RetrievalPartition,
    RetrievalProjectionGeneration,
    FileMaterializationOperation,
    SearchIndexJob,
    RagSyncJob,
)


class FileMaterializationRefused(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _uuid(value: str) -> None:
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise FileMaterializationRefused("materialization_uuid_invalid") from None


@dataclass(frozen=True, slots=True)
class PreparedFileGenerationPair:
    keyword_generation_id: str
    vector_generation_id: str
    generation_key: str
    keyword_physical_name: str
    vector_physical_name: str
    keyword_schema_version: int = 3
    vector_schema_version: int = 1

    def __post_init__(self):
        _uuid(self.keyword_generation_id)
        _uuid(self.vector_generation_id)
        if self.keyword_generation_id == self.vector_generation_id:
            raise FileMaterializationRefused("materialization_pair_invalid")
        for value, budget in (
            (self.generation_key, 64),
            (self.keyword_physical_name, 255),
            (self.vector_physical_name, 255),
        ):
            if type(value) is not str or not value.strip() or len(value) > budget:
                raise FileMaterializationRefused("materialization_target_invalid")
        if (
            type(self.keyword_schema_version) is not int
            or self.keyword_schema_version != 3
            or type(self.vector_schema_version) is not int
            or self.vector_schema_version != 1
        ):
            raise FileMaterializationRefused("materialization_schema_invalid")


@dataclass(frozen=True, slots=True)
class FileMaterializationEffectSpec:
    operation_id: str
    projection_event: ProjectionEventRef
    generation_pair: PreparedFileGenerationPair
    partition_metadata_version: int

    def __post_init__(self):
        _uuid(self.operation_id)
        if not isinstance(self.projection_event, ProjectionEventRef) or not isinstance(
            self.generation_pair, PreparedFileGenerationPair
        ):
            raise FileMaterializationRefused("materialization_spec_invalid")
        if (
            type(self.partition_metadata_version) is not int
            or not 1 <= self.partition_metadata_version <= 2_147_483_647
        ):
            raise FileMaterializationRefused("materialization_partition_version_invalid")


@dataclass(frozen=True, slots=True)
class FileMaterializationEffectReceipt:
    spec: FileMaterializationEffectSpec
    witness: FileMaterializationSourceWitness
    source_extracted_at: datetime | None
    header_digest: str
    issuer_role_oid: int
    issuer_role_name: str
    state: str
    provisional: bool
    historical: bool


class FileMaterializationEffectUnknown(FileMaterializationRefused):
    def __init__(self, phase: str, receipt: FileMaterializationEffectReceipt):
        self.phase = phase
        self.receipt = receipt
        super().__init__("file_materialization_effect_unknown")


class FileMaterializationPreflightRefused(FileMaterializationRefused):
    def __init__(self, receipt: FileMaterializationEffectReceipt):
        self.receipt = receipt
        super().__init__("file_materialization_preflight_refused")


class _LiveFileMaterializationPermit:
    """Only a newly acknowledged arm can create this nonserializable frame."""

    def __init__(self, key, receipt, materialization):
        if key is not _PERMIT_KEY:
            raise FileMaterializationRefused("materialization_live_permit_required")
        self.receipt = receipt
        self.materialization = materialization
        self._used = False

    def consume(self) -> tuple[FileMaterializationEffectReceipt, FileMaterializationProjection]:
        if self._used:
            raise FileMaterializationRefused("materialization_permit_consumed")
        self._used = True
        return self.receipt, self.materialization

    def __reduce__(self):
        raise TypeError("materialization_live_permit_cannot_be_serialized")


def _fresh(db: Session) -> None:
    if not isinstance(db, Session):
        raise FileMaterializationRefused("materialization_session_required")
    engine = db.get_bind()
    if not isinstance(engine, Engine):
        raise FileMaterializationRefused("materialization_engine_binding_required")
    if db.in_transaction() or db.in_nested_transaction() or db.new or db.dirty or db.deleted:
        raise FileMaterializationRefused("materialization_fresh_session_required")
    # Default Engine binding alone misses per-mapper/table borrowed connections
    # or a second Engine. Every fixed query route must share this owned Engine.
    if any(
        db.get_bind(mapper=model) is not engine
        or db.get_bind(clause=select(model.__table__)) is not engine
        for model in _QUERY_MODELS
    ):
        raise FileMaterializationRefused("materialization_single_engine_required")


@contextmanager
def owned_file_materialization_session(factory: SessionFactory) -> Iterator[Session]:
    """Reject borrowed/pending work before SQL, rollback or closing it."""
    db = None
    owns = False
    try:
        try:
            db = factory()
        except Exception:
            raise FileMaterializationRefused("materialization_session_factory_failed") from None
        _fresh(db)
        owns = True
        require_file_materialization_identity(db)
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='15s'"))
        yield db
    except SQLAlchemyError:
        raise FileMaterializationRefused("materialization_database_refused") from None
    finally:
        if owns:
            # Cleanup cannot replace the body's typed outcome or a COMMIT ACK.
            # Arm/execute classify cancellation while they still own its receipt.
            try:
                if db.in_transaction():
                    db.rollback()
            except BaseException:
                pass
            try:
                db.close()
            except BaseException:
                pass


def lock_prepared_file_materialization(db: Session, spec: FileMaterializationEffectSpec) -> None:
    """Fixed capability precedes operation/job DML, including completion."""
    pair = spec.generation_pair
    matched = db.scalar(
        text(
            "SELECT public.miy_lock_file_materialization(:event_sequence,"
            "CAST(:keyword_id AS uuid),CAST(:vector_id AS uuid),:metadata_version)"
        ),
        {
            "event_sequence": spec.projection_event.event_sequence,
            "keyword_id": pair.keyword_generation_id,
            "vector_id": pair.vector_generation_id,
            "metadata_version": spec.partition_metadata_version,
        },
    )
    if str(matched) != spec.projection_event.retrieval_partition_id:
        raise FileMaterializationRefused("materialization_partition_mismatch")


def _input_header(spec: FileMaterializationEffectSpec) -> dict:
    pair = spec.generation_pair
    return {
        "operation_id": spec.operation_id,
        **{field: getattr(spec.projection_event, field) for field in _EVENT_FIELDS},
        "partition_metadata_version": spec.partition_metadata_version,
        **{
            field: getattr(pair, field) for field in PreparedFileGenerationPair.__dataclass_fields__
        },
    }


def _receipt(row, spec, *, provisional: bool, historical: bool):
    header = _input_header(spec)
    if any(row[field] != value for field, value in header.items()):
        raise FileMaterializationRefused("materialization_history_identity_mismatch")
    if row["state"] not in {"armed", "complete"}:
        raise FileMaterializationRefused("materialization_history_state_invalid")
    return FileMaterializationEffectReceipt(
        spec,
        FileMaterializationSourceWitness(
            str(row["source_event_id"]),
            int(row["source_revision"]),
            row["source_payload_digest"],
            spec.projection_event,
        ),
        row["source_extracted_at"],
        row["header_digest"],
        int(row["issuer_role_oid"]),
        row["issuer_role_name"],
        row["state"],
        provisional,
        historical,
    )


def _find(db, spec, *, locked=False):
    query = select(_OPERATIONS).where(_OPERATIONS.c.operation_id == spec.operation_id)
    if locked:
        query = query.with_for_update()
    return db.execute(query).mappings().one_or_none()


def _output_stamp(materialization: FileMaterializationProjection) -> datetime | None:
    if materialization.witness.projection_event.desired_state == "deleted":
        return None
    identity = materialization.source_identity
    if identity is None or identity.extracted_at is None:
        raise FileMaterializationRefused("materialization_result_stamp_required")
    return datetime.fromisoformat(identity.extracted_at).astimezone(UTC).replace(tzinfo=None)


class PreparedFileEffectRunner:
    """No retries. Effects and their refresh ACK precede one progress COMMIT."""

    def __init__(self, session_factory: SessionFactory):
        self._factory = session_factory

    def observe(self, spec, *, expected_header_digest: str | None = None):
        with owned_file_materialization_session(self._factory) as db:
            with prepared_core_file_projection(db, projection_event=spec.projection_event):
                row = _find(db, spec)
                if row is None:
                    return None  # Absence grants no retry or new permit.
                receipt = _receipt(row, spec, provisional=False, historical=True)
                if (
                    expected_header_digest is not None
                    and receipt.header_digest != expected_header_digest
                ):
                    raise FileMaterializationRefused("materialization_history_digest_mismatch")
                return receipt

    def arm(self, spec):
        with owned_file_materialization_session(self._factory) as db:
            with prepared_core_file_projection(db, projection_event=spec.projection_event):
                row = _find(db, spec)
                if row is not None:
                    return _receipt(row, spec, provisional=False, historical=True)
                lock_prepared_file_materialization(db, spec)
                # Recheck after the Source stream wait before touching operation rows.
                row = _find(db, spec)
                if row is not None:
                    return _receipt(row, spec, provisional=False, historical=True)
                materialization = load_prepared_file_materialization(
                    db, projection_event=spec.projection_event
                )
                witness = materialization.witness
                row = (
                    db.execute(
                        insert(_OPERATIONS)
                        .values(
                            **_input_header(spec),
                            source_event_id=witness.source_event_id,
                            source_revision=witness.source_revision,
                            source_payload_digest=witness.payload_digest,
                            source_extracted_at=_output_stamp(materialization),
                        )
                        .returning(*_OPERATIONS.c)
                    )
                    .mappings()
                    .one()
                )
                receipt = _receipt(row, spec, provisional=True, historical=False)
                try:
                    db.commit()
                except BaseException:
                    raise FileMaterializationEffectUnknown("arm_commit", receipt) from None
        return _LiveFileMaterializationPermit(
            _PERMIT_KEY, replace(receipt, provisional=False), materialization
        )

    def execute(self, permit, effect):
        if not isinstance(permit, _LiveFileMaterializationPermit):
            raise FileMaterializationRefused("materialization_live_permit_required")
        receipt, materialization = permit.consume()
        attempt_started = False
        try:
            with owned_file_materialization_session(self._factory) as db:
                spec = receipt.spec
                with prepared_core_file_projection(db, projection_event=spec.projection_event):
                    lock_prepared_file_materialization(db, spec)
                    row = _find(db, spec, locked=True)
                    if row is None:
                        raise FileMaterializationRefused("materialization_arm_unobserved")
                    current = _receipt(row, spec, provisional=False, historical=False)
                    if current.state != "armed" or current != receipt:
                        raise FileMaterializationRefused("materialization_arm_changed")

                    def fence():
                        lock_prepared_file_materialization(db, spec)
                        witness = require_unchanged_file_materialization(
                            db, materialization=materialization
                        )
                        if (
                            witness != receipt.witness
                            or _output_stamp(materialization) != receipt.source_extracted_at
                        ):
                            raise FileMaterializationRefused("materialization_output_changed")

                    fence()  # Before constructing any provider or starting compute.
                    attempt_started = True
                    effect(db, materialization, fence)
                    fence()  # Both backend and refresh ACKs precede completion.
                    row = (
                        db.execute(
                            update(_OPERATIONS)
                            .where(
                                _OPERATIONS.c.operation_id == spec.operation_id,
                                _OPERATIONS.c.state == "armed",
                                _OPERATIONS.c.header_digest == receipt.header_digest,
                            )
                            .values(state="complete")
                            .returning(*_OPERATIONS.c)
                        )
                        .mappings()
                        .one()
                    )
                    complete = _receipt(row, spec, provisional=True, historical=False)
                    try:
                        db.commit()
                    except BaseException:
                        raise FileMaterializationEffectUnknown(
                            "complete_commit", complete
                        ) from None
            return replace(complete, provisional=False)
        except FileMaterializationEffectUnknown:
            raise
        except BaseException:
            if not attempt_started:
                # Known zero provider/compute attempts. Keep the same durable
                # arm and consumed permit; this is not completion/retry authority.
                raise FileMaterializationPreflightRefused(receipt) from None
            # Even cancellation/provider construction may have crossed a remote
            # boundary. The acknowledged armed record remains unresolved.
            raise FileMaterializationEffectUnknown("effect", receipt) from None


__all__ = [
    "FileMaterializationEffectReceipt",
    "FileMaterializationEffectSpec",
    "FileMaterializationEffectUnknown",
    "FileMaterializationRefused",
    "FileMaterializationPreflightRefused",
    "PreparedFileEffectRunner",
    "PreparedFileGenerationPair",
    "lock_prepared_file_materialization",
    "owned_file_materialization_session",
]
