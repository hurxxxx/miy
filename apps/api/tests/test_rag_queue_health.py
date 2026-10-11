from __future__ import annotations


from sqlalchemy import create_engine

from miy_api.core.db import Base
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RagSyncJob.__table__,
            RagVisibilityRecomputeJob.__table__,
        ],
    )
    return engine
