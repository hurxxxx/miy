"""Hash-only, source-session-bound registration authorizations; no work queue."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class AppRegistrationAuthorization(Base):
    __tablename__ = "independent_app_registration_authorizations"
    __table_args__ = tuple(
        Index(f"ix_app_registration_{column}", column)
        for column in ("operation_id", "actor_user_id", "source_session_id")
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    operation_id: Mapped[str] = mapped_column(String(36))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    audience: Mapped[str] = mapped_column(String(500))
    policy: Mapped[dict] = mapped_column(JSON)
    code_challenge: Mapped[str] = mapped_column(String(43))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_expires_at: Mapped[datetime] = mapped_column(DateTime)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    payload_digest: Mapped[str | None] = mapped_column(String(71))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
