from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import uuid4

from miy_api.domains.auth.models import User
from miy_api.domains.files.models import (
    FileManagerFile,
)
from miy_api.domains.files import rag_projection, rag_sync
from miy_api.domains.files.rag_projection import (
    MAX_FILES_RAG_SOURCE_BYTES,
    UnsupportedFileForRetrieval,
    read_file_content,
)


_FIXED_ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


def _assert_legacy_loader_stored_output_marker(db_session, monkeypatch):
    from miy_api.domains.files.current_content import file_extraction_result_marker

    owner = User(
        id=str(uuid4()),
        login_id=str(uuid4()),
        email="synthetic-marker@example.invalid",
        full_name="Synthetic",
        password_hash="synthetic",
    )
    db_session.add(owner)
    db_session.flush()
    file = _file(
        id=str(uuid4()),
        folder_id=None,
        owner_id=owner.id,
        filename="Synthetic.txt",
        content_type="text/plain",
        storage_key="synthetic-marker/" + str(uuid4()),
        extraction_status="pending",
        extracted_at=None,
    )
    db_session.add(file)
    db_session.flush()
    monkeypatch.setattr(rag_projection, "read_file_content", lambda _: b"Synthetic local text")
    runtime = SimpleNamespace(ocr_provider_name="unused")
    projection = rag_projection.load_file_rag_projection(
        db_session, file_id=file.id, rag_service=runtime
    )
    stored_time = db_session.scalar(
        select(FileManagerFile.extracted_at).where(FileManagerFile.id == file.id)
    )
    assert stored_time is not None and file.extracted_at == stored_time
    assert projection.metadata["extracted_at"] == file_extraction_result_marker(stored_time)


def _file(**overrides) -> FileManagerFile:
    values = {
        "id": "file-1",
        "folder_id": "folder-1",
        "owner_id": "user-1",
        "filename": "quarterly-plan.pptx",
        "content_type": "application/octet-stream",
        "size_bytes": 100,
        "storage_key": "files/file-1/quarterly-plan.pptx",
        "visibility": "company",
    }
    values.update(overrides)
    return FileManagerFile(**values)


def _pptx_signature() -> bytes:
    return _openxml_signature("ppt/presentation.xml")


def _openxml_signature(marker: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        _write_deterministic_zip_entry(archive, "[Content_Types].xml", b"<Types />")
        _write_deterministic_zip_entry(archive, marker, b"<document />")
    return output.getvalue()


def _hostile_openxml_archive(marker: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        _write_deterministic_zip_entry(archive, "[Content_Types].xml", b"<Types />")
        _write_deterministic_zip_entry(archive, marker, b"<document />")
        _write_deterministic_zip_entry(
            archive,
            "payload.bin",
            b"x" * (2 * 1024 * 1024),
        )
    return output.getvalue()


def _write_deterministic_zip_entry(
    archive: ZipFile,
    filename: str,
    content: bytes,
) -> None:
    entry = ZipInfo(filename=filename, date_time=_FIXED_ZIP_TIMESTAMP)
    entry.compress_type = ZIP_DEFLATED
    archive.writestr(entry, content)


def test_file_reader_closes_storage_response_and_enforces_declared_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StoredObject:
        closed = False
        released = False

        def stream(self, chunk_size: int):
            assert chunk_size > 0
            yield b"first"
            yield b"second"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
            self.released = True

    stored = StoredObject()
    monkeypatch.setattr(
        rag_projection.file_storage,
        "open_file_object",
        lambda storage_key: stored,
    )

    assert read_file_content(_file(filename="notes.txt", size_bytes=11)) == b"firstsecond"
    assert stored.closed is True
    assert stored.released is True

    with pytest.raises(UnsupportedFileForRetrieval, match="source_size_limit_exceeded"):
        read_file_content(_file(size_bytes=MAX_FILES_RAG_SOURCE_BYTES + 1))

    # Both gate states and extraction-before-keyword ordering are verified on
    # actual PostgreSQL in test_official_projection_outbox's four-hook case.


def test_vector_provider_failure_does_not_overwrite_ready_extraction_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        rag_sync,
        "mark_file_extraction_failed",
        lambda db, **kwargs: calls.append(kwargs),
    )

    with Session() as db:
        rag_sync.mark_file_projection_failed(
            db, file_id="file-1", error="embedding provider unavailable", phase="rag"
        )
        assert calls == []
        rag_sync.mark_file_projection_failed(
            db, file_id="file-1", error="document parser failed", phase="extraction"
        )
    assert calls == [
        {
            "file_id": "file-1",
            "error_code": "extraction:document parser failed",
        }
    ]
