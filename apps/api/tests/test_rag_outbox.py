from __future__ import annotations


import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.rag.contracts import (
    RagSyncOperation,
)
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import (
    ProjectionEventRef,
    record_projection_event,
)
import miy_api.domains.rag.outbox as rag_outbox
from miy_api.domains.rag.outbox import (
    enqueue_rag_sync_job,
)
from miy_api.domains.rag.source_adapter_registry import (
    RagResourceAdapter,
    RagVisibilityScopeAdapter,
    register_rag_resource_adapter,
    register_rag_visibility_scope_adapter,
    reset_rag_source_adapters,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RagSyncJob.__table__,
            RagVisibilityRecomputeJob.__table__,
        ],
    )
    session = Session(engine)
    session.commit()
    return session


def _versioned_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RetrievalPartition.__table__,
            RetrievalProjectionHead.__table__,
            RetrievalProjectionEvent.__table__,
            RagSyncJob.__table__,
        ],
    )
    session = Session(engine)
    session.add(
        RetrievalPartition(
            id="11111111-1111-1111-1111-111111111111",
            source_namespace="docs",
            candidate_scope_kind="company",
            state="active",
            metadata_version=1,
            is_default_ingest=True,
        )
    )
    session.commit()
    return session


def _record_doc_event(
    session: Session,
    *,
    resource_id: str,
    desired_state: str = "active",
    content_checksum: str | None = None,
) -> ProjectionEventRef:
    return record_projection_event(
        session,
        resource_type="doc",
        resource_id=resource_id,
        retrieval_partition_id="11111111-1111-1111-1111-111111111111",
        change_kind="delete" if desired_state == "deleted" else "content",
        desired_state=desired_state,
        content_checksum=content_checksum,
    )


def _stub_celery(monkeypatch, published: list[tuple[str, list[str], str]]) -> None:
    class _FakeSignature:
        def __init__(self, task_name: str, args: list[str]) -> None:
            self.task_name = task_name
            self.args = args

        def apply_async(self, *, queue: str, retry: bool) -> None:
            assert retry is False
            published.append((self.task_name, self.args, queue))

    class _FakeCeleryClient:
        def signature(self, task_name: str, args: list[str], immutable: bool):
            assert immutable is True
            return _FakeSignature(task_name, args)

    monkeypatch.setattr(rag_outbox, "get_celery_client", lambda: _FakeCeleryClient())


@pytest.fixture(autouse=True)
def _registered_rag_outbox_adapters():
    reset_rag_source_adapters()
    register_rag_resource_adapter(
        RagResourceAdapter(
            resource_type="doc",
            app_id="tests",
            load_projection=lambda db, resource_id, rag_service: None,
        )
    )
    for scope_type in ("meeting", "pms_meeting"):
        register_rag_visibility_scope_adapter(
            RagVisibilityScopeAdapter(
                scope_type=scope_type,
                resource_type="doc",
                resource_ids=lambda db, job: [],
            )
        )
    try:
        yield
    finally:
        reset_rag_source_adapters()


def test_enqueue_rag_sync_job_rejects_same_version_pending_mismatch() -> None:
    session = _versioned_session()
    try:
        with session.begin():
            event = _record_doc_event(
                session,
                resource_id="mismatched-pending-doc",
                content_checksum="content-v1",
            )
            job = enqueue_rag_sync_job(
                session,
                resource_type="doc",
                resource_id="mismatched-pending-doc",
                content_checksum="content-v1",
                projection_event=event,
            )
            job.content_checksum = "corrupted"
            session.flush()
            with pytest.raises(ValueError, match="same-version projection mismatch"):
                enqueue_rag_sync_job(
                    session,
                    resource_type="doc",
                    resource_id="mismatched-pending-doc",
                    content_checksum="content-v1",
                    projection_event=event,
                )
    finally:
        session.close()


def test_enqueue_rag_sync_job_publishes_only_after_commit(monkeypatch) -> None:
    published: list[tuple[str, list[str], str]] = []

    class _FakeSignature:
        def __init__(self, task_name: str, args: list[str]) -> None:
            self.task_name = task_name
            self.args = args

        def apply_async(self, *, queue: str, retry: bool) -> None:
            assert retry is False
            published.append((self.task_name, self.args, queue))

    class _FakeCeleryClient:
        def signature(self, task_name: str, args: list[str], immutable: bool):
            assert immutable is True
            return _FakeSignature(task_name, args)

    monkeypatch.setattr(rag_outbox, "get_celery_client", lambda: _FakeCeleryClient())

    session = _session()
    try:
        with session.begin():
            job = enqueue_rag_sync_job(
                session,
                resource_type="doc",
                resource_id="doc-publish",
            )
            assert published == []

        assert published == [("rag.sync_resource", [job.id], "rag_sync_realtime")]
    finally:
        session.close()


def test_enqueue_rag_sync_job_preserves_pending_delete_over_later_upsert() -> None:
    session = _session()
    try:
        with session.begin():
            first = enqueue_rag_sync_job(
                session,
                resource_type="doc",
                resource_id="doc-5",
                operation=RagSyncOperation.DELETE,
            )
            second = enqueue_rag_sync_job(
                session,
                resource_type="doc",
                resource_id="doc-5",
                operation=RagSyncOperation.UPSERT,
                content_checksum="content-v3",
            )

        rows = session.scalars(
            select(RagSyncJob).where(
                RagSyncJob.resource_type == "doc",
                RagSyncJob.resource_id == "doc-5",
            )
        ).all()
        assert len(rows) == 1
        assert second.id == first.id
        stored = rows[0]
        assert stored.operation == "delete"
        assert stored.content_checksum == "content-v3"
    finally:
        session.close()
