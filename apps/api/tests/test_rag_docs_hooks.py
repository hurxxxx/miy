from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob
from miy_api.domains.retrieval import official_projection_ingress as ingress


def _job_rows() -> list[RagSyncJob]:
    with get_session_factory()() as db:
        return list(
            db.scalars(
                select(RagSyncJob).order_by(RagSyncJob.created_at.asc(), RagSyncJob.id.asc())
            )
        )


def _visibility_job_rows() -> list[RagVisibilityRecomputeJob]:
    with get_session_factory()() as db:
        return list(
            db.scalars(
                select(RagVisibilityRecomputeJob).order_by(
                    RagVisibilityRecomputeJob.created_at.asc(),
                    RagVisibilityRecomputeJob.id.asc(),
                )
            )
        )


def _enable_docs_rag(monkeypatch) -> None:
    monkeypatch.setattr(
        ingress,
        "get_settings",
        lambda: SimpleNamespace(rag_enabled=True),
    )
