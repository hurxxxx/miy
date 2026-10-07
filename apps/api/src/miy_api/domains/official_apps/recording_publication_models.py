"""Core owns transport observation, never Recording business execution."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, FetchedValue, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class CoreRecordingPublication(Base):
    __tablename__ = "core_recording_publications"
    __table_args__ = (
        CheckConstraint(
            "queue='miy.official.meeting_transcribe' AND profile='official'",
            name="ck_recording_publication_route",
        ),
        CheckConstraint(
            "state IN ('pending','publishing','acknowledged','unknown','consumed')",
            name="ck_recording_publication_state",
        ),
        CheckConstraint(
            "payload_digest ~ '^[a-f0-9]{64}$'", name="ck_recording_publication_digest"
        ),
        CheckConstraint("issuer_role_oid > 0", name="ck_recording_publication_issuer"),
    )
    publication_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    command_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("recording_stage_commands.command_id", ondelete="RESTRICT"),
        unique=True,
    )
    task_id: Mapped[str] = mapped_column(Uuid(as_uuid=False))
    payload_digest: Mapped[str] = mapped_column(String(64))
    queue: Mapped[str] = mapped_column(String(80))
    profile: Mapped[str] = mapped_column(String(16))
    issuer_role_oid: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())
    issuer_role_name: Mapped[str] = mapped_column(String(63), server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    publication_token: Mapped[str | None] = mapped_column(Uuid(as_uuid=False))
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime)
