"""Current identity uses a real owned SQLite query, never cached ORM authority."""

from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine

from miy_api.core.model_registry import import_all_models

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
