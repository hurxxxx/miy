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
from miy_api.domains.files.rag_projection import (
    hydrate_file_rag_hits_from_source,
)
from miy_api.domains.files.search_projection import (
    hydrate_file_search_rows_from_source,
)
from miy_api.domains.rag.contracts import RagProjection, RagVectorSearchHit

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


@pytest.mark.parametrize("kind", ["keyword"])
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
