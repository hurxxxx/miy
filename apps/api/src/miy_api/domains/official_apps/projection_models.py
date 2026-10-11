"""Suite transport intent and Core acceptance have separate write ownership."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE


class OfficialProjectionOutbox(Base):
    __tablename__ = "official_projection_outbox"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "source_revision",
            name="uq_official_projection_stream_revision",
        ),
        CheckConstraint("source_revision >= 1", name="ck_official_projection_source_revision"),
        CheckConstraint(
            "resource_type IN ('docs_native_doc','pms_task','meeting','file_manager_file')",
            name="ck_official_projection_source_type",
        ),
        CheckConstraint(
            "octet_length(payload) <= 8192", name="ck_official_projection_payload_size"
        ),
        CheckConstraint(
            "payload_digest ~ '^[a-f0-9]{64}$'", name="ck_official_projection_payload_digest"
        ),
        CheckConstraint(
            "producer_generation >= 1 AND producer_role_oid > 0",
            name="ck_official_projection_producer",
        ),
        Index("ix_official_projection_pending_order", "created_at", "event_id"),
    )
    writer_scope: Mapped[str] = mapped_column(
        String(80),
        ForeignKey(
            "official_runtime_ownership.scope", name="fk_official_projection_outbox_writer_scope"
        ),
        CheckConstraint(
            "writer_scope = 'official.suite'", name="ck_official_projection_outbox_writer_scope"
        ),
        server_default=SUITE_SCOPE,
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(255))
    source_revision: Mapped[int] = mapped_column(BigInteger)
    payload: Mapped[str] = mapped_column(Text)
    payload_digest: Mapped[str] = mapped_column(String(64))
    producer_generation: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    producer_artifact: Mapped[str | None] = mapped_column(String(71), server_default=FetchedValue())
    producer_role_oid: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    producer_role_name: Mapped[str] = mapped_column(String(63), server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class OfficialProjectionReceipt(Base):
    __tablename__ = "official_projection_receipts"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "source_revision",
            name="uq_official_projection_receipt_revision",
        ),
        CheckConstraint("source_revision >= 1", name="ck_official_projection_receipt_revision"),
        CheckConstraint(
            "status IN ('accepted','superseded')", name="ck_official_projection_receipt_status"
        ),
        CheckConstraint(
            "(status = 'accepted') = (core_event_sequence IS NOT NULL)",
            name="ck_official_projection_receipt_event",
        ),
    )
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("official_projection_outbox.event_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(255))
    source_revision: Mapped[int] = mapped_column(BigInteger)
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    core_event_sequence: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT")
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
