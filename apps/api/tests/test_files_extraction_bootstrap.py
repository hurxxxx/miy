from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import User
from miy_api.domains.files import rag_projection, retrieval_contract
from miy_api.domains.files.extraction_bootstrap import bootstrap_file_extraction_artifacts
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
)
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE


_PARTITION_ID = "3b348bd8-7c75-48a1-a5c7-3c9e9a77fd11"
_RUNNER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "manage_files_retrieval_generation.py"
)


def _load_runner_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "test_files_extraction_bootstrap_runner_script",
        _RUNNER_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ExtractionRuntime:
    ocr_provider_name = "test-ocr"

    def extract_text(self, **_kwargs) -> str:
        raise AssertionError("plain text bootstrap must not invoke OCR")


@pytest.fixture
def db(application_postgres_dsn):
    # The canonical hook now owns real Source outbox + Core acceptance SQL.
    # Reuse the migrated disposable PG schema instead of a partial SQLite copy.
    engine = create_engine(application_postgres_dsn)
    session = Session(engine)
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
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _pending_file(file_id: str) -> FileManagerFile:
    return FileManagerFile(
        id=file_id,
        retrieval_partition_id=_PARTITION_ID,
        owner_id="user-1",
        filename=f"{file_id}.txt",
        content_type="text/plain",
        size_bytes=64,
        storage_key=f"files/{file_id}/document.txt",
        visibility="company",
        extraction_status="pending",
        extraction_blocks=[],
        extraction_metadata={},
    )


def test_bootstrap_is_resumable_and_does_not_duplicate_current_ready_head(
    monkeypatch: pytest.MonkeyPatch,
    db: Session,
) -> None:
    try:
        db.add_all([_pending_file("file-1"), _pending_file("file-2")])
        db.flush()
        monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", False)
        monkeypatch.setattr(
            rag_projection,
            "read_file_content",
            lambda file: f"{file.id} 접근 권한 기준".encode(),
        )

        first = bootstrap_file_extraction_artifacts(
            db,
            after_file_id=None,
            limit=1,
            extraction_runtime=_ExtractionRuntime(),
        )
        second = bootstrap_file_extraction_artifacts(
            db,
            after_file_id=first.next_file_id,
            limit=1,
            extraction_runtime=_ExtractionRuntime(),
        )
        event_count = int(
            db.scalar(
                select(func.count())
                .select_from(RetrievalProjectionEvent)
                .where(RetrievalProjectionEvent.resource_type == FILE_MANAGER_FILE_RESOURCE_TYPE)
            )
            or 0
        )
        repeated = bootstrap_file_extraction_artifacts(
            db,
            after_file_id=None,
            limit=10,
            extraction_runtime=_ExtractionRuntime(),
        )

        assert first.complete is False and first.next_file_id == "file-1"
        assert second.complete is True and second.next_file_id == "file-2"
        assert repeated.ready_files == 2
        assert repeated.recorded_events == 0
        assert event_count == 2
        assert (
            int(
                db.scalar(
                    select(func.count())
                    .select_from(RetrievalProjectionEvent)
                    .where(
                        RetrievalProjectionEvent.resource_type == FILE_MANAGER_FILE_RESOURCE_TYPE
                    )
                )
                or 0
            )
            == event_count
        )
    finally:
        db.close()
