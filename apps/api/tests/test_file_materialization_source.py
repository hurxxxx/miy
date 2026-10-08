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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import materialization_source as materialization
from miy_api.domains.files.artifact_contract import (
    FileArtifactChecksumMismatch,
    FileArtifactInvalid,
    FileArtifactNotReady,
    MAX_FILES_RAG_EXTRACTED_CHARS,
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


def test_ready_pair_uses_same_bounded_snapshot_and_exact_event(source_db):
    state = source_db
    result = read(state)
    assert result.keyword_document["body"] == result.rag_projection.text_content == TEXT
    assert (
        result.keyword_document["metadata"]["extracted_at"]
        == result.rag_projection.metadata["extracted_at"]
    )
    assert (
        result.rag_projection.retrieval_partition_id
        == result.keyword_document["retrieval_partition_id"]
        == PARTITION
    )
    assert (
        result.rag_projection.projection_version
        == result.keyword_document["projection_version"]
        == 1
    )
    assert result.witness.source_event_id == SOURCE_ID
    assert result.witness.source_revision == 1
    assert result.witness.projection_event == state.ref
    assert result.rag_projection.owner_label == "Synthetic"


@pytest.mark.parametrize("status", ["pending", "failed", "unsupported"])
def test_active_not_ready_never_returns_deletion(source_db, status):
    update(source_db, FileManagerFile, extraction_status=status)
    with refused(FileArtifactNotReady, reason="source_" + status):
        read(source_db)


@pytest.mark.parametrize("deleted", [False, True])
def test_active_missing_or_deleted_source_holds(source_db, deleted):
    if deleted:
        update(source_db, FileManagerFile, deleted_at=STAMP)
    else:
        with source_db.engine.begin() as connection:
            connection.execute(source_db.tables[FileManagerFile].delete())
    with refused(FileArtifactNotReady, reason="active_event_source_missing"):
        read(source_db)


@pytest.mark.parametrize("state", ["missing", "deleted", "unsupported"])
def test_genuine_deleted_event_allows_only_consistent_derived_delete(source_db, state):
    delete_event(source_db)
    if state == "missing":
        with source_db.engine.begin() as connection:
            connection.execute(source_db.tables[FileManagerFile].delete())
    elif state == "deleted":
        update(source_db, FileManagerFile, deleted_at=STAMP)
    else:
        update(source_db, FileManagerFile, extraction_status="unsupported")
    result = read(source_db)
    assert result.keyword_document is None
    assert result.rag_projection is None
    assert result.witness.projection_event.desired_state == "deleted"


@pytest.mark.parametrize("status", ["ready", "pending", "failed"])
def test_deleted_event_does_not_delete_inconsistent_live_source(source_db, status):
    delete_event(source_db)
    update(source_db, FileManagerFile, extraction_status=status)
    with refused(FileArtifactNotReady, reason="deleted_event_source_inconsistent"):
        read(source_db)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"retrieval_partition_id": OTHER_PARTITION}, "source_partition_mismatch"),
        ({"extraction_status": "unknown"}, "source_status_invalid"),
        ({"extraction_content_checksum": "b" * 64}, "accepted_event_checksum_mismatch"),
        ({"extracted_at": None}, "source_result_stamp_missing"),
    ],
)
def test_ready_current_identity_required(source_db, mutation, reason):
    update(source_db, FileManagerFile, **mutation)
    with refused(
        (FileArtifactInvalid, FileArtifactNotReady, FileArtifactChecksumMismatch), reason=reason
    ):
        read(source_db)


def test_whole_artifact_bounds_preserved(source_db):
    update(source_db, FileManagerFile, extraction_text="x" * (MAX_FILES_RAG_EXTRACTED_CHARS + 1))
    with pytest.raises(FileArtifactInvalid):
        read(source_db)


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


