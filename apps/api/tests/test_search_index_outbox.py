from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import (
    record_projection_event,
)
from miy_api.domains.search import outbox as search_outbox
from miy_api.domains.search.indexing import process_search_index_job
from miy_api.domains.search.entity_adapter_registry import (
    SearchEntityAdapter,
    register_search_entity_adapter,
    reset_search_entity_adapters,
)
from miy_api.domains.docs.app_catalog import DOCS_APP
from miy_api.domains.search.entity_registry import reset_search_entity_descriptors
from miy_api.domains.search.models import SearchIndexJob
from miy_api.domains.search.outbox import enqueue_search_index_job
from miy_api.domains.search.projection_registry import reset_search_projection_adapters


_PROJECTION_PARTITION_ID = "722c2043-fc6f-4446-9811-dc35c263d445"


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            SearchIndexJob.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    session.commit()
    return session


def _projection_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            RetrievalPartition.__table__,
            RetrievalProjectionHead.__table__,
            RetrievalProjectionEvent.__table__,
            SearchIndexJob.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    session.add_all(
        [
            RetrievalPartition(
                id=_PROJECTION_PARTITION_ID,
                source_namespace="search-fence-test",
                candidate_scope_kind="company",
                is_default_ingest=False,
            ),
        ]
    )
    session.commit()
    return session


def _fence_docs_job(session: Session, job: SearchIndexJob) -> None:
    """Ordinary indexing tests use actual persisted events, not legacy repair."""
    updated_at = job.updated_at
    event = record_projection_event(
        session,
        resource_type="docs_native_doc",
        resource_id=job.entity_id,
        retrieval_partition_id=_PROJECTION_PARTITION_ID,
        change_kind="delete" if job.operation == "delete" else "content",
        desired_state="deleted" if job.operation == "delete" else "active",
    )
    job.resource_type = event.resource_type
    job.retrieval_partition_id = event.retrieval_partition_id
    job.projection_event_sequence = event.event_sequence
    job.projection_version = event.projection_version
    job.desired_state = event.desired_state
    session.flush()
    job.updated_at = updated_at
    session.commit()


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

    monkeypatch.setattr(search_outbox, "get_celery_client", lambda: _FakeCeleryClient())


def _reset_search_registries() -> None:
    reset_search_entity_adapters()
    reset_search_entity_descriptors()
    reset_search_projection_adapters()


def _search_acl_fields() -> dict[str, object]:
    return {
        "owner_user_id": None,
        "visibility": None,
        "team_ids": [],
        "participant_user_ids": [],
        "shared_user_ids": [],
        "shared_group_ids": [],
        "ownership_kind": "personal",
        "granted_user_ids": [],
        "target_keys": [],
    }


def _register_extension_search_entity(entity_type: str = "plugin_external_record") -> None:
    register_search_entity_adapter(
        SearchEntityAdapter(
            owner_app=DOCS_APP,
            entity_type=entity_type,
            resource_type="plugin_external_record",
            label="Plugin External Record",
            label_key="ai.search.entityPluginExternalRecord",
            company_loader=lambda db,: [],
            document_loader=lambda db, *, entity_type, entity_id: {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title": "Plugin External Record",
            },
        )
    )


def test_versioned_enqueue_higher_version_wins_over_late_delete(
    monkeypatch,
) -> None:
    published: list[tuple[str, list[str], str]] = []
    _stub_celery(monkeypatch, published)
    session = _projection_session()
    try:
        with session.begin():
            departed = record_projection_event(
                session,
                resource_type="docs_native_doc",
                resource_id="doc-versioned",
                retrieval_partition_id=_PROJECTION_PARTITION_ID,
                change_kind="delete",
                desired_state="deleted",
            )
            job = enqueue_search_index_job(
                session,
                entity_type="doc",
                entity_id="doc-versioned",
                operation="delete",
                projection_event=departed,
            )
            moved = record_projection_event(
                session,
                resource_type="docs_native_doc",
                resource_id="doc-versioned",
                retrieval_partition_id=_PROJECTION_PARTITION_ID,
                change_kind="content",
                desired_state="active",
            )
            merged = enqueue_search_index_job(
                session,
                entity_type="doc",
                entity_id="doc-versioned",
                operation="upsert",
                projection_event=moved,
            )
            ignored = enqueue_search_index_job(
                session,
                entity_type="doc",
                entity_id="doc-versioned",
                operation="delete",
                projection_event=departed,
            )

        assert merged.id == job.id == ignored.id
        stored = session.get(SearchIndexJob, job.id)
        assert stored is not None
        assert not hasattr(stored, "workspace_id")
        assert stored.resource_type == "docs_native_doc"
        assert stored.projection_event_sequence == moved.event_sequence
        assert stored.projection_version == 2
        assert stored.retrieval_partition_id == _PROJECTION_PARTITION_ID
        assert stored.desired_state == "active"
        assert stored.operation == "upsert"
        assert published == [("search.index_resource", [job.id], "search_index_realtime")]
    finally:
        session.close()

    # The four-hook PostgreSQL integration verifies the positive path with
    # actual source rows, append-only intent and Core receipt in one transaction.


