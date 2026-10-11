"""Explicit prepared Source delivery, separate from the unchanged legacy bridge.

The context is trusted internal composition, never authority. Actual PostgreSQL
roles/guards and the fixed Core default capability enforce that independently.
Receipts here describe Source appends, provisionally until the caller commits.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import (
    append_projection_intent,
    emit_and_accept_projection,
    require_current_transaction,
)

PREPARED_PROJECTION_RESOURCES = frozenset({"docs_native_doc", "pms_task", "meeting"})
_COMPOSITION_KEY = object()
_JOURNAL_LIMIT = 100


@dataclass(frozen=True)
class SourceProjectionReceipt:
    event_id: str
    resource_type: str
    resource_id: str
    source_revision: int
    payload_digest: str

    @classmethod
    def from_event(cls, event: OfficialProjectionOutbox) -> "SourceProjectionReceipt":
        return cls(
            event.event_id,
            event.resource_type,
            event.resource_id,
            event.source_revision,
            event.payload_digest,
        )


@dataclass
class SourceProjectionJournal:
    """Bounded local identities, not a durable business idempotency ledger."""

    _receipts: tuple[SourceProjectionReceipt, ...] = field(default=(), init=False, repr=False)

    @property
    def receipts(self) -> tuple[SourceProjectionReceipt, ...]:
        return self._receipts

    def _reserve(self, event_id: str) -> None:
        if len(self._receipts) >= _JOURNAL_LIMIT and all(
            receipt.event_id != event_id for receipt in self._receipts
        ):
            raise ProjectionOutboxError("projection_emission_limit_exceeded")

    def _record(self, receipt: SourceProjectionReceipt) -> None:
        existing = next((r for r in self._receipts if r.event_id == receipt.event_id), None)
        if existing is not None:
            if existing != receipt:
                raise ProjectionOutboxError("projection_event_conflict")
            return
        self._receipts += (receipt,)


@dataclass(frozen=True)
class _PreparedSourceComposition:
    journal: SourceProjectionJournal


def is_prepared_source_projection(db: Session) -> bool:
    return isinstance(db.info.get(_COMPOSITION_KEY), _PreparedSourceComposition)


@contextmanager
def prepared_source_projection(db: Session):
    """Compose one internal Session; no global runtime, grant or activation change.

    Retain the yielded provisional receipts when reconciling a lost COMMIT ACK.
    A process loss is not repaired by automatically rerunning business methods.
    """
    if _COMPOSITION_KEY in db.info:
        raise ProjectionOutboxError("projection_composition_already_prepared")
    journal = SourceProjectionJournal()
    db.info[_COMPOSITION_KEY] = _PreparedSourceComposition(journal)
    try:
        yield journal
    finally:
        db.info.pop(_COMPOSITION_KEY, None)


def emit_source_projection(
    db: Session, *, intent: ProjectionIntent, event_id: UUID | None = None
) -> SourceProjectionReceipt:
    """Append in the original Source transaction; never stage Core work or commit."""
    event = append_projection_intent(db, intent=intent, event_id=event_id)
    return SourceProjectionReceipt.from_event(event)


def lookup_source_projection_receipt(
    db: Session, *, event_id: str, expected_digest: str
) -> SourceProjectionReceipt | None:
    """Observe the same identity. Absence does not prove a COMMIT failed."""
    require_current_transaction(db)
    event = db.get(OfficialProjectionOutbox, str(UUID(event_id)), populate_existing=True)
    if event is None:
        return None
    intent = ProjectionIntent.model_validate_json(event.payload)
    if (event.payload, event.payload_digest, event.resource_type, event.resource_id) != (
        intent.canonical(),
        intent.digest(),
        intent.resource_type,
        intent.resource_id,
    ) or event.payload_digest != expected_digest:
        raise ProjectionOutboxError("projection_event_conflict")
    return SourceProjectionReceipt.from_event(event)


def deliver_projection_intent(
    db: Session, *, intent: ProjectionIntent, event_id: UUID | None = None
) -> None:
    """Hooks return no Core reference; prepared delivery records a genuine Source receipt."""
    context = db.info.get(_COMPOSITION_KEY)
    if not isinstance(context, _PreparedSourceComposition):
        emit_and_accept_projection(db, intent=intent, event_id=event_id)
        return
    if intent.resource_type not in PREPARED_PROJECTION_RESOURCES:
        raise ProjectionOutboxError("projection_source_composition_resource_unavailable")
    identifier = event_id or uuid4()
    context.journal._reserve(str(identifier))
    receipt = emit_source_projection(db, intent=intent, event_id=identifier)
    context.journal._record(receipt)
