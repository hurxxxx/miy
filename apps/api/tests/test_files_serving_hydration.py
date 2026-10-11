"""Synthetic hydration behavior; actual column SQL is tested separately."""

from datetime import datetime

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.artifact_contract import FileExtractionArtifact
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files.rag_projection import (
    build_file_rag_projection,
    hydrate_file_rag_hits_from_source,
)
from miy_api.domains.files.search_projection import (
    build_file_search_document,
    hydrate_file_search_rows_from_source,
)
from miy_api.domains.rag import application
from miy_api.domains.rag.contracts import RagProjection, RagVectorSearchHit
from miy_api.domains.rag.query_projection import to_query_hit

PARTITION = "a3b6638a-7547-45f8-81f2-973bfa6080d6"
CHECKSUM = "a" * 64
STAMP = "2026-10-07T00:00:00.123456+00:00"


@pytest.fixture
def source(monkeypatch):
    import_all_models()
    file = FileManagerFile(
        id="file-1",
        owner_id="user-1",
        filename="Current.txt",
        folder_id="current-folder",
        content_type="text/plain",
        storage_key="synthetic",
        size_bytes=16,
        visibility="company",
        retrieval_partition_id=PARTITION,
        extraction_status="ready",
        extraction_content_checksum=CHECKSUM,
        extracted_at=datetime(2026, 10, 7, microsecond=123456),
        updated_at=datetime(2026, 10, 7),
    )
    file.corpus = None
    file.source_metadata = None
    file.owner = None
    db = Session()

    def execute(statement):
        assert statement.is_select and db.autoflush is False
        assert len(statement.selected_columns) == 6
        return [
            (
                file.id,
                file.deleted_at,
                file.extraction_status,
                file.extraction_content_checksum,
                file.retrieval_partition_id,
                file.extracted_at,
            )
        ]

    def scalars(statement):
        assert db.autoflush is False
        assert statement.get_execution_options()["populate_existing"] is True
        return [file]

    monkeypatch.setattr(db, "execute", execute)
    monkeypatch.setattr(db, "scalars", scalars)
    monkeypatch.setattr(db, "flush", lambda *_a: pytest.fail("hydration flushed Source"))
    try:
        yield db, file
    finally:
        db.close()


def candidate_hit(*, checksum=CHECKSUM, partition=PARTITION):
    return RagVectorSearchHit(
        chunk_id="file-1:1",
        text="synthetic indexed bytes",
        score=1.0,
        metadata={
            "content_checksum": "collision",
            "retrieval_partition_id": "collision",
            "locator": "paragraph 1",
            "extracted_at": STAMP,
        },
        projection=RagProjection(
            resource_type="file_manager_file",
            resource_id="file-1",
            source_kind="files",
            retrieval_partition_id=partition,
            projection_version=1 if partition else None,
            metadata={"content_checksum": checksum, "extracted_at": STAMP},
        ),
    )


def candidate_row(*, checksum=CHECKSUM, partition=PARTITION):
    return {
        "entity_type": "file",
        "entity_id": "file-1",
        "body": "synthetic indexed bytes",
        "retrieval_partition_id": partition,
        "metadata": {"content_checksum": checksum, "extracted_at": STAMP},
    }


@pytest.mark.parametrize("empty", [True, False])
def test_non_file_keyword_and_vector_candidates_need_no_database(empty):
    rows = [] if empty else [{"entity_type": "doc_page", "entity_id": "synthetic-doc"}]
    hits = (
        []
        if empty
        else [
            RagVectorSearchHit(
                chunk_id="synthetic-doc:1",
                text="Synthetic document",
                score=1.0,
                projection=RagProjection(
                    resource_type="doc_page",
                    resource_id="synthetic-doc",
                    source_kind="docs",
                ),
            )
        ]
    )
    assert hydrate_file_search_rows_from_source(None, rows=rows) == rows
    assert hydrate_file_rag_hits_from_source(None, hits=hits) == hits


