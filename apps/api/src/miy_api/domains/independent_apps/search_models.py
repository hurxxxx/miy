"""Core-owned search resource binding. Apps never write these backend targets."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from miy_api.core.db import Base
from miy_api.domains.auth.models import utcnow_naive


class AppSearchBindingRecord(Base):
    __tablename__ = "independent_app_search_bindings"
    __table_args__ = (
        UniqueConstraint("opensearch_index", name="uq_app_search_keyword_index"),
        UniqueConstraint("qdrant_collection", name="uq_app_search_vector_collection"),
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("independent_app_installations.id"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    search_spec_sha256: Mapped[str] = mapped_column(String(64))
    candidate_release_id: Mapped[str] = mapped_column(ForeignKey("independent_app_releases.id"))
    definition_digest: Mapped[str] = mapped_column(String(71))
    opensearch_index: Mapped[str] = mapped_column(String(120))
    opensearch_uuid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qdrant_collection: Mapped[str] = mapped_column(String(120))
    embedding_profile: Mapped[str] = mapped_column(String(100))
    embedding_config_sha256: Mapped[str] = mapped_column(String(64))
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    # unknown retains exact resources and original operation; never auto adopt/delete.
    state: Mapped[str] = mapped_column(String(20), default="preparing")
    # Only verified cleanup may resume after a deletion/lost acknowledgement.
    cleanup_phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
