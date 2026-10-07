"""Current File content at common retrieval's pre-AI and final use boundaries."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.retrieval import application as retrieval_application
from miy_api.domains.retrieval.contracts import RetrievalHit
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE

_EXTRACTED_AT = datetime(2026, 10, 7, 10, 0, 0, 123456, tzinfo=UTC)
_EXTRACTION_MARKER = "2026-10-07T10:00:00.123456+00:00"


@pytest.fixture
def current_file(monkeypatch: pytest.MonkeyPatch):
    import_all_models()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    # Owned synthetic Source tables only; no platform schema/role authority claim.
    FileManagerCorpus.__table__.create(engine)
    FileManagerFile.__table__.create(engine)
    FileManagerFileSourceMetadata.__table__.create(engine)
    file_id, partition_id = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            insert(FileManagerFile.__table__).values(
                id=file_id,
                owner_id="synthetic-owner",
                filename="Synthetic.txt",
                content_type="text/plain",
                storage_key="synthetic-only",
                size_bytes=16,
                visibility="company",
                retrieval_partition_id=partition_id,
                extraction_status="ready",
                extraction_content_checksum="a" * 64,
                extracted_at=_EXTRACTED_AT,
            )
        )

    class AllowCandidates:
        def authorize_many_resources(self, resources):
            return set(resources)

        def authorize_many_rag_resources(self, resources):
            return set(resources)

    monkeypatch.setattr(
        retrieval_application.SourceAclPolicy,
        "for_user",
        lambda _db, *, user: AllowCandidates(),
    )
    with Session(engine) as db:
        yield db, file_id, partition_id
    engine.dispose()


def _candidate(file_id: str, partition_id: str, *, checksum: str = "a" * 64):
    return RetrievalHit(
        source="generic_rag",
        source_kind="files",
        resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
        resource_id=file_id,
        excerpt="SYNTHETIC-ORIGINAL-CONTENT",
        metadata={
            "content_checksum": checksum,
            "retrieval_partition_id": partition_id,
            "extracted_at": _EXTRACTION_MARKER,
        },
    )


@pytest.mark.parametrize(
    "change",
    [
        {"extraction_status": "pending", "extraction_content_checksum": None},
        {"extraction_status": "failed", "extraction_content_checksum": None},
        {"extraction_status": "unsupported", "extraction_content_checksum": None},
        {"deleted_at": datetime(2026, 10, 7)},
        {"extraction_content_checksum": "b" * 64},
        {"retrieval_partition_id": str(uuid4())},
        {"extracted_at": datetime(2026, 10, 7, 10, 1, tzinfo=UTC)},
        {"extracted_at": None},
    ],
)
def test_common_retrieval_drops_content_changed_after_candidate_creation(current_file, change):
    db, file_id, partition_id = current_file
    candidate = _candidate(file_id, partition_id)
    db.execute(update(FileManagerFile).where(FileManagerFile.id == file_id).values(**change))
    db.commit()
    assert (
        retrieval_application._filter_current_retrieval_hits(
            db, user=SimpleNamespace(id="synthetic-owner"), hits=[candidate]
        )
        == []
    )


def test_common_retrieval_keeps_current_candidate_and_other_resource(current_file):
    db, file_id, partition_id = current_file
    candidate = _candidate(file_id, partition_id)
    other = RetrievalHit(source="keyword", resource_type="pms_task", resource_id="synthetic-task")
    assert retrieval_application._filter_current_retrieval_hits(
        db, user=SimpleNamespace(id="synthetic-owner"), hits=[candidate, other]
    ) == [candidate, other]


def test_common_retrieval_checks_again_after_ranking_input_changes(current_file):
    db, file_id, partition_id = current_file
    candidate = _candidate(file_id, partition_id)
    first = retrieval_application._filter_current_retrieval_hits(
        db, user=SimpleNamespace(id="synthetic-owner"), hits=[candidate]
    )
    assert first == [candidate]
    db.execute(
        update(FileManagerFile)
        .where(FileManagerFile.id == file_id)
        .values(extraction_content_checksum="b" * 64)
    )
    db.commit()
    assert (
        retrieval_application._filter_current_retrieval_hits(
            db, user=SimpleNamespace(id="synthetic-owner"), hits=first
        )
        == []
    )


def test_common_retrieval_preserves_content_after_display_metadata_change(current_file):
    db, file_id, partition_id = current_file
    candidate = _candidate(file_id, partition_id)
    db.execute(
        update(FileManagerFile)
        .where(FileManagerFile.id == file_id)
        .values(filename="Renamed.txt", updated_at=datetime(2026, 10, 7, 11, tzinfo=UTC))
    )
    db.commit()
    assert retrieval_application._filter_current_retrieval_hits(
        db, user=SimpleNamespace(id="synthetic-owner"), hits=[candidate]
    ) == [candidate]


@pytest.mark.parametrize("field", ["content_checksum", "retrieval_partition_id", "extracted_at"])
def test_common_retrieval_drops_unverifiable_file_candidates(current_file, field):
    db, file_id, partition_id = current_file
    candidate = _candidate(file_id, partition_id)
    candidate.metadata.pop(field)
    assert (
        retrieval_application._filter_current_retrieval_hits(
            db, user=SimpleNamespace(id="synthetic-owner"), hits=[candidate]
        )
        == []
    )