@pytest.mark.parametrize("file_id", [None, ""])
def test_no_known_file_ids_drops_invalid_files_without_touching_database(file_id):
    doc = {"entity_type": "doc_page", "entity_id": "synthetic-doc"}
    assert hydrate_file_search_rows_from_source(
        None, rows=[{"entity_type": "file", "entity_id": file_id}, doc]
    ) == [doc]


@pytest.mark.parametrize("partition", [PARTITION, None])
def test_ready_envelope_survives_keyword_and_chunk_metadata_conversion(source, partition):
    db, file = source
    file.retrieval_partition_id = partition
    row = candidate_row(partition=partition)
    keyword = hydrate_file_search_rows_from_source(db, rows=[row])[0]
    assert keyword["body"] == row["body"]
    assert keyword["metadata"]["content_checksum"] == CHECKSUM
    assert keyword["metadata"]["retrieval_partition_id"] == partition
    assert keyword["retrieval_partition_id"] == partition
    original = candidate_hit(partition=partition)
    hit = hydrate_file_rag_hits_from_source(db, hits=[original])[0]
    assert hit.text == original.text
    assert hit.metadata == {
        "content_checksum": CHECKSUM,
        "retrieval_partition_id": partition,
        "locator": "paragraph 1",
        "extracted_at": STAMP,
    }
    assert original.metadata["content_checksum"] == "collision"
    assert to_query_hit(hit).metadata["content_checksum"] == CHECKSUM
    assert to_query_hit(hit).metadata["retrieval_partition_id"] == partition
    assert hit.projection.metadata["content_checksum"] == CHECKSUM
    assert hit.projection.retrieval_partition_id == partition


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "failed",
        "unsupported",
        "deleted",
        "checksum",
        "partition",
        "missing_partition",
        "same_input_new_result",
        "missing_result_marker",
    ],
)
def test_keyword_and_vector_drop_stale_content_before_routing_rewrite(source, change):
    db, file = source
    if change in {"pending", "failed", "unsupported"}:
        file.extraction_status = change
    elif change == "deleted":
        file.deleted_at = datetime(2026, 10, 7)
    elif change == "checksum":
        file.extraction_content_checksum = "b" * 64
    elif change == "partition":
        file.retrieval_partition_id = "31a974ba-7fe4-4c35-9d98-ea3bb9b82d12"
    elif change == "same_input_new_result":
        file.extracted_at = datetime(2026, 10, 7, microsecond=123457)
    elif change == "missing_result_marker":
        file.extracted_at = None
    else:
        file.retrieval_partition_id = None
    assert hydrate_file_search_rows_from_source(db, rows=[candidate_row()]) == []
    assert hydrate_file_rag_hits_from_source(db, hits=[candidate_hit()]) == []


def test_missing_checksum_and_non_file_behavior(source):
    db, _file = source
    assert hydrate_file_search_rows_from_source(db, rows=[candidate_row(checksum=None)]) == []
    assert hydrate_file_rag_hits_from_source(db, hits=[candidate_hit(checksum=None)]) == []
    row = {"entity_type": "doc", "entity_id": "doc-1"}
    hit = candidate_hit().model_copy(
        update={
            "projection": RagProjection(
                resource_type="doc", resource_id="doc-1", source_kind="docs"
            )
        }
    )
    assert hydrate_file_search_rows_from_source(db, rows=[row]) == [row]
    assert hydrate_file_rag_hits_from_source(db, hits=[hit]) == [hit]


@pytest.mark.parametrize("partitioned", [False, True])
def test_files_application_installs_hydrator_for_legacy_and_partitioned(source, partitioned):
    db, file = source
    file.extraction_status = "pending"
    hydrate = application._build_files_hit_hydrator(
        db, source_kinds=["files"], partitioned_generation=partitioned
    )
    assert hydrate is not None and hydrate([candidate_hit()]) == []
    assert (
        application._build_files_hit_hydrator(
            db, source_kinds=["docs"], partitioned_generation=partitioned
        )
        is None
    )