def test_enqueue_search_index_job_does_not_publish_on_rollback(monkeypatch) -> None:
    published: list[tuple[str, list[str], str]] = []
    _stub_celery(monkeypatch, published)
    session = _session()
    try:
        try:
            with session.begin():
                enqueue_search_index_job(
                    session,
                    entity_type="meeting",
                    entity_id="meeting-1",
                    operation="upsert",
                )
                raise RuntimeError("rollback")
        except RuntimeError:
            pass

        assert published == []
    finally:
        session.close()


def test_process_search_index_job_rechecks_policy_after_claim_before_client_resolution(
    monkeypatch,
) -> None:
    session = _projection_session()
    published: list[tuple[str, list[str], str]] = []
    _stub_celery(monkeypatch, published)
    try:
        with session.begin():
            job = enqueue_search_index_job(
                session,
                entity_type="doc",
                entity_id="doc-disabled",
                operation="upsert",
                trace_context={},
            )

        _fence_docs_job(session, job)
        result = process_search_index_job(
            session,
            job.id,
            client_factory=lambda *_args: (_ for _ in ()).throw(
                AssertionError("disabled job resolved a search provider")
            ),
            execution_allowed=lambda *_args: False,
        )

        stored = session.get(SearchIndexJob, job.id)
        assert result == "app-disabled"
        assert stored is not None
        assert stored.status == "pending"
        assert stored.attempts == 0
        assert stored.last_error == "app_disabled"
    finally:
        session.close()


def test_versioned_search_job_stale_head_skips_backend_mutation(monkeypatch) -> None:
    session = _projection_session()
    published: list[tuple[str, list[str], str]] = []
    _stub_celery(monkeypatch, published)

    class _FakeClient:
        def upsert_document(self, document: dict) -> None:
            del document
            raise AssertionError("stale versioned job must not upsert")

        def delete_document(self, *, entity_type: str, entity_id: str) -> None:
            del entity_type, entity_id
            raise AssertionError("stale versioned job must not delete")

    try:
        with session.begin():
            first = record_projection_event(
                session,
                resource_type="docs_native_doc",
                resource_id="doc-stale-head",
                retrieval_partition_id=_PROJECTION_PARTITION_ID,
                change_kind="delete",
                desired_state="deleted",
            )
            job = enqueue_search_index_job(
                session,
                entity_type="doc",
                entity_id="doc-stale-head",
                operation="delete",
                projection_event=first,
            )
            record_projection_event(
                session,
                resource_type="docs_native_doc",
                resource_id="doc-stale-head",
                retrieval_partition_id=_PROJECTION_PARTITION_ID,
                change_kind="content",
                desired_state="active",
            )

        result = process_search_index_job(session, job.id, client=_FakeClient())
        stored = session.get(SearchIndexJob, job.id)
        assert result == "superseded"
        assert stored is not None
        assert stored.status == "cancelled"
        assert stored.last_error == "superseded_by_projection_head:before_mutation"
    finally:
        session.close()


def test_process_search_index_job_reclaims_stale_processing_delivery() -> None:
    session = _projection_session()
    calls: list[tuple[str, object]] = []

    class _FakeClient:
        def upsert_document(self, document: dict) -> None:
            calls.append(("upsert", document))

        def delete_document(self, *, entity_type: str, entity_id: str) -> None:
            calls.append(("delete", (entity_type, entity_id)))

    try:
        with session.begin():
            session.add(
                SearchIndexJob(
                    id="job-processing-stale",
                    entity_type="doc",
                    entity_id="doc-processing-stale",
                    operation="delete",
                    trace_context={},
                    status="processing",
                    attempts=1,
                    updated_at=(datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)),
                )
            )

        _fence_docs_job(session, session.get(SearchIndexJob, "job-processing-stale"))
        result = process_search_index_job(
            session,
            "job-processing-stale",
            client=_FakeClient(),
        )

        stored = session.get(SearchIndexJob, "job-processing-stale")
        assert result == "deleted"
        assert stored is not None
        assert stored.status == "succeeded"
        assert stored.attempts == 2
        assert calls == [("delete", ("doc", "doc-processing-stale"))]
    finally:
        session.close()