def test_same_sha_new_output_is_admitted_only_as_latest_accepted_core_event(source_db):
    state = source_db
    new_text = "Second valid canonical result for the same raw input checksum."
    update(
        state,
        FileManagerFile,
        extraction_text=new_text,
        extracted_at=STAMP + timedelta(seconds=1),
        extraction_blocks=[
            EvidenceBlock(
                document_id=state.ref.resource_id,
                block_id="synthetic-file:text:2",
                locator_kind="document",
                locator_label="Document",
                section_path="Body",
                block_kind="text",
                text=new_text,
            ).to_dict()
        ],
    )
    source = {
        "event_id": NEW_SOURCE_ID,
        "resource_type": state.ref.resource_type,
        "resource_id": state.ref.resource_id,
        "source_revision": 2,
        "payload_digest": "2" * 64,
    }
    fields = {
        name: getattr(state.ref, name)
        for name in (
            "resource_type",
            "resource_id",
            "retrieval_partition_id",
            "desired_state",
            "content_checksum",
            "visibility_checksum",
            "change_kind",
        )
    }
    with state.engine.begin() as connection:
        connection.execute(state.tables[OfficialProjectionOutbox].insert(), source)
        connection.execute(
            state.tables[OfficialProjectionReceipt].insert(),
            {
                **source,
                "status": "accepted",
                "core_event_sequence": 2,
            },
        )
        connection.execute(
            state.tables[RetrievalProjectionEvent].insert(),
            {
                **fields,
                "event_sequence": 2,
                "projection_version": 2,
            },
        )
    update(state, RetrievalProjectionHead, projection_version=2)
    state.ref = replace(state.ref, event_sequence=2, projection_version=2)
    result = read(state)
    assert result.witness.source_event_id == NEW_SOURCE_ID
    assert result.witness.source_revision == 2
    assert result.keyword_document["body"] == result.rag_projection.text_content == new_text
    assert (
        result.rag_projection.metadata["extracted_at"]
        != STAMP.isoformat(timespec="microseconds") + "+00:00"
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"payload_digest": "2" * 64}, "source_receipt_mismatch"),
        ({"source_revision": 2}, "source_receipt_mismatch"),
        ({"resource_id": "other"}, "source_receipt_mismatch"),
        (
            {"status": "superseded", "core_event_sequence": None},
            "source_tip_not_accepted_for_event",
        ),
        ({"core_event_sequence": 2}, "source_tip_not_accepted_for_event"),
        ({"status": "unknown"}, "source_receipt_invalid"),
    ],
)
def test_receipt_must_correlate_exact_latest_tip_and_event(source_db, mutation, reason):
    update(source_db, OfficialProjectionReceipt, **mutation)
    with refused((FileArtifactInvalid, FileArtifactNotReady), reason=reason):
        read(source_db)


@pytest.mark.parametrize("missing", ["tip", "receipt"])
def test_no_tip_or_receipt_holds_legacy_or_unaccepted_output(source_db, missing):
    model = OfficialProjectionOutbox if missing == "tip" else OfficialProjectionReceipt
    with source_db.engine.begin() as connection:
        connection.execute(source_db.tables[model].delete())
    with refused(
        FileArtifactNotReady,
        reason="source_tip_missing" if missing == "tip" else "source_tip_unaccepted",
    ):
        read(source_db)


def test_core_head_checksum_conflict_refused_before_source_snapshot(source_db):
    update(source_db, RetrievalProjectionHead, content_checksum="b" * 64)
    source_db.statements.clear()
    with refused(FileArtifactNotReady, reason="event_superseded"):
        read(source_db)
    assert not any("FROM file_manager_files" in sql for sql in source_db.statements)


def test_fresh_scalar_snapshot_ignores_stale_orm_and_never_autoflushes(source_db, monkeypatch):
    state = source_db
    old = state.db.get(FileManagerFile, state.ref.resource_id)
    old.filename = "Uncommitted caller name.txt"
    update(state, FileManagerFile, filename="Actual database name.txt")
    monkeypatch.setattr(
        state.db, "flush", lambda *_a, **_k: pytest.fail("reader flushed caller data")
    )
    monkeypatch.setattr(
        state.db, "commit", lambda *_a, **_k: pytest.fail("reader committed caller data")
    )
    result = read(state)
    assert (
        result.keyword_document["title"]
        == result.rag_projection.title
        == "Actual database name.txt"
    )
    assert old.filename == "Uncommitted caller name.txt"
    assert old in state.db.dirty


def test_fresh_snapshot_queries_only_explicit_safe_columns(source_db):
    read(source_db)
    source_sql = [sql for sql in source_db.statements if "FROM file_manager_files" in sql]
    assert len(source_sql) == 2
    artifact_sql = source_sql[0]
    for column in (
        "extraction_text",
        "extraction_blocks",
        "extraction_metadata",
        "display_name",
        "full_name",
        "source_kind",
    ):
        assert column in artifact_sql
    for column in (
        "storage_key",
        "extraction_error_code",
        "password_hash",
        "email",
        "login_id",
        "source_uri",
        "raw_metadata",
        "external_id",
        "source_id_sha256",
    ):
        assert column not in artifact_sql
    for sql in source_db.statements:
        assert sql.lstrip().upper().startswith("SELECT")
        assert "FOR UPDATE" not in sql and "FOR SHARE" not in sql
    transport_sql = next(
        sql for sql in source_db.statements if "FROM official_projection_outbox" in sql
    )
    assert ".payload," not in transport_sql
    assert "producer_" not in transport_sql
    assert "accepted_at" not in transport_sql