def test_source_builders_emit_actual_result_stamp_after_artifact_metadata(source):
    _db, file = source
    file.extraction_text = "Synthetic canonical text"
    keyword = build_file_search_document(file=file)
    block = EvidenceBlock(
        "file-1", "file-1:text:1", "document", "Document", "Body", "text", file.extraction_text
    )
    artifact = FileExtractionArtifact(
        CHECKSUM, file.extraction_text, [block], {"extracted_at": "untrusted artifact marker"}
    )
    projection = build_file_rag_projection(file=file, artifact=artifact)
    assert keyword["metadata"]["extracted_at"] == STAMP
    assert projection.metadata["extracted_at"] == STAMP
    file.extracted_at = None
    assert build_file_search_document(file=file)["metadata"]["extracted_at"] is None
    assert build_file_rag_projection(file=file, artifact=artifact).metadata["extracted_at"] is None


@pytest.mark.parametrize("kind", ["keyword", "vector"])
def test_result_change_during_real_routing_query_is_rechecked_before_response(
    tmp_path, monkeypatch, kind
):
    import_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'routing.sqlite'}")
    metadata = MetaData()

    def read_table(model, names, primary):
        return Table(
            model.__tablename__,
            metadata,
            *[
                Column(name, model.__table__.c[name].type, primary_key=name == primary)
                for name in names
            ],
        )

    files = read_table(
        FileManagerFile,
        [
            "id",
            "owner_id",
            "filename",
            "folder_id",
            "corpus_id",
            "content_type",
            "size_bytes",
            "visibility",
            "updated_at",
            "deleted_at",
            "extraction_status",
            "extraction_content_checksum",
            "retrieval_partition_id",
            "extracted_at",
        ],
        "id",
    )
    corpora = read_table(FileManagerCorpus, ["id", "access_scope_kind"], "id")
    source_metadata = read_table(
        FileManagerFileSourceMetadata,
        [
            "file_id",
            "source_kind",
            "title",
            "author",
            "authored_at",
            "department",
            "document_type",
            "source_updated_at",
            "content_checksum",
        ],
        "file_id",
    )
    # Exact model column types on local read-seam tables; not platform migration proof.
    for table in (files, corpora, source_metadata):
        table.create(engine)
    extracted = datetime(2026, 10, 7, microsecond=123456)
    with engine.begin() as connection:
        connection.execute(
            files.insert(),
            {
                "id": "file-1",
                "owner_id": "user-1",
                "filename": "Current.txt",
                "content_type": "text/plain",
                "size_bytes": 16,
                "visibility": "company",
                "updated_at": extracted,
                "extraction_status": "ready",
                "extraction_content_checksum": CHECKSUM,
                "retrieval_partition_id": PARTITION,
                "extracted_at": extracted,
            },
        )
    statements = []
    event.listen(engine, "before_cursor_execute", lambda _c, _u, s, *_a: statements.append(s))
    try:
        with Session(engine) as db:
            real_scalars = db.scalars
            routing_queries = []

            def routing_then_mutation(statement):
                assert db.autoflush is False
                rows = list(real_scalars(statement))
                routing_queries.append(statement)
                # Same raw bytes/partition, distinct extraction output; mutate
                # only after the actual routing rows have been fetched.
                with engine.begin() as connection:
                    connection.execute(
                        files.update().values(
                            extracted_at=datetime(2026, 10, 7, microsecond=123457)
                        )
                    )
                return rows

            monkeypatch.setattr(db, "scalars", routing_then_mutation)
            if kind == "keyword":
                assert hydrate_file_search_rows_from_source(db, rows=[candidate_row()]) == []
            else:
                assert hydrate_file_rag_hits_from_source(db, hits=[candidate_hit()]) == []
            assert len(routing_queries) == 1
            select_statements = [s for s in statements if s.lstrip().startswith("SELECT")]
            assert len(select_statements) == 2
            assert "JOIN" in select_statements[0] and "JOIN" not in select_statements[1]
            assert all(
                not any(
                    name in s
                    for name in (
                        "storage_key",
                        "extraction_text",
                        "raw_metadata",
                        "source_uri",
                        "external_id",
                    )
                )
                for s in select_statements
            )
    finally:
        engine.dispose()
