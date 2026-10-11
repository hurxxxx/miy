"""Real owned SQLite reads with synthetic ledger; PostgreSQL authority is separate.

Only the fixed PostgreSQL actual-role guard is explicitly stubbed in these
behaviour tests. No producer guards, real app ACL, grants or lock claim is made.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import materialization_source as materialization
from miy_api.domains.files.artifact_contract import (
    FileArtifactNotReady,
)
from miy_api.domains.files.core_projection import prepared_core_file_projection
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.retrieval.models import RetrievalProjectionEvent, RetrievalProjectionHead
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef

PARTITION = "826901c6-58b1-4687-b7e0-d7844a337a01"
OTHER_PARTITION = "826901c6-58b1-4687-b7e0-d7844a337a02"
SOURCE_ID = "2c5a3f3e-8868-4d2a-97b2-d80662f0d4a5"
NEW_SOURCE_ID = "2c5a3f3e-8868-4d2a-97b2-d80662f0d4a6"
CHECKSUM = "a" * 64
TEXT = "Canonical Source body admitted for this exact accepted output."
STAMP = datetime(2026, 10, 7, 12, 0, 0, 2)


@pytest.fixture
def source_db(tmp_path, monkeypatch):
    import_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'materialization.sqlite'}")
    metadata = MetaData()
    tables = {}
    for model in (
        User,
        FileManagerCorpus,
        FileManagerFileSourceMetadata,
        FileManagerFile,
        RetrievalProjectionEvent,
        RetrievalProjectionHead,
        OfficialProjectionOutbox,
        OfficialProjectionReceipt,
    ):
        table = Table(
            model.__tablename__,
            metadata,
            *(
                Column(column.name, column.type, primary_key=column.primary_key)
                for column in model.__table__.columns
            ),
        )
        table.create(engine)
        tables[model] = table
    fields = {
        "resource_type": "file_manager_file",
        "resource_id": "synthetic-file",
        "projection_version": 1,
        "retrieval_partition_id": PARTITION,
        "desired_state": "active",
        "content_checksum": CHECKSUM,
        "visibility_checksum": None,
    }
    source = {
        "event_id": SOURCE_ID,
        "resource_type": fields["resource_type"],
        "resource_id": fields["resource_id"],
        "source_revision": 1,
        "payload_digest": "1" * 64,
    }
    with engine.begin() as connection:
        connection.execute(
            tables[User].insert(),
            {
                "id": "synthetic-owner",
                "display_name": "Synthetic",
                "full_name": "Owner",
            },
        )
        connection.execute(
            tables[FileManagerFile].insert(),
            {
                "id": fields["resource_id"],
                "owner_id": "synthetic-owner",
                "filename": "Plan.txt",
                "content_type": "text/plain",
                "size_bytes": 64,
                "storage_key": "private-input",
                "visibility": "company",
                "retrieval_partition_id": PARTITION,
                "extraction_status": "ready",
                "extraction_content_checksum": CHECKSUM,
                "extraction_text": TEXT,
                "extraction_blocks": [
                    EvidenceBlock(
                        document_id=fields["resource_id"],
                        block_id="synthetic-file:text:1",
                        locator_kind="document",
                        locator_label="Document",
                        section_path="Body",
                        block_kind="text",
                        text=TEXT,
                    ).to_dict()
                ],
                "extraction_metadata": {"parser": "plain_text"},
                "extracted_at": STAMP,
                "updated_at": STAMP,
            },
        )
        connection.execute(tables[RetrievalProjectionHead].insert(), fields)
        connection.execute(
            tables[RetrievalProjectionEvent].insert(),
            {
                **fields,
                "event_sequence": 1,
                "change_kind": "content",
            },
        )
        connection.execute(tables[OfficialProjectionOutbox].insert(), source)
        connection.execute(
            tables[OfficialProjectionReceipt].insert(),
            {
                **source,
                "status": "accepted",
                "core_event_sequence": 1,
            },
        )
    statements = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _c, _cur, statement, *_rest: statements.append(statement),
    )
    # Explicit synthetic guard, never a substitute for actual restricted PG.
    monkeypatch.setattr(materialization, "_require_core_identity", lambda _db: None)
    db = Session(engine)
    state = SimpleNamespace(
        db=db,
        engine=engine,
        tables=tables,
        statements=statements,
        ref=ProjectionEventRef(event_sequence=1, change_kind="content", **fields),
    )
    try:
        yield state
    finally:
        db.close()
        engine.dispose()


@contextmanager
def refused(errors, *, reason):
    with pytest.raises(errors) as caught:
        yield
    assert caught.value.reason in reason.split("|")


def update(state, model, **values):
    with state.engine.begin() as connection:
        connection.execute(state.tables[model].update().values(**values))


def read(state):
    with prepared_core_file_projection(state.db, projection_event=state.ref):
        return materialization.load_prepared_file_materialization(
            state.db, projection_event=state.ref
        )


def delete_event(state):
    state.ref = replace(
        state.ref, change_kind="delete", desired_state="deleted", content_checksum=None
    )
    update(
        state,
        RetrievalProjectionEvent,
        change_kind="delete",
        desired_state="deleted",
        content_checksum=None,
    )
    update(state, RetrievalProjectionHead, desired_state="deleted", content_checksum=None)


def test_unaccepted_same_sha_new_output_cannot_be_old_core_output(source_db):
    state = source_db
    update(
        state,
        FileManagerFile,
        extraction_text="A new output from the same input SHA.",
        extracted_at=STAMP + timedelta(seconds=1),
    )
    with state.engine.begin() as connection:
        connection.execute(
            state.tables[OfficialProjectionOutbox].insert(),
            {
                "event_id": NEW_SOURCE_ID,
                "resource_type": state.ref.resource_type,
                "resource_id": state.ref.resource_id,
                "source_revision": 2,
                "payload_digest": "2" * 64,
            },
        )
    state.statements.clear()
    with refused(FileArtifactNotReady, reason="source_tip_unaccepted"):
        read(state)
    assert not any("FROM file_manager_files" in sql for sql in state.statements)


def test_final_recheck_after_wait_rejects_changed_result_identity(source_db):
    state = source_db
    result = read(state)
    update(state, FileManagerFile, extracted_at=STAMP + timedelta(seconds=1))
    with prepared_core_file_projection(state.db, projection_event=state.ref):
        with refused(FileArtifactNotReady, reason="source_result_changed"):
            materialization.require_unchanged_file_materialization(state.db, materialization=result)


def controlled_pg_transaction(monkeypatch, db, *, autocommit=False, isolation="read committed"):
    monkeypatch.setattr(
        db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    monkeypatch.setattr(
        db,
        "connection",
        lambda: SimpleNamespace(
            connection=SimpleNamespace(driver_connection=SimpleNamespace(autocommit=autocommit))
        ),
    )
    monkeypatch.setattr(db, "scalar", lambda _statement: isolation)
