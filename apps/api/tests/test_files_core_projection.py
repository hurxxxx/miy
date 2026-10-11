"""Bounded reader/control contracts; actual restricted PG proof is separately owned."""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import rag_projection
from miy_api.domains.files.core_projection import (
    FileArtifactInvalid,
    load_ready_file_rag_projection,
    prepared_core_file_projection,
)
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef

PARTITION = "a3b6638a-7547-45f8-81f2-973bfa6080d6"
CHECKSUM = "a" * 64


@pytest.fixture
def projection_event():
    return ProjectionEventRef(
        2, "file_manager_file", "file-1", 2, PARTITION, "content", "active", CHECKSUM, None
    )


@pytest.fixture
def ready_file():
    import_all_models()
    block = EvidenceBlock(
        "file-1",
        "file-1:text:1",
        "document",
        "Document",
        "Body",
        "text",
        "A bounded canonical Source artifact.",
    )
    file = FileManagerFile(
        id="file-1",
        owner_id="user-1",
        filename="plan.txt",
        content_type="text/plain",
        storage_key="files/file-1/input.txt",
        size_bytes=42,
        visibility="private",
        retrieval_partition_id=PARTITION,
        extraction_status="ready",
        extraction_content_checksum=CHECKSUM,
        extraction_text=block.text,
        extraction_blocks=[block.to_dict()],
        extraction_metadata={"parser_version": "legacy"},
    )
    file.owner = User(id="user-1", full_name="Source owner", display_name="Owner label")
    return file


@pytest.fixture
def reader_db(monkeypatch, projection_event, ready_file):
    """A real unbound Session with deterministic persisted rows, not SQL authority proof."""
    db = Session()
    statements = []
    event_fields = (
        "event_sequence",
        "resource_type",
        "resource_id",
        "projection_version",
        "retrieval_partition_id",
        "change_kind",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    )
    head_fields = (
        "projection_version",
        "retrieval_partition_id",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    )
    state = SimpleNamespace(
        file=ready_file,
        event=tuple(getattr(projection_event, name) for name in event_fields),
        head=tuple(getattr(projection_event, name) for name in head_fields),
        statements=statements,
    )

    def execute(statement):
        assert statement.is_select
        assert db.autoflush is False
        statements.append(statement)
        row = state.event if "retrieval_projection_events" in str(statement) else state.head
        return SimpleNamespace(one_or_none=lambda: row)

    def scalar(statement):
        assert statement.is_select
        assert db.autoflush is False
        statements.append(statement)
        return state.file

    def forbidden(*_args, **_kwargs):
        raise AssertionError("reader attempted IO, extraction or transaction mutation")

    monkeypatch.setattr(db, "execute", execute)
    monkeypatch.setattr(db, "scalar", scalar)
    monkeypatch.setattr(db, "flush", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    monkeypatch.setattr(rag_projection, "read_file_content", forbidden)
    monkeypatch.setattr(rag_projection, "extract_file_artifact", forbidden)
    monkeypatch.setattr(rag_projection.file_storage, "open_file_object", forbidden)
    try:
        yield db, state
    finally:
        db.close()


def read(reader_db, projection_event, **kwargs):
    db, _ = reader_db
    with prepared_core_file_projection(db, projection_event=projection_event):
        return load_ready_file_rag_projection(db, file_id="file-1", **kwargs)


@pytest.mark.parametrize("key", ["visibility"])
def test_artifact_metadata_cannot_override_source_or_safe_projection_fields(
    reader_db, projection_event, key
):
    _, state = reader_db
    state.file.extraction_metadata = {key: "synthetic-conflicting-metadata"}
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "metadata_reserved_key"
