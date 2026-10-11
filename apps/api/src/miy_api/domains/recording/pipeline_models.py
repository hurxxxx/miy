"""Source-owned immutable command identity with durable execution claim."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, FetchedValue, ForeignKey
from sqlalchemy import Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class RecordingStageCommand(Base):
    __tablename__ = "recording_stage_commands"
    __table_args__ = (
        UniqueConstraint("attempt_id", "stage", "retry_ordinal", name="uq_recording_stage_retry"),
        CheckConstraint(
            "stage IN ('transcribe','analyze_transcript','verify_transcript_summary','persist_result')",
            name="ck_recording_stage_name",
        ),
        CheckConstraint("retry_ordinal BETWEEN 0 AND 3", name="ck_recording_stage_retry"),
        CheckConstraint(
            "result_version IS NULL OR result_version >= 1", name="ck_recording_stage_version"
        ),
        CheckConstraint(
            "state IN ('pending','running','succeeded','retry_scheduled','failed')",
            name="ck_recording_stage_state",
        ),
        CheckConstraint(
            "(state='pending' AND execution_token IS NULL AND started_at IS NULL AND finished_at IS NULL) OR (state='running' AND execution_token IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NULL) OR (state IN ('succeeded','retry_scheduled','failed') AND execution_token IS NOT NULL AND started_at IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_recording_stage_execution",
        ),
        CheckConstraint("payload_digest ~ '^[a-f0-9]{64}$'", name="ck_recording_stage_digest"),
        CheckConstraint(
            "producer_generation >= 1 AND producer_role_oid > 0", name="ck_recording_stage_producer"
        ),
        CheckConstraint(
            "producer_artifact ~ '^sha256:[a-f0-9]{64}$'", name="ck_recording_stage_artifact"
        ),
        CheckConstraint(
            "stage != 'persist_result' OR task_id=attempt_id", name="ck_recording_stage_final_id"
        ),
        CheckConstraint(
            "transcript_digest IS NULL OR transcript_digest ~ '^[a-f0-9]{64}$'",
            name="ck_recording_stage_transcript_digest",
        ),
        CheckConstraint(
            "summary_digest IS NULL OR summary_digest ~ '^[a-f0-9]{64}$'",
            name="ck_recording_stage_summary_digest",
        ),
        CheckConstraint(
            "verifier_digest IS NULL OR verifier_digest ~ '^[a-f0-9]{64}$'",
            name="ck_recording_stage_verifier_digest",
        ),
        Index("ix_recording_stage_pending", "state", "due_at", "command_id"),
    )
    writer_scope: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("official_runtime_ownership.scope"),
        CheckConstraint("writer_scope = 'official.suite'", name="ck_recording_stage_scope"),
        server_default="official.suite",
    )
    command_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    retry_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    predecessor_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("recording_stage_commands.command_id", ondelete="RESTRICT")
    )
    owner_id: Mapped[str] = mapped_column(String(36))
    storage_key: Mapped[str] = mapped_column(String(512))
    result_version: Mapped[int | None] = mapped_column(Integer)
    transcript_digest: Mapped[str | None] = mapped_column(String(64))
    summary_digest: Mapped[str | None] = mapped_column(String(64))
    verifier_digest: Mapped[str | None] = mapped_column(String(64))
    payload_digest: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    producer_generation: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    producer_artifact: Mapped[str] = mapped_column(String(71), server_default=FetchedValue())
    producer_role_oid: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    producer_role_name: Mapped[str] = mapped_column(String(63), server_default=FetchedValue())
    state: Mapped[str] = mapped_column(String(24), default="pending")
    execution_token: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
