"""App development work, separate from product spaces and installed releases."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class AppWorkspaceRecord(Base):
    __tablename__ = "independent_app_workspaces"
    __table_args__ = (UniqueConstraint("profile_id", "slot", name="uq_app_workspace_slot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(ForeignKey("independent_app_definitions.app_id"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    parent_installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id")
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), unique=True
    )
    profile_id: Mapped[str] = mapped_column(String(64))
    profile_digest: Mapped[str] = mapped_column(String(64))
    creation_digest: Mapped[str] = mapped_column(String(64))
    slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="ready")
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    integration_revision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class AppWorkspaceCandidate(Base):
    __tablename__ = "independent_app_workspace_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_workspaces.id"), index=True
    )
    app_id: Mapped[str] = mapped_column(ForeignKey("independent_app_definitions.app_id"))
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(71))
    source_revision: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
