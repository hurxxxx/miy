"""Fixed inactive Files Core staging, owned ACK and same-identity observation."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_delivery import SourceProjectionReceipt
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.retrieval.official_projection_ingress import (
    _core_authority,
    accept_prepared_file_projection_intent,
    receipt_projection_event,
)


@dataclass(frozen=True)
class FileProjectionConsumption:
    source: SourceProjectionReceipt
    status: str
    core_event_sequence: int | None
    provisional: bool = True


class FileProjectionConsumptionCommitUnknown(ProjectionOutboxError):
    def __init__(self, consumption: FileProjectionConsumption):
        super().__init__("file_projection_consumption_commit_unknown")
        self.consumption = consumption


def _bounded_core_transaction(db: Session) -> None:
    _core_authority(db)
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    db.execute(text("SET LOCAL statement_timeout='15s'"))


def _event_uuid(event_id: str) -> str:
    try:
        return str(UUID(event_id))
    except (ValueError, TypeError, AttributeError):
        raise ProjectionOutboxError("projection_event_identity_invalid") from None


def next_pending_file_projection(db: Session) -> SourceProjectionReceipt | None:
    """One oldest unreceipted Files revision per stream; never discovers old3."""
    _bounded_core_transaction(db)
    earlier = aliased(OfficialProjectionOutbox)
    row = db.scalar(
        select(OfficialProjectionOutbox)
        .where(
            OfficialProjectionOutbox.resource_type == "file_manager_file",
            ~exists().where(
                OfficialProjectionReceipt.event_id == OfficialProjectionOutbox.event_id
            ),
            ~exists().where(
                earlier.resource_type == OfficialProjectionOutbox.resource_type,
                earlier.resource_id == OfficialProjectionOutbox.resource_id,
                earlier.source_revision < OfficialProjectionOutbox.source_revision,
                ~exists().where(OfficialProjectionReceipt.event_id == earlier.event_id),
            ),
        )
        .order_by(OfficialProjectionOutbox.resource_id, OfficialProjectionOutbox.source_revision)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return SourceProjectionReceipt.from_event(row) if row is not None else None


def consume_file_projection_once(
    db: Session, *, event_id: str, expected_digest: str
) -> FileProjectionConsumption:
    """Stage one persisted Files event; the caller owns COMMIT and rollback."""
    if db.new or db.dirty or db.deleted:
        raise ProjectionOutboxError("projection_consumption_requires_clean_transaction")
    _bounded_core_transaction(db)
    row = db.get(OfficialProjectionOutbox, _event_uuid(event_id), populate_existing=True)
    if row is None:
        raise ProjectionOutboxError("projection_event_unobserved")
    receipt = accept_prepared_file_projection_intent(
        db, event_id=row.event_id, expected_digest=expected_digest
    )
    return FileProjectionConsumption(
        SourceProjectionReceipt.from_event(row), receipt.status, receipt.core_event_sequence
    )


def observe_file_projection_consumption(
    db: Session,
    *,
    event_id: str,
    expected_digest: str,
    expected_consumption: FileProjectionConsumption | None = None,
) -> FileProjectionConsumption | None:
    """Read same-ID history; caller-stage outcome stays provisional until ACK."""
    if db.new or db.dirty or db.deleted:
        raise ProjectionOutboxError("projection_consumption_requires_clean_transaction")
    _bounded_core_transaction(db)
    row = db.get(OfficialProjectionOutbox, _event_uuid(event_id), populate_existing=True)
    if row is None:
        raise ProjectionOutboxError("projection_event_unobserved")
    try:
        intent = ProjectionIntent.model_validate_json(row.payload)
    except ValueError:
        raise ProjectionOutboxError("projection_event_conflict") from None
    source = SourceProjectionReceipt.from_event(row)
    if source.resource_type != "file_manager_file":
        raise ProjectionOutboxError("projection_consumer_resource_unavailable")
    if (
        (row.payload, row.payload_digest, row.resource_type, row.resource_id)
        != (
            intent.canonical(),
            intent.digest(),
            intent.resource_type,
            intent.resource_id,
        )
        or source.payload_digest != expected_digest
        or (expected_consumption is not None and expected_consumption.source != source)
    ):
        raise ProjectionOutboxError("projection_event_conflict")
    receipt = db.get(OfficialProjectionReceipt, source.event_id, populate_existing=True)
    if receipt is None:
        return None
    if (
        receipt.resource_type,
        receipt.resource_id,
        receipt.source_revision,
        receipt.payload_digest,
    ) != (source.resource_type, source.resource_id, source.source_revision, source.payload_digest):
        raise ProjectionOutboxError("projection_receipt_conflict")
    if receipt.status == "accepted":
        core = receipt_projection_event(db, receipt)
        fields = (
            "resource_type",
            "resource_id",
            "retrieval_partition_id",
            "change_kind",
            "desired_state",
            "content_checksum",
            "visibility_checksum",
        )
        if tuple(str(getattr(core, key)) for key in fields) != tuple(
            str(getattr(intent, key)) for key in fields
        ):
            raise ProjectionOutboxError("projection_receipt_event_conflict")
    elif receipt.status != "superseded" or receipt.core_event_sequence is not None:
        raise ProjectionOutboxError("projection_receipt_conflict")
    observed = FileProjectionConsumption(source, receipt.status, receipt.core_event_sequence)
    if expected_consumption is not None and (
        observed.status,
        observed.core_event_sequence,
    ) != (expected_consumption.status, expected_consumption.core_event_sequence):
        raise ProjectionOutboxError("projection_receipt_conflict")
    return observed


def _fresh_core_session(db: Session) -> None:
    # A Session ACK must belong to its own actual outer transaction. Refuse
    # external Connection joins before SQL/autobegin and preserve borrowed work.
    if not isinstance(db.get_bind(), Engine):
        raise ProjectionOutboxError("file_projection_engine_binding_required")
    if db.in_transaction() or db.in_nested_transaction() or db.new or db.dirty or db.deleted:
        raise ProjectionOutboxError("projection_consumption_requires_fresh_session")


def _owned(
    session_factory: Callable[[], Session], function, **kwargs
) -> FileProjectionConsumption | None:
    try:
        db = session_factory()
    except SQLAlchemyError:
        raise ProjectionOutboxError("file_projection_session_factory_refused") from None
    owns_session = False
    try:
        _fresh_core_session(db)
        owns_session = True
        result = function(db, **kwargs)
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            if result is not None:
                raise FileProjectionConsumptionCommitUnknown(result) from None
            raise ProjectionOutboxError("file_projection_observation_commit_unknown") from None
        return replace(result, provisional=False) if result is not None else None
    except Exception as error:
        if owns_session:
            try:
                db.rollback()
            except Exception:
                pass
        if isinstance(error, SQLAlchemyError):
            raise ProjectionOutboxError("file_projection_database_refused") from None
        raise
    finally:
        if owns_session:
            try:
                db.close()
            except Exception:
                # Cleanup cannot revoke a COMMIT ACK or replace the retained
                # stable refusal/unknown outcome. It grants no retry permission.
                pass


def run_file_projection_consumer_once(
    session_factory: Callable[[], Session],
    *,
    event_id: str | None = None,
    expected_digest: str | None = None,
) -> FileProjectionConsumption | None:
    """Own one fresh Core Session; no automatic retry, provider, broker or loop."""
    if (event_id is None) != (expected_digest is None):
        raise ProjectionOutboxError("projection_consumer_identity_required")

    def stage(db: Session):
        source = None
        if event_id is None:
            source = next_pending_file_projection(db)
            if source is None:
                return None
        return consume_file_projection_once(
            db,
            event_id=source.event_id if source is not None else event_id,
            expected_digest=source.payload_digest if source is not None else expected_digest,
        )

    return _owned(session_factory, stage)


def run_file_projection_observation(
    session_factory: Callable[[], Session],
    *,
    event_id: str,
    expected_digest: str,
    expected_consumption: FileProjectionConsumption | None = None,
) -> FileProjectionConsumption | None:
    """Own a read-only observation transaction; never calls acceptance."""
    return _owned(
        session_factory,
        observe_file_projection_consumption,
        event_id=event_id,
        expected_digest=expected_digest,
        expected_consumption=expected_consumption,
    )
