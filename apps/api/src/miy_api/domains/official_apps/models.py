from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class OfficialAppBinding(Base):
    """Explicit core approval, immutable for one installation generation."""

    __tablename__ = "official_app_bindings"
    __table_args__ = (
        UniqueConstraint("installation_id", "generation", name="uq_official_binding_generation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(ForeignKey("independent_app_installations.id"))
    generation: Mapped[int] = mapped_column(Integer)
    release_id: Mapped[str] = mapped_column(ForeignKey("independent_app_releases.id"))
    verification_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_build_verifications.id")
    )
    artifact: Mapped[str] = mapped_column(String(500))
    origin: Mapped[str] = mapped_column(String(300))
    environment: Mapped[str] = mapped_column(String(16))
    logical_app_ids: Mapped[list[str]] = mapped_column(JSON)
    approved_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