@pytest.mark.parametrize("mutation", ["stamp", "tip"])
def test_mutation_during_build_is_rechecked_before_return(source_db, monkeypatch, mutation):
    state = source_db
    original = materialization.build_file_rag_projection

    def builder(**kwargs):
        result = original(**kwargs)
        if mutation == "stamp":
            update(state, FileManagerFile, extracted_at=STAMP + timedelta(seconds=1))
        else:
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
        return result

    monkeypatch.setattr(materialization, "build_file_rag_projection", builder)
    with refused(FileArtifactNotReady, reason="source_result_changed|source_tip_unaccepted"):
        read(state)


def test_final_recheck_after_wait_rejects_changed_result_identity(source_db):
    state = source_db
    result = read(state)
    update(state, FileManagerFile, extracted_at=STAMP + timedelta(seconds=1))
    with prepared_core_file_projection(state.db, projection_event=state.ref):
        with refused(FileArtifactNotReady, reason="source_result_changed"):
            materialization.require_unchanged_file_materialization(state.db, materialization=result)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"retrieval_partition_id": OTHER_PARTITION}, "source_corpus_binding_mismatch"),
        ({"access_scope_kind": "personal"}, "source_corpus_binding_mismatch"),
        ({"id": "different-corpus"}, "source_corpus_binding_mismatch"),
    ],
)
def test_external_corpus_binding_required(source_db, mutation, reason):
    state = source_db
    with state.engine.begin() as connection:
        connection.execute(
            state.tables[FileManagerCorpus].insert(),
            {
                "id": "corpus",
                "access_scope_kind": "company",
                "retrieval_partition_id": PARTITION,
            },
        )
    update(state, FileManagerFile, corpus_id="corpus")
    update(state, FileManagerCorpus, **mutation)
    with refused(FileArtifactInvalid, reason=reason):
        read(state)


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"corpus_id": "other"}, "external_corpus_binding_mismatch"),
        ({"content_checksum": "b" * 64}, "external_input_checksum_mismatch"),
    ],
)
def test_safe_external_metadata_binding_and_checksum_required(source_db, mutation, reason):
    state = source_db
    with state.engine.begin() as connection:
        connection.execute(
            state.tables[FileManagerCorpus].insert(),
            {
                "id": "corpus",
                "access_scope_kind": "company",
                "retrieval_partition_id": PARTITION,
            },
        )
        connection.execute(
            state.tables[FileManagerFileSourceMetadata].insert(),
            {
                "file_id": state.ref.resource_id,
                "corpus_id": "corpus",
                "source_kind": "external",
                "content_checksum": CHECKSUM,
                "title": "External title",
            },
        )
    update(state, FileManagerFile, corpus_id="corpus")
    update(state, FileManagerFileSourceMetadata, **mutation)
    with refused((FileArtifactInvalid, FileArtifactChecksumMismatch), reason=reason):
        read(state)


def test_safe_external_pair_uses_same_bound_corpus_and_public_fields(source_db):
    state = source_db
    with state.engine.begin() as connection:
        connection.execute(
            state.tables[FileManagerCorpus].insert(),
            {
                "id": "corpus",
                "access_scope_kind": "company",
                "retrieval_partition_id": PARTITION,
            },
        )
        connection.execute(
            state.tables[FileManagerFileSourceMetadata].insert(),
            {
                "file_id": state.ref.resource_id,
                "corpus_id": "corpus",
                "source_kind": "external",
                "content_checksum": CHECKSUM,
                "title": "External title",
                "author": "External author",
                "source_updated_at": STAMP,
                "raw_metadata": {"private": "must not load"},
                "source_uri": "private://must-not-load",
            },
        )
    update(state, FileManagerFile, corpus_id="corpus")
    result = read(state)
    assert result.keyword_document["title"] == result.rag_projection.title == "External title"
    assert (
        result.keyword_document["metadata"]["author"]
        == result.rag_projection.metadata["author"]
        == "External author"
    )
    assert result.rag_projection.visibility_refs == ["company_public"]
    assert "raw_metadata" not in result.keyword_document["metadata"]
    assert "source_uri" not in result.rag_projection.metadata


