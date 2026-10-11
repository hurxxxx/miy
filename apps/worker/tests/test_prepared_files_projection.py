from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import rag_projection, rag_sync as files_rag_sync
from miy_api.domains.files.core_projection import (
    FileArtifactInvalid,
    prepared_core_file_projection,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.rag.contracts import RagJobStatus
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import record_projection_event
from miy_api.domains.search import outbox as search_outbox
from miy_api.domains.search.models import SearchIndexJob
from miy_worker.tasks import rag_sync


CHECKSUM = "a" * 64


def trap(*args, **kwargs):
    raise AssertionError("prepared Core Files reached a forbidden effect")


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://")
    models = (
        User,
        RetrievalPartition,
        FileManagerCorpus,
        FileManagerFile,
        FileManagerFileSourceMetadata,
        RetrievalProjectionEvent,
        RetrievalProjectionHead,
        SearchIndexJob,
        RagSyncJob,
    )
    Base.metadata.create_all(engine, tables=[model.__table__ for model in models])
    db = Session(engine)
    partition_id = str(uuid4())
    file = FileManagerFile(
        id="prepared-file-1",
        owner_id="prepared-owner-1",
        filename="synthetic.txt",
        content_type="text/plain",
        size_bytes=64,
        storage_key="synthetic-only/prepared-file-1",
        visibility="company",
        retrieval_partition_id=partition_id,
        extraction_status="ready",
        extraction_content_checksum=CHECKSUM,
        extraction_text="Synthetic extraction used only by this isolated test.",
        extraction_blocks=[
            EvidenceBlock(
                document_id="prepared-file-1",
                block_id="prepared-file-1:body",
                locator_kind="document",
                locator_label="Body",
                section_path="Body",
                block_kind="text",
                text="Synthetic extraction used only by this isolated test.",
            ).to_dict()
        ],
        extraction_metadata={"parser_version": rag_projection.FILES_EXTRACTION_PARSER_VERSION},
    )
    db.add_all(
        [
            User(
                id=file.owner_id,
                login_id=file.owner_id,
                email="prepared-owner@example.test",
                full_name="Synthetic owner",
                password_hash="unused-test-hash",
            ),
            RetrievalPartition(
                id=partition_id,
                source_namespace="files",
                candidate_scope_kind="company",
                is_default_ingest=True,
            ),
            file,
        ]
    )
    db.flush()
    ref = record_projection_event(
        db,
        resource_type="file_manager_file",
        resource_id=file.id,
        retrieval_partition_id=partition_id,
        change_kind="content",
        desired_state="active",
        content_checksum=CHECKSUM,
    )
    job = RagSyncJob(
        id=str(uuid4()),
        scope_kind="company",
        resource_type=ref.resource_type,
        resource_id=ref.resource_id,
        operation="upsert",
        status="processing",
        lane="realtime",
        attempts=1,
        retrieval_partition_id=partition_id,
        projection_event_sequence=ref.event_sequence,
        projection_version=ref.projection_version,
        desired_state=ref.desired_state,
        content_checksum=ref.content_checksum,
    )
    db.add(job)
    db.commit()
    for name in (
        "read_file_content",
        "extract_file_artifact",
        "mark_file_extraction_failed",
        "purge_deleted_file_retrieval_artifact",
        "_store_artifact_if_active",
        "_mark_extraction_unsupported_if_active",
    ):
        monkeypatch.setattr(rag_projection, name, trap)
    monkeypatch.setattr(files_rag_sync, "mark_file_extraction_failed", trap)
    monkeypatch.setattr(files_rag_sync, "purge_deleted_file_retrieval_artifact", trap)
    monkeypatch.setattr(files_rag_sync, "enqueue_file_retrieval_sync", trap)
    monkeypatch.setattr(search_outbox, "get_celery_client", trap)
    monkeypatch.setattr(rag_sync, "_disabled_app_id_for_job", lambda *args: None)
    monkeypatch.setattr(rag_sync, "_record_sync_queue_depth_snapshot", lambda *args, **kwargs: None)
    yield SimpleNamespace(db=db, engine=engine, file=file, ref=ref, job=job)
    db.close()
    engine.dispose()


def forbid_source_dml(world):
    @event.listens_for(world.engine, "before_cursor_execute")
    def reject_source_dml(connection, cursor, statement, parameters, context, executemany):
        lowered = statement.lower().lstrip()
        if lowered.startswith(("update", "insert", "delete", "copy")) and (
            "file_manager_" in lowered or "official_projection_outbox" in lowered
        ):
            raise AssertionError("prepared Core mutated Source data or intent")


@pytest.mark.parametrize("status", ["pending", "failed", "unsupported"])
def test_not_ready_is_held_before_provider_and_never_source_failed(world, monkeypatch, status):
    world.file.extraction_status = status
    world.db.commit()
    forbid_source_dml(world)
    monkeypatch.setattr(rag_sync, "_rag_runtime_for_job", trap)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        result = rag_sync._execute_sync_job(
            world.db,
            task=SimpleNamespace(retry=trap),
            job=world.job,
            span_name="test.prepared.files",
            job_kind="resource_sync",
            rag_enabled=True,
        )
        assert result == "file_artifact_not_ready"
        assert world.job.status == RagJobStatus.FAILED
        assert world.job.last_error == result
        assert world.job.attempts == 0
        assert world.job.next_retry_at is None
        now = datetime.now(UTC).replace(tzinfo=None)
        claimable = world.db.scalar(
            select(RagSyncJob.id).where(
                RagSyncJob.id == world.job.id,
                rag_sync._sync_claimable_clause(now=now, lease_cutoff=now - timedelta(minutes=5)),
            )
        )
        assert claimable is None
    assert world.file.extraction_status == status
    assert world.db.scalar(select(func.count()).select_from(SearchIndexJob)) == 0


@pytest.mark.parametrize("fault", ["invalid_blocks", "wrong_checksum"])
def test_invalid_or_mismatched_ready_is_held_without_provider(world, monkeypatch, fault):
    if fault == "invalid_blocks":
        world.file.extraction_blocks = [{"unexpected": "malformed"}]
        expected = "file_artifact_invalid"
    else:
        world.file.extraction_content_checksum = "b" * 64
        expected = "file_artifact_checksum_mismatch"
    world.db.commit()
    forbid_source_dml(world)
    monkeypatch.setattr(rag_sync, "_rag_runtime_for_job", trap)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        result = rag_sync._execute_sync_job(
            world.db,
            task=SimpleNamespace(retry=trap),
            job=world.job,
            span_name="test.prepared.files",
            job_kind="resource_sync",
            rag_enabled=True,
        )
    assert result == expected
    assert world.job.status == RagJobStatus.FAILED


def test_actual_adapter_reads_ready_and_worker_only_mutates_derived_data(world, monkeypatch):
    calls = []
    service = SimpleNamespace(
        sync_projection=lambda projection, **kwargs: (
            calls.append((projection, kwargs))
            or SimpleNamespace(chunk_count=len(projection.chunks))
        ),
        delete_projection=trap,
    )
    monkeypatch.setattr(
        rag_sync,
        "_rag_runtime_for_job",
        lambda db, job: SimpleNamespace(service=service, collection="synthetic-derived-only"),
    )
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        assert rag_sync._process_sync_job(world.db, world.job) == "succeeded"
    assert len(calls) == 1
    projection, kwargs = calls[0]
    assert projection.resource_id == world.file.id
    assert projection.metadata["content_checksum"] == CHECKSUM
    assert projection.projection_version == world.ref.projection_version
    assert kwargs == {"collection": "synthetic-derived-only"}
    keyword = world.db.scalar(select(SearchIndexJob))
    assert keyword.projection_event_sequence == world.ref.event_sequence
    assert keyword.projection_version == world.ref.projection_version


def test_ready_callback_new_and_merged_keyword_jobs_publish_nothing(world):
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        files_rag_sync.mark_file_projection_prepared(
            world.db, file_id=world.file.id, projection_event=world.ref
        )
        world.db.commit()
    first = world.db.scalar(select(SearchIndexJob))
    keyword_id = first.id
    second_ref = record_projection_event(
        world.db,
        resource_type="file_manager_file",
        resource_id=world.file.id,
        retrieval_partition_id=world.ref.retrieval_partition_id,
        change_kind="visibility",
        desired_state="active",
        content_checksum=CHECKSUM,
    )
    world.db.commit()
    with prepared_core_file_projection(world.db, projection_event=second_ref):
        files_rag_sync.mark_file_projection_prepared(
            world.db, file_id=world.file.id, projection_event=second_ref
        )
        world.db.commit()
    merged = world.db.scalar(select(SearchIndexJob))
    assert merged.id == keyword_id
    assert merged.projection_version == second_ref.projection_version
    assert merged.projection_event_sequence == second_ref.event_sequence
    assert world.db.scalar(select(func.count()).select_from(SearchIndexJob)) == 1


def test_prepared_delete_and_failure_callbacks_never_touch_source(world):
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        files_rag_sync.mark_file_projection_deleted(world.db, file_id=world.file.id)
        for phase in ("extraction", "ocr", "parser", "embedding"):
            files_rag_sync.mark_file_projection_failed(
                world.db, file_id=world.file.id, error="synthetic failure", phase=phase
            )
        world.db.commit()
    assert world.file.extraction_status == "ready"
    assert world.file.extraction_content_checksum == CHECKSUM
    assert world.file.extraction_error_code is None


def test_ready_callback_rejects_unbound_core_event(world):
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        with pytest.raises(RuntimeError) as outcome:
            files_rag_sync.mark_file_projection_prepared(world.db, file_id=world.file.id)
        assert outcome.value.reason == "file_projection_event_required"
    assert world.db.scalar(select(func.count()).select_from(SearchIndexJob)) == 0


@pytest.mark.parametrize("missing", ["deleted", "absent"])
def test_actual_missing_source_deletes_only_derived_vectors(world, monkeypatch, missing):
    if missing == "deleted":
        world.file.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        world.db.execute(delete(FileManagerFile).where(FileManagerFile.id == world.file.id))
    world.db.commit()
    deletions = []
    service = SimpleNamespace(
        sync_projection=trap,
        delete_projection=lambda **kwargs: deletions.append(kwargs),
    )
    monkeypatch.setattr(
        rag_sync,
        "_rag_runtime_for_job",
        lambda db, job: SimpleNamespace(service=service, collection="synthetic-derived-only"),
    )
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        assert rag_sync._process_sync_job(world.db, world.job) == "deleted_missing_projection"
    assert len(deletions) == 1
    assert deletions[0]["resource_id"] == world.job.resource_id
    assert world.db.scalar(select(func.count()).select_from(SearchIndexJob)) == 0


def test_backend_effect_then_control_retains_attempt_and_requires_reconciliation(
    world, monkeypatch
):
    world.file.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    world.db.commit()
    deletions = []
    service = SimpleNamespace(
        sync_projection=trap,
        delete_projection=lambda **kwargs: deletions.append(kwargs),
    )
    monkeypatch.setattr(
        rag_sync,
        "_rag_runtime_for_job",
        lambda db, job: SimpleNamespace(service=service, collection="synthetic-derived-only"),
    )

    def callback_after_effect(*args, **kwargs):
        assert len(deletions) == 1
        raise FileArtifactInvalid("event_head_changed_after_effect")

    actual_adapter = rag_sync._resource_adapter_for_job(world.job)
    injected_adapter = replace(actual_adapter, on_projection_deleted=callback_after_effect)
    monkeypatch.setattr(rag_sync, "_resource_adapter_for_job", lambda job: injected_adapter)
    forbid_source_dml(world)
    identity = (world.job.id, world.job.projection_event_sequence, world.job.projection_version)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        result = rag_sync._execute_sync_job(
            world.db,
            task=SimpleNamespace(retry=trap),
            job=world.job,
            span_name="test.prepared.files.effect",
            job_kind="resource_sync",
            rag_enabled=True,
        )
    assert result == "file_projection_effect_unknown"
    assert len(deletions) == 1
    assert world.job.status == RagJobStatus.FAILED
    assert world.job.attempts == 1
    assert world.job.next_retry_at is None
    assert identity == (
        world.job.id,
        world.job.projection_event_sequence,
        world.job.projection_version,
    )


def test_delete_job_with_active_event_is_held_before_provider(world, monkeypatch):
    world.job.operation = "delete"
    world.db.commit()
    forbid_source_dml(world)
    monkeypatch.setattr(rag_sync, "_rag_runtime_for_job", trap)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        result = rag_sync._execute_sync_job(
            world.db,
            task=SimpleNamespace(retry=trap),
            job=world.job,
            span_name="test.prepared.files.invalid-delete",
            job_kind="resource_sync",
            rag_enabled=True,
        )
    assert result == "file_artifact_invalid"
    assert world.job.attempts == 0
    assert world.job.status == RagJobStatus.FAILED
    assert world.file.extraction_status == "ready"
    assert world.file.extraction_content_checksum == CHECKSUM


@pytest.mark.parametrize("phase", ["preflight", "after_effect"])
@pytest.mark.parametrize("ack", ["before_commit", "after_commit"])
def test_hold_commit_unknown_preserves_identity_and_bypasses_retry(world, monkeypatch, phase, ack):
    deletions = []
    if phase == "preflight":
        world.file.extraction_status = "pending"
        monkeypatch.setattr(rag_sync, "_rag_runtime_for_job", trap)
    else:
        world.file.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        service = SimpleNamespace(
            sync_projection=trap,
            delete_projection=lambda **kwargs: deletions.append(kwargs),
        )
        monkeypatch.setattr(
            rag_sync,
            "_rag_runtime_for_job",
            lambda db, job: SimpleNamespace(service=service, collection="synthetic-derived-only"),
        )

        def callback_after_effect(*args, **kwargs):
            assert len(deletions) == 1
            raise FileArtifactInvalid("event_head_changed_after_effect")

        adapter = replace(
            rag_sync._resource_adapter_for_job(world.job),
            on_projection_deleted=callback_after_effect,
        )
        monkeypatch.setattr(rag_sync, "_resource_adapter_for_job", lambda job: adapter)
    world.db.commit()
    identity = (world.job.id, world.job.projection_event_sequence, world.job.projection_version)
    actual_commit = world.db.commit

    def uncertain_commit():
        if ack == "after_commit":
            actual_commit()
        raise RuntimeError("synthetic COMMIT acknowledgement failure")

    monkeypatch.setattr(world.db, "commit", uncertain_commit)
    monkeypatch.setattr(rag_sync, "_handle_sync_job_failure", trap)
    forbid_source_dml(world)
    with prepared_core_file_projection(world.db, projection_event=world.ref):
        outcome = rag_sync._execute_sync_job(
            world.db,
            task=SimpleNamespace(retry=trap),
            job=world.job,
            span_name="test.prepared.files.hold-commit",
            job_kind="resource_sync",
            rag_enabled=True,
        )
    assert outcome == "file_projection_hold_commit_unknown"
    assert len(deletions) == (1 if phase == "after_effect" else 0)
    with Session(world.engine) as observed:
        actual = observed.get(RagSyncJob, identity[0])
        assert (actual.id, actual.projection_event_sequence, actual.projection_version) == identity
        assert actual.next_retry_at is None
        if ack == "after_commit":
            assert actual.status == RagJobStatus.FAILED
            assert actual.last_error == (
                "file_artifact_not_ready"
                if phase == "preflight"
                else "file_projection_effect_unknown"
            )
            assert actual.attempts == (0 if phase == "preflight" else 1)
        else:
            assert actual.status == RagJobStatus.PROCESSING
            assert actual.attempts == 1
            assert actual.last_error is None
        source = observed.get(FileManagerFile, "prepared-file-1")
        assert source.extraction_status == ("pending" if phase == "preflight" else "ready")
        assert observed.scalar(select(func.count()).select_from(SearchIndexJob)) == 0


def test_legacy_callbacks_retain_original_source_behavior(monkeypatch):
    calls = []
    monkeypatch.setattr(
        files_rag_sync, "purge_deleted_file_retrieval_artifact", lambda *a, **kw: calls.append(kw)
    )
    monkeypatch.setattr(
        files_rag_sync, "mark_file_extraction_failed", lambda *a, **kw: calls.append(kw)
    )
    with Session() as db:
        files_rag_sync.mark_file_projection_deleted(db, file_id="legacy-file")
        files_rag_sync.mark_file_projection_failed(
            db, file_id="legacy-file", error="known parse failure", phase="parser"
        )
    assert calls == [
        {"file_id": "legacy-file"},
        {"file_id": "legacy-file", "error_code": "parser:known parse failure"},
    ]
