from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class AppDefinitionRecord(Base):
    __tablename__ = "independent_app_definitions"

    app_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(71))
    source_revision: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class AppReleaseRecord(Base):
    __tablename__ = "independent_app_releases"
    __table_args__ = (
        UniqueConstraint("app_id", "artifact", name="uq_independent_app_release_artifact"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_definitions.app_id"), index=True
    )
    definition_digest: Mapped[str] = mapped_column(String(71))
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_revision: Mapped[str] = mapped_column(String(40))
    artifact: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    verification_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppInstallationRecord(Base):
    __tablename__ = "independent_app_installations"
    __table_args__ = (
        UniqueConstraint("app_id", "environment", "origin", name="uq_independent_app_installation"),
        UniqueConstraint("origin", name="uq_independent_app_origin"),
        Index(
            "uq_independent_app_production",
            "app_id",
            unique=True,
            postgresql_where=text("environment = 'production'"),
            sqlite_where=text("environment = 'production'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_definitions.app_id"), index=True
    )
    environment: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    audience: Mapped[str] = mapped_column(String(16), default="selected")
    user_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    group_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    granted_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    release_id: Mapped[str | None] = mapped_column(
        ForeignKey("independent_app_releases.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), default="configured")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    runtime_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AppLaunchCode(Base):
    __tablename__ = "independent_app_launch_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), index=True
    )
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    code_challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppSession(Base):
    __tablename__ = "independent_app_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), index=True
    )
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    permissions: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
