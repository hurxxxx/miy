"""Durable local delivery state; native Codex tasks remain owned by Workbench."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
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


class AppDeliveryDelegation(Base):
    __tablename__ = "independent_app_delivery_delegations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    app_id: Mapped[str] = mapped_column(ForeignKey("independent_app_definitions.app_id"))
    installation_id: Mapped[str] = mapped_column(ForeignKey("independent_app_installations.id"))
    environment: Mapped[str] = mapped_column(String(16))
    actions: Mapped[list[str]] = mapped_column(JSON)
    definition_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class AppBuildJob(Base):
    __tablename__ = "independent_app_build_jobs"
    __table_args__ = (
        UniqueConstraint("executor_id", "active_slot", name="uq_independent_app_heavy_build"),
        CheckConstraint(
            "active_slot IS NULL OR active_slot = 1", name="ck_independent_app_build_slot"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    app_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_definitions.app_id"), index=True
    )
    source_revision: Mapped[str] = mapped_column(String(40))
    definition_digest: Mapped[str] = mapped_column(String(71))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("auth_sessions.id"), nullable=True
    )
    delegation_id: Mapped[str | None] = mapped_column(
        ForeignKey("independent_app_delivery_delegations.id"), nullable=True
    )
    installation_id: Mapped[str | None] = mapped_column(
        ForeignKey("independent_app_installations.id"), nullable=True
    )
    executor_id: Mapped[str] = mapped_column(String(80), default="local")
    state: Mapped[str] = mapped_column(String(16), default="queued")
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    release_id: Mapped[str | None] = mapped_column(
        ForeignKey("independent_app_releases.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)


class AppBuildVerification(Base):
    __tablename__ = "independent_app_build_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    build_job_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_build_jobs.id"), unique=True
    )
    app_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_definitions.app_id"), index=True
    )
    source_revision: Mapped[str] = mapped_column(String(40))
    definition_digest: Mapped[str] = mapped_column(String(71))
    source_archive_sha256: Mapped[str] = mapped_column(String(64))
    artifact_digest: Mapped[str] = mapped_column(String(71))
    builder_profile_digest: Mapped[str] = mapped_column(String(71))
    target_environment: Mapped[str] = mapped_column(String(16))
    checks: Mapped[dict[str, int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AppRuntimeSlot(Base):
    __tablename__ = "independent_app_runtime_slots"
    __table_args__ = (
        UniqueConstraint("executor_id", "slot", name="uq_independent_app_preview_slot"),
        CheckConstraint("slot >= 0 AND slot < 4", name="ck_independent_app_preview_slot"),
    )

    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), primary_key=True
    )
    executor_id: Mapped[str] = mapped_column(String(80), default="local")
    slot: Mapped[int] = mapped_column(Integer)


class AppDeploymentRequest(Base):
    __tablename__ = "independent_app_deployment_requests"
    __table_args__ = (
        Index(
            "uq_independent_app_pending_deployment",
            "installation_id",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running', 'unknown', 'cleanup')"),
            sqlite_where=text("state IN ('queued', 'running', 'unknown', 'cleanup')"),
        ),
        UniqueConstraint("executor_id", "active_slot", name="uq_independent_app_active_deploy"),
        CheckConstraint(
            "active_slot IS NULL OR active_slot = 1", name="ck_independent_app_deploy_slot"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source_session_id: Mapped[str] = mapped_column(ForeignKey("auth_sessions.id"))
    delegation_id: Mapped[str | None] = mapped_column(
        ForeignKey("independent_app_delivery_delegations.id"), nullable=True
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), index=True
    )
    release_id: Mapped[str] = mapped_column(ForeignKey("independent_app_releases.id"))
    action: Mapped[str] = mapped_column(String(16))
    request_hash: Mapped[str] = mapped_column(String(64))
    expected_generation: Mapped[int] = mapped_column(Integer)
    expected_release_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_release_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_runtime_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    executor_id: Mapped[str] = mapped_column(String(80), default="local")
    state: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    observed_image_id: Mapped[str | None] = mapped_column(String(71), nullable=True)
    runtime_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
