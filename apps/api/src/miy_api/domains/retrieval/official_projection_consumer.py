"""Bounded internal Core staging and same-event COMMIT reconciliation.

No HTTP, broker, task registration, business retry or automatic consumer exists.
The stage primitive uses a caller transaction; the runner owns a fresh Session.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session, aliased

from miy_api.domains.official_apps.projection_contracts import ProjectionOutboxError
from miy_api.domains.official_apps.projection_delivery import (
    PREPARED_PROJECTION_RESOURCES,
    SourceProjectionReceipt,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.retrieval.official_projection_ingress import (
    _core_authority,
    accept_prepared_projection_intent,
)


@dataclass(frozen=True)
class CoreProjectionConsumption:
    source: SourceProjectionReceipt
    status: str
    core_event_sequence: int | None


class ProjectionConsumptionCommitUnknown(ProjectionOutboxError):
    def __init__(self, consumption: CoreProjectionConsumption):
        super().__init__("projection_consumption_commit_unknown")
        self.consumption = consumption


def next_pending_projection(db: Session) -> SourceProjectionReceipt | None:
    """One stream's oldest unreceipted revision, with no commit-time cursor."""
    _bounded_core_transaction(db)
    earlier = aliased(OfficialProjectionOutbox)
    row = db.scalar(
        select(OfficialProjectionOutbox)
        .where(
            OfficialProjectionOutbox.resource_type.in_(PREPARED_PROJECTION_RESOURCES),
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
        .order_by(
            OfficialProjectionOutbox.resource_type,
            OfficialProjectionOutbox.resource_id,
            OfficialProjectionOutbox.source_revision,
        )
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return SourceProjectionReceipt.from_event(row) if row is not None else None


def consume_projection_once(
    db: Session, *, event_id: str, expected_digest: str
) -> CoreProjectionConsumption:
    """Stage one persisted Source event in the caller transaction, without COMMIT."""
    _bounded_core_transaction(db)
    if db.new or db.dirty or db.deleted:
        raise ProjectionOutboxError("projection_consumption_requires_clean_transaction")
    row = db.get(OfficialProjectionOutbox, str(UUID(event_id)), populate_existing=True)
    if row is None:
        raise ProjectionOutboxError("projection_event_unobserved")
    if row.resource_type not in PREPARED_PROJECTION_RESOURCES:
        raise ProjectionOutboxError("projection_consumer_resource_unavailable")
    receipt = accept_prepared_projection_intent(
        db, event_id=event_id, expected_digest=expected_digest
    )
    return CoreProjectionConsumption(
        SourceProjectionReceipt.from_event(row), receipt.status, receipt.core_event_sequence
    )


def _bounded_core_transaction(db: Session) -> None:
    _core_authority(db)
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    db.execute(text("SET LOCAL statement_timeout='15s'"))


def run_projection_consumer_once(
    session_factory: Callable[[], Session],
    *,
    event_id: str | None = None,
    expected_digest: str | None = None,
) -> CoreProjectionConsumption | None:
    """Own one fresh Core Session, stage one event and return only after COMMIT ACK.

    With no identity, discover one persisted stream head. Reconciliation supplies
    the exact previous UUID/digest; no Source operation or provider is repeated.
    """
    if (event_id is None) != (expected_digest is None):
        raise ProjectionOutboxError("projection_consumer_identity_required")
    with session_factory() as db:
        if db.in_transaction() or db.new or db.dirty or db.deleted:
            raise ProjectionOutboxError("projection_consumption_requires_fresh_session")
        _bounded_core_transaction(db)
        if event_id is None:
            source = next_pending_projection(db)
            if source is None:
                db.rollback()
                return None
            event_id, expected_digest = source.event_id, source.payload_digest
        assert event_id is not None and expected_digest is not None
        consumption = consume_projection_once(
            db, event_id=event_id, expected_digest=expected_digest
        )
        try:
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            raise ProjectionConsumptionCommitUnknown(consumption) from None
        return consumption
