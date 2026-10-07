"""Bounded reader/control contracts; actual restricted PG proof is separately owned."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import rag_projection
from miy_api.domains.files.core_projection import (
    FileArtifactChecksumMismatch,
    FileArtifactInvalid,
    FileArtifactNotReady,
    is_prepared_core_file_projection,
    load_ready_file_rag_projection,
    prepared_core_file_projection,
    require_prepared_core_file_projection_event,
)
from miy_api.domains.files.models import FileManagerFile, FileManagerFileSourceMetadata
from miy_api.domains.files.rag_projection import extract_file_artifact
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


def test_ready_reader_builds_existing_projection_without_io_or_source_writes(
    reader_db, projection_event
):
    db, state = reader_db
    projection = read(reader_db, projection_event, expected_checksum=CHECKSUM)
    assert projection.resource_id == "file-1"
    assert projection.text_content == state.file.extraction_text
    assert projection.owner_label == "Owner label"
    assert projection.visibility_refs == ["owner:user-1"]
    assert len(state.statements) == 3
    assert db.autoflush is True
    assert not is_prepared_core_file_projection(db)


def test_reader_selects_only_declared_owner_and_safe_metadata_columns(reader_db, projection_event):
    read(reader_db, projection_event)
    _, state = reader_db
    sql = str(state.statements[-1].compile(dialect=postgresql.dialect()))
    for field in ("display_name", "full_name", "content_checksum", "access_scope_kind"):
        assert field in sql
    for field in (
        "password_hash",
        "email",
        "login_id",
        "source_uri",
        "raw_metadata",
        "external_id",
        "source_id",
        "FOR UPDATE",
        "FOR SHARE",
    ):
        assert field not in sql
    assert state.statements[-1].get_execution_options()["populate_existing"] is True


def test_unprepared_and_boolean_context_do_not_select(reader_db):
    db, state = reader_db
    db.info["prepared_core_file_projection"] = True
    assert not is_prepared_core_file_projection(db)
    with pytest.raises(FileArtifactInvalid) as caught:
        load_ready_file_rag_projection(db, file_id="file-1", expected_checksum=CHECKSUM)
    assert caught.value.reason == "file_projection_context_required"
    assert not state.statements


def test_nested_context_refused_and_context_removed_on_exception(reader_db, projection_event):
    db, _ = reader_db
    with pytest.raises(RuntimeError, match="synthetic"):
        with prepared_core_file_projection(db, projection_event=projection_event):
            assert is_prepared_core_file_projection(db)
            with pytest.raises(FileArtifactInvalid):
                with prepared_core_file_projection(db, projection_event=projection_event):
                    pass
            raise RuntimeError("synthetic")
    assert not is_prepared_core_file_projection(db)


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_sequence": 0},
        {"event_sequence": True},
        {"projection_version": 0},
        {"resource_type": "docs_native_doc"},
        {"retrieval_partition_id": "not-a-uuid"},
        {"content_checksum": "not-a-checksum"},
        {"desired_state": "unknown"},
        {"change_kind": "delete"},
        {"visibility_checksum": object()},
    ],
)
def test_invalid_reference_cannot_prepare(reader_db, projection_event, overrides):
    db, state = reader_db
    with pytest.raises(FileArtifactInvalid):
        with prepared_core_file_projection(
            db, projection_event=replace(projection_event, **overrides)
        ):
            pass
    assert not state.statements
    assert not is_prepared_core_file_projection(db)


def test_supplied_reference_or_resource_cannot_escape_context(reader_db, projection_event):
    db, state = reader_db
    with prepared_core_file_projection(db, projection_event=projection_event):
        with pytest.raises(FileArtifactInvalid):
            require_prepared_core_file_projection_event(db, file_id="another-file")
        with pytest.raises(FileArtifactInvalid):
            require_prepared_core_file_projection_event(
                db, projection_event=replace(projection_event, event_sequence=99)
            )
    assert not state.statements


@pytest.mark.parametrize("actual", [None, (99,)])
def test_missing_or_forged_actual_event_refuses_before_source_read(
    reader_db, projection_event, actual
):
    _, state = reader_db
    state.event = actual
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "persisted_event_mismatch"
    assert len(state.statements) == 1


@pytest.mark.parametrize("head", [None, (3, PARTITION, "active", CHECKSUM, None)])
def test_noncurrent_head_is_control_outcome_before_source_read(reader_db, projection_event, head):
    _, state = reader_db
    state.head = head
    with pytest.raises(FileArtifactNotReady) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "event_superseded"
    assert len(state.statements) == 2


@pytest.mark.parametrize("deleted", [False, True])
def test_only_missing_or_deleted_source_returns_none(reader_db, projection_event, deleted):
    _, state = reader_db
    if deleted:
        state.file.deleted_at = datetime(2026, 10, 7)
        state.file.extraction_blocks = None
    else:
        state.file = None
    assert read(reader_db, projection_event) is None


@pytest.mark.parametrize("status", ["pending", "failed", "unsupported"])
def test_pending_failed_active_unsupported_are_not_missing(reader_db, projection_event, status):
    _, state = reader_db
    state.file.extraction_status = status
    with pytest.raises(FileArtifactNotReady) as caught:
        read(reader_db, projection_event)
    assert caught.value.code == "file_artifact_not_ready"
    assert caught.value.reason == "source_" + status


def test_ready_with_pending_event_checksum_cannot_claim_ready(reader_db, projection_event):
    _, state = reader_db
    event = replace(projection_event, content_checksum=None)
    state.event = (*state.event[:-2], None, None)
    state.head = (*state.head[:-2], None, None)
    with pytest.raises(FileArtifactNotReady) as caught:
        read(reader_db, event)
    assert caught.value.reason == "event_checksum_pending"


def test_deleted_context_permitted_but_active_source_is_not_missing(reader_db, projection_event):
    db, state = reader_db
    event = replace(
        projection_event, change_kind="delete", desired_state="deleted", content_checksum=None
    )
    state.event = (
        event.event_sequence,
        event.resource_type,
        event.resource_id,
        event.projection_version,
        event.retrieval_partition_id,
        "delete",
        "deleted",
        None,
        None,
    )
    state.head = (event.projection_version, PARTITION, "deleted", None, None)
    with prepared_core_file_projection(db, projection_event=event):
        assert require_prepared_core_file_projection_event(db) == event
        with pytest.raises(FileArtifactNotReady):
            load_ready_file_rag_projection(db, file_id="file-1")
        state.file.deleted_at = datetime(2026, 10, 7)
        assert load_ready_file_rag_projection(db, file_id="file-1") is None


@pytest.mark.parametrize("kind", ["explicit", "artifact", "external"])
def test_checksum_conflicts_are_stable_refusals(reader_db, projection_event, kind):
    _, state = reader_db
    kwargs = {}
    if kind == "explicit":
        kwargs["expected_checksum"] = "b" * 64
    elif kind == "artifact":
        state.file.extraction_content_checksum = "b" * 64
    else:
        state.file.source_metadata = FileManagerFileSourceMetadata(content_checksum="b" * 64)
    with pytest.raises(FileArtifactChecksumMismatch) as caught:
        read(reader_db, projection_event, **kwargs)
    assert caught.value.code == "file_artifact_checksum_mismatch"


def test_source_binding_mismatch_refuses_ready(reader_db, projection_event):
    _, state = reader_db
    state.file.retrieval_partition_id = "41ca1cb8-ef8e-4fc4-bab1-8c1e5f673268"
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "source_partition_mismatch"


@pytest.mark.parametrize(
    "field,value",
    [
        ("extraction_status", "unknown"),
        ("extraction_text", ""),
        ("extraction_text", "x" * 240_001),
        ("extraction_blocks", []),
        ("extraction_metadata", []),
        ("extraction_content_checksum", "invalid"),
    ],
)
def test_malformed_ready_artifact_is_never_missing(reader_db, projection_event, field, value):
    _, state = reader_db
    setattr(state.file, field, value)
    with pytest.raises(FileArtifactInvalid):
        read(reader_db, projection_event)


@pytest.mark.parametrize(
    "kind",
    [
        "identity",
        "duplicate",
        "unknown_field",
        "block_text",
        "empty_block_text",
        "rows",
        "cells",
        "row_text",
        "locator",
    ],
)
def test_evidence_identity_and_full_rows_are_bounded(reader_db, projection_event, kind):
    _, state = reader_db
    block = state.file.extraction_blocks[0]
    if kind == "identity":
        block["document_id"] = "another-file"
    elif kind == "duplicate":
        state.file.extraction_blocks.append(dict(block))
    elif kind == "unknown_field":
        block["unvalidated_payload"] = "x"
    elif kind == "block_text":
        block["text"] = "x" * 240_001
    elif kind == "empty_block_text":
        block["text"] = "   "
    elif kind == "rows":
        block["rows"] = [[]] * 4_097
    elif kind == "cells":
        block["rows"] = [[""] * 16_385]
    elif kind == "row_text":
        block["rows"] = [["x" * 240_001]]
    elif kind == "locator":
        block["locator_label"] = "x" * 4_097
    with pytest.raises(FileArtifactInvalid):
        read(reader_db, projection_event)


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), object(), 2**64, {1: "bad"}, "x" * 4_097]
)
def test_metadata_non_json_and_unbounded_values_refused(reader_db, projection_event, value):
    _, state = reader_db
    state.file.extraction_metadata = {"value": value}
    with pytest.raises(FileArtifactInvalid):
        read(reader_db, projection_event)


@pytest.mark.parametrize("kind", ["depth", "nodes", "keys", "serialized_bytes"])
def test_complete_metadata_budget_refused(reader_db, projection_event, kind):
    _, state = reader_db
    value = {}
    if kind == "depth":
        for _ in range(9):
            value = {"child": value}
    elif kind == "nodes":
        value = {"values": [None] * 4_096}
    elif kind == "keys":
        value = {str(index): None for index in range(1_025)}
    else:
        value = {str(index): "가" * 4_000 for index in range(6)}
    state.file.extraction_metadata = value
    with pytest.raises(FileArtifactInvalid):
        read(reader_db, projection_event)


def test_whole_serialized_evidence_budget_is_independent_of_clipped_text(
    reader_db, projection_event
):
    _, state = reader_db
    prototype = state.file.extraction_blocks[0]
    state.file.extraction_blocks = [
        {**prototype, "block_id": f"file-1:{index}", "text": "x", "locator_label": "가" * 4_000}
        for index in range(400)
    ]
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "artifact_budget_exceeded"


def test_invalid_utf8_surrogate_does_not_escape_control_exception(reader_db, projection_event):
    _, state = reader_db
    state.file.extraction_text = "\ud800"
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "artifact_serialization_invalid"


@pytest.mark.parametrize(
    "key",
    [
        "content_checksum",
        "origin_ref",
        "corpus_id",
        "visibility",
        "source_title",
        "author",
        "chunking",
    ],
)
def test_artifact_metadata_cannot_override_source_or_safe_projection_fields(
    reader_db, projection_event, key
):
    _, state = reader_db
    state.file.extraction_metadata = {key: "synthetic-conflicting-metadata"}
    with pytest.raises(FileArtifactInvalid) as caught:
        read(reader_db, projection_event)
    assert caught.value.reason == "metadata_reserved_key"


@pytest.mark.parametrize("format", ["plain", "html"])
def test_current_native_parser_artifacts_pass_the_reader_without_ocr(
    reader_db, projection_event, format
):
    _, state = reader_db
    text = "A current native parser result with bounded meaningful source content. " * 10
    if format == "html":
        content = (
            "<!doctype html><html><head><title>Current parser</title></head>"
            "<body><main><h1>Source heading</h1><p>" + text + "</p></main></body></html>"
        ).encode()
        state.file.filename = "current.html"
        state.file.content_type = "text/html"
    else:
        content = text.encode()
        state.file.content_type = "text/plain"

    def no_ocr(*_args, **_kwargs):
        raise AssertionError("native compatibility check attempted OCR")

    # The symbol was imported before the fixture poisons the legacy loader.
    # Compute uses only trusted synthetic in-memory bytes, never storage IO.
    artifact = extract_file_artifact(
        file=state.file,
        content=content,
        rag_service=SimpleNamespace(extract_text=no_ocr, ocr_provider_name=None),
    )
    state.file.extraction_content_checksum = artifact.content_checksum
    state.file.extraction_text = artifact.text
    state.file.extraction_blocks = [block.to_dict() for block in artifact.blocks]
    state.file.extraction_metadata = artifact.metadata
    ref = replace(projection_event, content_checksum=artifact.content_checksum)
    state.event = (*state.event[:-2], artifact.content_checksum, None)
    state.head = (*state.head[:-2], artifact.content_checksum, None)
    projection = read(reader_db, ref)
    assert projection.metadata["content_checksum"] == artifact.content_checksum
    assert projection.metadata["parser_version"] == rag_projection.FILES_EXTRACTION_PARSER_VERSION
    assert projection.metadata["ocr_status"] == "not_required"
    assert projection.chunks
    assert "current native parser result" in projection.text_content