def test_unprepared_context_never_reads_source(source_db):
    state = source_db
    state.statements.clear()
    with refused(FileArtifactInvalid, reason="file_projection_context_required"):
        materialization.load_prepared_file_materialization(state.db, projection_event=state.ref)
    assert not state.statements


def test_core_identity_guard_is_postgresql_only_without_explicit_test_stub():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    # This fixture does not stub the actual fixed guard.
    with Session(engine) as db:
        with refused(FileArtifactInvalid, reason="materialization_requires_read_committed"):
            materialization._require_core_identity(db)
    engine.dispose()


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


@pytest.mark.parametrize("position", range(9))
def test_fixed_core_identity_guard_denies_each_unsafe_catalog_flag(monkeypatch, position):
    # Real unbound Session with synthetic catalog result; not SQL role proof.
    db = Session()
    flags = [True, False, False, False, False, False, False, False, False]
    flags[position] = not flags[position]
    statements = []
    controlled_pg_transaction(monkeypatch, db)
    monkeypatch.setattr(
        db,
        "execute",
        lambda statement: (
            statements.append(str(statement)) or SimpleNamespace(one_or_none=lambda: tuple(flags))
        ),
    )
    with refused(FileArtifactInvalid, reason="materialization_core_identity_forbidden"):
        materialization._require_core_identity(db)
    assert len(statements) == 2
    assert "pg_catalog.set_config" in statements[0]
    assert "p.role_oid=r.oid::bigint OR p.role_name=session_user" in statements[1]
    db.close()


def test_safe_core_identity_pins_local_namespace_without_source_mutation(monkeypatch):
    db = Session()
    controlled_pg_transaction(monkeypatch, db)
    statements = []
    monkeypatch.setattr(
        db,
        "execute",
        lambda statement: (
            statements.append(str(statement))
            or SimpleNamespace(
                one_or_none=lambda: (True, False, False, False, False, False, False, False, False)
            )
        ),
    )
    monkeypatch.setattr(db, "flush", lambda *_a, **_k: pytest.fail("identity guard flushed"))
    materialization._require_core_identity(db)
    assert len(statements) == 2
    assert statements[0] == (
        "SELECT pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true)"
    )
    assert "pg_catalog.pg_roles" in statements[1]
    db.close()


def test_local_namespace_failure_stops_content_and_suppresses_sql_details(monkeypatch):
    db = Session()
    controlled_pg_transaction(monkeypatch, db)
    statements = []

    def execute(statement):
        statements.append(str(statement))
        raise SQLAlchemyError("synthetic sensitive connection/SQL details")

    monkeypatch.setattr(db, "execute", execute)
    with pytest.raises(FileArtifactInvalid) as error:
        materialization._require_core_identity(db)
    assert error.value.reason == "materialization_namespace_unavailable"
    assert error.value.__cause__ is None
    assert "sensitive" not in str(error.value)
    assert len(statements) == 1
    assert not any("file_manager" in statement for statement in statements)
    db.close()


def test_core_identity_denial_precedes_core_and_source_content_queries(source_db, monkeypatch):
    state = source_db

    def deny(_db):
        raise FileArtifactInvalid("materialization_core_identity_forbidden")

    monkeypatch.setattr(materialization, "_require_core_identity", deny)
    state.statements.clear()
    with refused(FileArtifactInvalid, reason="materialization_core_identity_forbidden"):
        read(state)
    assert not state.statements


@pytest.mark.parametrize(
    "autocommit,isolation", [(False, "repeatable read"), (True, "read committed")]
)
def test_core_identity_requires_retained_read_committed_transaction(
    monkeypatch, autocommit, isolation
):
    """Controlled real Session seams; genuine PostgreSQL authority proof follows separately."""
    db = Session()
    controlled_pg_transaction(monkeypatch, db, autocommit=autocommit, isolation=isolation)
    statements = []
    monkeypatch.setattr(
        db,
        "execute",
        lambda statement: (
            statements.append(str(statement))
            or SimpleNamespace(
                one_or_none=lambda: (True, False, False, False, False, False, False, False, False)
            )
        ),
    )
    with refused(FileArtifactInvalid, reason="materialization_requires_read_committed"):
        materialization._require_core_identity(db)
    assert not statements
    db.close()
