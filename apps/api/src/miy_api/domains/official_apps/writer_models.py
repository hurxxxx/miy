"""Core-owned writer control state; no official service is activated by these rows."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class RuntimeOwnership(Base):
    __tablename__ = "official_runtime_ownership"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="ck_official_writer_generation"),
        CheckConstraint(
            "active_owner IN ('legacy', 'official-suite')", name="ck_official_writer_owner"
        ),
        CheckConstraint("state IN ('active', 'draining')", name="ck_official_writer_state"),
    )

    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    active_owner: Mapped[str] = mapped_column(String(32))
    generation: Mapped[int] = mapped_column(Integer)
    artifact: Mapped[str | None] = mapped_column(String(71), nullable=True)
    state: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class RuntimeTransition(Base):
    __tablename__ = "official_runtime_transitions"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(ForeignKey("official_runtime_ownership.scope"), index=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    previous: Mapped[dict] = mapped_column(JSON)
    resulting: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
