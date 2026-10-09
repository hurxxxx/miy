"""Core-owned immutable checked attempts; no official Source or native activation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base


class WhiteboardCheckedAttempt(Base):
    __tablename__ = "whiteboard_checked_attempts"
    __table_args__ = (
        CheckConstraint("base_revision >= 0", name="ck_wb_checked_base_revision"),
        CheckConstraint("cohort_cutoff >= 1", name="ck_wb_checked_cutoff"),
        CheckConstraint("contributor_count BETWEEN 1 AND 128", name="ck_wb_checked_contributors"),
        CheckConstraint(
            "state IN ('sealed','committed','cancelled_not_committed')", name="ck_wb_checked_state"
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    seal_role_oid: Mapped[int] = mapped_column(BigInteger)
    seal_role_name: Mapped[str] = mapped_column(String(63))
    source_role_oid: Mapped[int] = mapped_column(BigInteger)
    source_role_name: Mapped[str] = mapped_column(String(63))
    service_generation: Mapped[int] = mapped_column(Integer)
    service_artifact: Mapped[str] = mapped_column(String(71))
    composition_epoch: Mapped[str] = mapped_column(String(64))
    whiteboard_id: Mapped[str] = mapped_column(String(36))
    collab_id: Mapped[str] = mapped_column(String(36))
    room_key: Mapped[str] = mapped_column(String(128))
    content_incarnation_id: Mapped[UUID] = mapped_column(Uuid)
    base_revision: Mapped[int] = mapped_column(BigInteger)
    yjs_state: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    snapshot_scene: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    cohort_cutoff: Mapped[int] = mapped_column(BigInteger)
    contributor_count: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32))
    result_incarnation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    result_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sealed_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WhiteboardCheckedContributor(Base):
    __tablename__ = "whiteboard_checked_contributors"
    __table_args__ = (CheckConstraint("ordinal BETWEEN 1 AND 128", name="ck_wb_checked_ordinal"),)

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("whiteboard_checked_attempts.attempt_id"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    delegated_token_digest: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(String(36))
    source_session_id: Mapped[str] = mapped_column(String(36))
    installation_id: Mapped[str] = mapped_column(String(36))
    installation_generation: Mapped[int] = mapped_column(Integer)
    binding_id: Mapped[str] = mapped_column(String(36))
    release_id: Mapped[str] = mapped_column(String(36))
    verification_id: Mapped[str] = mapped_column(String(100))
    execution_artifact: Mapped[str] = mapped_column(String(500))
    origin: Mapped[str] = mapped_column(String(300))
    environment: Mapped[str] = mapped_column(String(16))
    database_name: Mapped[str] = mapped_column(String(63))
    database_oid: Mapped[int] = mapped_column(BigInteger)
    server_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    server_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
