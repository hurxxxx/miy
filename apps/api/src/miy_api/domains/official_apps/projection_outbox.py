"""Append-only projection intent; the source writer never writes Core receipts."""

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
    SOURCE_TABLE_BY_RESOURCE,
)
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.source_guard import lock_source_writer


def require_current_transaction(db: Session) -> None:
    with db.no_autoflush:
        if (
            db.get_bind().dialect.name != "postgresql"
            or db.connection().connection.driver_connection.autocommit
            or db.scalar(text("SHOW transaction_isolation")) != "read committed"
        ):
            raise ProjectionOutboxError("projection_requires_read_committed")


def lock_projection_source(db: Session, resource_type: str, resource_id: str) -> None:
    require_current_transaction(db)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
        {"identity": f"official.projection:{resource_type}:{resource_id}"},
    )


def append_projection_intent(
    db: Session, *, intent: ProjectionIntent, event_id: UUID | None = None
) -> OfficialProjectionOutbox:
    """Caller commits source mutation and this intent together; replay is exact."""
    require_current_transaction(db)
    lock_source_writer(db, SOURCE_TABLE_BY_RESOURCE[intent.resource_type])
    identifier = str(event_id or uuid4())
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
        {"identity": "official.projection.event:" + identifier},
    )
    lock_projection_source(db, intent.resource_type, intent.resource_id)
    payload = intent.canonical()
    existing = db.get(OfficialProjectionOutbox, identifier, populate_existing=True)
    if existing is not None:
        if existing.payload != payload or existing.payload_digest != intent.digest():
            raise ProjectionOutboxError("projection_event_conflict")
        return existing
    tip = db.scalar(
        select(OfficialProjectionOutbox.source_revision)
        .where(
            OfficialProjectionOutbox.resource_type == intent.resource_type,
            OfficialProjectionOutbox.resource_id == intent.resource_id,
        )
        .order_by(OfficialProjectionOutbox.source_revision.desc())
        .limit(1)
    )
    event = OfficialProjectionOutbox(
        event_id=identifier,
        resource_type=intent.resource_type,
        resource_id=intent.resource_id,
        source_revision=(tip or 0) + 1,
        payload=payload,
        payload_digest=intent.digest(),
    )
    db.add(event)
    db.flush()
    db.refresh(event)
    return event


def emit_and_accept_projection(
    db: Session, *, intent: ProjectionIntent, event_id: UUID | None = None
):
    """Legacy same-transaction bridge; no HTTP/queue handoff or internal commit."""
    from miy_api.domains.retrieval.official_projection_ingress import (
        accept_projection_intent,
        receipt_projection_event,
    )

    event = append_projection_intent(db, intent=intent, event_id=event_id)
    receipt = accept_projection_intent(
        db, event_id=event.event_id, expected_digest=event.payload_digest
    )
    return receipt_projection_event(db, receipt)
