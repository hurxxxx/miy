"""Immutable Core repair receipts; source-only principals receive no grants."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class DocsLegacyProjectionRepair(Base):
    __tablename__ = "docs_legacy_projection_repairs"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="ck_docs_repair_version"),
        CheckConstraint("target_count BETWEEN 0 AND 100", name="ck_docs_repair_count"),
        CheckConstraint(
            "(CASE WHEN visibility_job_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN rag_job_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN search_job_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_docs_repair_origin",
        ),
        CheckConstraint("octet_length(input_payload) <= 131072", name="ck_docs_repair_input_size"),
        CheckConstraint(
            "octet_length(targets_payload) <= 131072", name="ck_docs_repair_targets_size"
        ),
        CheckConstraint("input_digest ~ '^[a-f0-9]{64}$'", name="ck_docs_repair_digest"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visibility_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("rag_visibility_recompute_jobs.id", ondelete="RESTRICT"), unique=True
    )
    rag_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("rag_sync_jobs.id", ondelete="RESTRICT"), unique=True
    )
    search_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_index_jobs.id", ondelete="RESTRICT"), unique=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_payload: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    targets_payload: Mapped[str] = mapped_column(Text, nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rag_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, nullable=False)


class DocsLegacyProjectionRepairTarget(Base):
    __tablename__ = "docs_legacy_projection_repair_targets"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('upsert','visibility_update','delete')", name="ck_docs_repair_target_op"
        ),
    )
    receipt_id: Mapped[str] = mapped_column(
        ForeignKey("docs_legacy_projection_repairs.id", ondelete="RESTRICT"), primary_key=True
    )
    resource_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    core_event_sequence: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("retrieval_projection_events.event_sequence", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    search_job_id: Mapped[str] = mapped_column(
        ForeignKey("search_index_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    rag_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("rag_sync_jobs.id", ondelete="RESTRICT")
    )
