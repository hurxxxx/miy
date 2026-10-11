from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.groups.models import Group
from miy_api.domains.files.rag_sync import (
    capture_file_retrieval_event_watermark,
    inspect_file_retrieval_reconciliation,
    stage_file_retrieval_reconciliation,
)
from miy_api.domains.files import rag_sync as files_rag_sync
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFolder,
)
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.retrieval import official_projection_ingress
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import record_projection_event
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.models import SearchIndexJob
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE


_PARTITION_ID = "6fa05b2e-8f30-4388-af56-c229636fa6c9"


def _stub_sqlite_core_dispatch(monkeypatch) -> list[ProjectionIntent]:
    # SQLite controls Core head/job behavior here. The real Source transport,
    # READ COMMITTED and role admission remain covered by PostgreSQL four-hook
    # and authority tests in the full release CI.
    intents: list[ProjectionIntent] = []

    def _record_and_stage_core(db: Session, *, intent: ProjectionIntent) -> ProjectionEventRef:
        assert isinstance(intent, ProjectionIntent)
        intents.append(intent)
        projection_event = record_projection_event(
            db, **intent.model_dump(mode="json", exclude={"operation"})
        )
        official_projection_ingress._stage_jobs(
            db, intent, projection_event, publish_after_commit=False
        )
        return projection_event

    monkeypatch.setattr(files_rag_sync, "emit_and_accept_projection", _record_and_stage_core)
    monkeypatch.setattr(
        official_projection_ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True)
    )
    return intents


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            Group.__table__,
            User.__table__,
            RuntimeOwnership.__table__,
            RetrievalPartition.__table__,
            FileManagerCorpus.__table__,
            FileManagerFolder.__table__,
            FileManagerFile.__table__,
            RetrievalProjectionHead.__table__,
            RetrievalProjectionEvent.__table__,
            SearchIndexJob.__table__,
            RagSyncJob.__table__,
        ],
    )
    session = Session(engine)
    session.add(
        RuntimeOwnership(
            scope="official.suite",
            active_owner="legacy",
            generation=1,
            artifact=None,
            state="active",
        )
    )
    session.flush()
    session.add_all(
        [
            User(
                id="user-1",
                login_id="user-1",
                email="user-1@example.com",
                full_name="User 1",
                password_hash="hash",
            ),
            RetrievalPartition(
                id=_PARTITION_ID,
                source_namespace="files",
                candidate_scope_kind="company",
                is_default_ingest=False,
            ),
        ]
    )
    session.flush()
    return session


def _legacy_file(
    *,
    file_id: str,
    checksum: str | None,
    deleted: bool = False,
) -> FileManagerFile:
    return FileManagerFile(
        id=file_id,
        retrieval_partition_id=_PARTITION_ID,
        owner_id="user-1",
        filename=f"{file_id}.txt",
        content_type="text/plain",
        size_bytes=100,
        storage_key=f"files/{file_id}/document.txt",
        visibility="company",
        extraction_status="ready" if checksum is not None else "pending",
        extraction_content_checksum=checksum,
        extraction_text="cached extracted text" if checksum is not None else None,
        extraction_blocks=[],
        extraction_metadata={},
        deleted_at=(datetime.now(UTC).replace(tzinfo=None) if deleted else None),
    )


def test_reactivation_watermark_requires_both_backends_and_no_newer_file_event() -> None:
    db = _session()
    try:
        event_ref = record_projection_event(
            db,
            resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
            resource_id="file-1",
            retrieval_partition_id=_PARTITION_ID,
            change_kind="delete",
            desired_state="deleted",
        )
        watermark = capture_file_retrieval_event_watermark(db)
        stage_file_retrieval_reconciliation(
            db,
            after_event_sequence=0,
            through_event_sequence=watermark,
        )

        pending = inspect_file_retrieval_reconciliation(
            db,
            through_event_sequence=watermark,
        )

        assert pending.caught_up is False
        assert pending.current_event_sequence == watermark
        assert pending.keyword_remaining == 1
        assert pending.vector_remaining == 1

        search_job = db.scalar(select(SearchIndexJob))
        rag_job = db.scalar(select(RagSyncJob))
        assert search_job is not None and rag_job is not None
        search_job.status = "succeeded"
        rag_job.status = "succeeded"
        db.flush()

        complete = inspect_file_retrieval_reconciliation(
            db,
            through_event_sequence=watermark,
        )
        assert complete.caught_up is True
        assert complete.keyword_remaining == 0
        assert complete.vector_remaining == 0

        newer = record_projection_event(
            db,
            resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
            resource_id="file-1",
            retrieval_partition_id=_PARTITION_ID,
            change_kind="content",
            desired_state="active",
            content_checksum="b" * 64,
        )
        assert newer.event_sequence > event_ref.event_sequence
        drifted = inspect_file_retrieval_reconciliation(
            db,
            through_event_sequence=watermark,
        )
        assert drifted.caught_up is False
        assert drifted.current_event_sequence == newer.event_sequence
    finally:
        db.close()
