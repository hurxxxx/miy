"""Fixed Source extraction history; canonical artifacts remain on the File."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base


class FileExtractionRequest(Base):
    __tablename__ = "file_extraction_requests"
    __table_args__ = (
        UniqueConstraint("result_id", name="uq_file_extraction_result"),
        UniqueConstraint("event_id", name="uq_file_extraction_event"),
        UniqueConstraint(
            "file_id", "input_fingerprint", "parser_policy", name="uq_file_extraction_input"
        ),
        CheckConstraint("source_scope='official.suite'", name="ck_file_extraction_scope"),
        CheckConstraint(
            "state IN ('prepared','claimed','input_bound','ready','unsupported','failed')",
            name="ck_file_extraction_state",
        ),
        CheckConstraint("octet_length(request_payload)<=8192", name="ck_file_extraction_payload"),
        CheckConstraint(
            "request_digest ~ '^[a-f0-9]{64}$' AND input_fingerprint ~ '^[a-f0-9]{64}$'",
            name="ck_file_extraction_digests",
        ),
        CheckConstraint(
            "input_sha256 IS NULL OR input_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_file_extraction_raw_sha",
        ),
        CheckConstraint(
            "result_digest IS NULL OR result_digest ~ '^[a-f0-9]{64}$'",
            name="ck_file_extraction_result_sha",
        ),
        CheckConstraint(
            "input_byte_count IS NULL OR input_byte_count BETWEEN 0 AND 10485760",
            name="ck_file_extraction_bytes",
        ),
        CheckConstraint(
            "hold_reason IS NULL OR hold_reason='ocr_required'", name="ck_file_extraction_hold"
        ),
        CheckConstraint(
            "producer_role_oid>0 AND producer_generation>=1", name="ck_file_extraction_producer"
        ),
    )

    request_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    result_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    event_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    source_scope: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("official_runtime_ownership.scope", name="fk_file_extraction_source_scope"),
        server_default="official.suite",
    )
    # Historical identifiers deliberately have no cascading business/user FK.
    file_id: Mapped[str] = mapped_column(String(36))
    actor_user_id: Mapped[str] = mapped_column(String(36))
    execution_ref: Mapped[str] = mapped_column(String(80))
    parser_policy: Mapped[str] = mapped_column(String(80))
    request_payload: Mapped[str] = mapped_column(Text)
    request_digest: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    producer_role_oid: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    producer_role_name: Mapped[str] = mapped_column(String(63), server_default=FetchedValue())
    producer_generation: Mapped[int] = mapped_column(Integer, server_default=FetchedValue())
    producer_artifact: Mapped[str | None] = mapped_column(String(71), server_default=FetchedValue())
    state: Mapped[str] = mapped_column(String(16), default="prepared")
    claim_token: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    input_byte_count: Mapped[int | None] = mapped_column(Integer)
    hold_reason: Mapped[str | None] = mapped_column(String(32))
    result_digest: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=FetchedValue())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    input_bound_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
