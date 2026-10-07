"""Current identity uses a real owned SQLite query, never cached ORM authority."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, event, select
from sqlalchemy.orm import Session, load_only

from miy_api.core.model_registry import import_all_models
from miy_api.domains.files.current_content import (
    CurrentFileContent,
    file_candidate_matches_current_content,
    file_extraction_result_marker,
    load_current_file_content,
)
from miy_api.domains.files.models import FileManagerFile

PARTITION = "a3b6638a-7547-45f8-81f2-973bfa6080d6"
CHECKSUM = "a" * 64
STAMP = "2026-10-07T00:00:00.123456+00:00"
EXTRACTED = datetime(2026, 10, 7, microsecond=123456)


@pytest.fixture
def source_rows(tmp_path):
    import_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'content.sqlite'}")
    # A local read-seam table, not platform schema setup or migration proof.
    table = Table(
        "file_manager_files",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("deleted_at", DateTime),
        Column("extraction_status", String),
        Column("extraction_content_checksum", String),
        Column("retrieval_partition_id", String),
        Column("extracted_at", DateTime),
    )
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            {
                "id": "file-1",
                "extraction_status": "ready",
                "extraction_content_checksum": CHECKSUM,
                "retrieval_partition_id": PARTITION,
                "extracted_at": EXTRACTED,
            },
        )
    try:
        yield engine, table
    finally:
        engine.dispose()


def test_fresh_columns_ignore_cached_source_and_do_not_flush(source_rows):
    engine, table = source_rows
    with Session(engine) as db:
        cached = db.scalar(
            select(FileManagerFile).options(
                load_only(
                    FileManagerFile.id,
                    FileManagerFile.deleted_at,
                    FileManagerFile.extraction_status,
                    FileManagerFile.extraction_content_checksum,
                    FileManagerFile.retrieval_partition_id,
                )
            )
        )
        assert cached.extraction_content_checksum == CHECKSUM
        with engine.begin() as connection:
            connection.execute(table.update().values(extraction_content_checksum="b" * 64))
        assert cached.extraction_content_checksum == CHECKSUM
        pending = FileManagerFile(id="unflushed")
        db.add(pending)
        event.listen(db, "before_flush", lambda *_args: pytest.fail("content read flushed Source"))
        statements = []
        event.listen(engine, "before_cursor_execute", lambda _c, _u, s, *_a: statements.append(s))
        content = load_current_file_content(db, file_ids=["file-1", "file-1", "missing"])
        assert content == {"file-1": CurrentFileContent("b" * 64, UUID(PARTITION), STAMP)}
        assert cached.extraction_content_checksum == CHECKSUM
        assert pending in db.new
        assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")
        assert "extraction_text" not in statements[0] and "users" not in statements[0]
        with pytest.raises(TypeError):
            content["other"] = content["file-1"]
        with pytest.raises(FrozenInstanceError):
            content["file-1"].content_checksum = CHECKSUM


@pytest.mark.parametrize(
    "changes",
    [
        {"extraction_status": "pending"},
        {"extraction_status": "failed"},
        {"extraction_status": "unsupported"},
        {"deleted_at": datetime(2026, 10, 7)},
        {"extraction_content_checksum": None},
        {"extraction_content_checksum": "A" * 64},
        {"extraction_content_checksum": "a" * 63},
        {"extracted_at": None},
    ],
)
def test_unready_deleted_or_invalid_current_rows_have_no_witness(source_rows, changes):
    engine, table = source_rows
    with engine.begin() as connection:
        connection.execute(table.update().values(**changes))
    with Session(engine) as db:
        assert load_current_file_content(db, file_ids=["file-1"]) == {}


def test_legacy_none_partition_is_a_current_witness(source_rows):
    engine, table = source_rows
    with engine.begin() as connection:
        connection.execute(table.update().values(retrieval_partition_id=None))
    with Session(engine) as db:
        assert load_current_file_content(db, file_ids=["file-1"])["file-1"] == CurrentFileContent(
            CHECKSUM, None, STAMP
        )


def test_empty_set_needs_no_database():
    with Session() as db:
        assert load_current_file_content(db, file_ids=[]) == {}


@pytest.mark.parametrize(
    "checksum,partition,expected",
    [
        (CHECKSUM, PARTITION, True),
        (CHECKSUM, UUID(PARTITION), True),
        ("b" * 64, PARTITION, False),
        (None, PARTITION, False),
        ("A" * 64, PARTITION, False),
        ("a" * 63, PARTITION, False),
        (CHECKSUM, None, False),
        (CHECKSUM, "", False),
        (CHECKSUM, "malformed", False),
        (CHECKSUM, "31a974ba-7fe4-4c35-9d98-ea3bb9b82d12", False),
    ],
)
def test_candidate_must_match_known_current_envelope(checksum, partition, expected):
    assert (
        file_candidate_matches_current_content(
            CurrentFileContent(CHECKSUM, UUID(PARTITION), STAMP),
            candidate_checksum=checksum,
            candidate_partition_id=partition,
            candidate_extracted_at=STAMP,
        )
        is expected
    )


def test_missing_and_legacy_partition_match_without_object_conversion():
    class UntrustedObject:
        def __str__(self):
            pytest.fail("candidate object was converted to a string")

    match = file_candidate_matches_current_content
    assert not match(
        None,
        candidate_checksum=CHECKSUM,
        candidate_partition_id=PARTITION,
        candidate_extracted_at=STAMP,
    )
    legacy = CurrentFileContent(CHECKSUM, None, STAMP)
    assert match(
        legacy,
        candidate_checksum=CHECKSUM,
        candidate_partition_id=None,
        candidate_extracted_at=STAMP,
    )
    assert not match(
        legacy,
        candidate_checksum=CHECKSUM,
        candidate_partition_id=PARTITION,
        candidate_extracted_at=STAMP,
    )
    assert not match(
        legacy,
        candidate_checksum=UntrustedObject(),
        candidate_partition_id=None,
        candidate_extracted_at=STAMP,
    )
    assert not match(
        legacy,
        candidate_checksum=CHECKSUM,
        candidate_partition_id=UntrustedObject(),
        candidate_extracted_at=STAMP,
    )


@pytest.mark.parametrize(
    "marker",
    [None, "", "malformed", "2026-10-07T00:00:00.123456", "2026-10-07T00:00:00.123457+00:00"],
)
def test_same_raw_input_checksum_requires_same_canonical_result_stamp(marker):
    assert not file_candidate_matches_current_content(
        CurrentFileContent(CHECKSUM, UUID(PARTITION), STAMP),
        candidate_checksum=CHECKSUM,
        candidate_partition_id=PARTITION,
        candidate_extracted_at=marker,
    )


def test_result_stamp_normalizes_source_utc_microseconds():
    assert file_extraction_result_marker(EXTRACTED) == STAMP
    assert file_extraction_result_marker(EXTRACTED.replace(tzinfo=UTC)) == STAMP
    assert (
        file_extraction_result_marker(
            datetime(2026, 10, 7, 9, microsecond=123456, tzinfo=timezone(timedelta(hours=9)))
        )
        == STAMP
    )
    assert file_extraction_result_marker(None) is None
