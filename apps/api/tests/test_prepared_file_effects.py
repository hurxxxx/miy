"""Owned SQLite behavior; PostgreSQL identity/cap/header guards are simulated.

Real Source/Core/operation/job rows and final Source rereads remain exercised.
This is not PostgreSQL grants, triggers, transaction-lock or provider proof.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import TextClause

from miy_api.core.model_registry import import_all_models
from miy_api.domains.auth.models import User
from miy_api.domains.document_processing import EvidenceBlock
from miy_api.domains.files import materialization_source
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.official_apps.file_materialization_effect_models import (
    FileMaterializationOperation,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.rag.contracts import RagSyncOperation, RagSyncResult
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval import prepared_file_effects as effects
from miy_api.domains.retrieval import prepared_file_materializer as composition
from miy_api.domains.retrieval.files_generation_runner import FilesGenerationPairSpec
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionGeneration,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.models import SearchIndexJob

PARTITION = "826901c6-58b1-4687-b7e0-d7844a337a01"
SOURCE_ID = "2c5a3f3e-8868-4d2a-97b2-d80662f0d4a5"
NEXT_SOURCE_ID = "2c5a3f3e-8868-4d2a-97b2-d80662f0d4a6"
OPERATION_ID = "c7e25cb2-818e-4e03-822c-d7c3b5586001"
KEYWORD_ID = "e35818c1-c5c4-4896-9aa0-c53a22bf8001"
VECTOR_ID = "e35818c1-c5c4-4896-9aa0-c53a22bf8002"
CHECKSUM = "a" * 64
HEADER_DIGEST = "b" * 64
STAMP = datetime(2026, 10, 7, 12, 0, 0, 2)
TEXT = "Synthetic canonical output for the exact accepted Source result."

READ_MODELS = (
    User,
    FileManagerCorpus,
    FileManagerFileSourceMetadata,
    FileManagerFile,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
    RetrievalPartition,
    RetrievalProjectionGeneration,
    SearchIndexJob,
    RagSyncJob,
    FileMaterializationOperation,
)


class ControlledCoreSession(Session):
    """Simulate only SQL-owned stamp fields and LOCAL timeout statements."""

    def __init__(self, state, **kwargs):
        super().__init__(state.engine, **kwargs)
        self.state = state

    def execute(self, statement, *args, **kwargs):
        if isinstance(statement, TextClause) and str(statement).startswith("SET LOCAL"):
            self.state.simulated_pg.append(str(statement))
            return None
        if getattr(statement, "table", None) is FileMaterializationOperation.__table__:
            if isinstance(statement, Insert):
                # Production SQL stamps these fields. This simulator does not
                # claim their digest algorithm or authority was verified.
                statement = statement.values(
                    issuer_role_oid=47001,
                    issuer_role_name="synthetic_core",
                    armed_xact_id="101",
                    header_digest=HEADER_DIGEST,
                    state="armed",
                    created_at=STAMP,
                    completed_at=None,
                )
            elif isinstance(statement, Update):
                statement = statement.values(completed_at=STAMP + timedelta(seconds=1))
        return super().execute(statement, *args, **kwargs)

    def commit(self):
        self.state.commit_calls += 1
        timing = self.state.commit_faults.get(self.state.commit_calls)
        if timing == "before":
            raise self.state.commit_error("synthetic COMMIT response failure")
        super().commit()
        if timing == "after":
            raise self.state.commit_error("synthetic COMMIT response failure")

    def rollback(self):
        if self.state.rollback_failure:
            raise self.state.rollback_error("synthetic cleanup failure")
        return super().rollback()

    def close(self):
        super().close()
        if self.state.close_failure:
            raise self.state.close_error("synthetic cleanup failure")


@pytest.fixture
def effect_state(tmp_path, monkeypatch):
    import_all_models()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'effects.sqlite'}")
    tables = {}
    metadata = MetaData()
    for model in READ_MODELS:
        if model is FileMaterializationOperation:
            # Keep the actual operation checks and unique indexes. Source/Core
            # table clones intentionally do not simulate PostgreSQL guards.
            model.__table__.create(engine)
            tables[model] = model.__table__
        else:
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
    ref = ProjectionEventRef(
        event_sequence=1,
        resource_type="file_manager_file",
        resource_id="synthetic-file",
        projection_version=1,
        retrieval_partition_id=PARTITION,
        change_kind="content",
        desired_state="active",
        content_checksum=CHECKSUM,
        visibility_checksum=None,
    )
    source = {
        "event_id": SOURCE_ID,
        "resource_type": ref.resource_type,
        "resource_id": ref.resource_id,
        "source_revision": 1,
        "payload_digest": "1" * 64,
    }
    with engine.begin() as db:
        db.execute(tables[User].insert(), {"id": "synthetic-owner", "display_name": "Owner"})
        db.execute(
            tables[FileManagerFile].insert(),
            {
                "id": ref.resource_id,
                "owner_id": "synthetic-owner",
                "filename": "Plan.txt",
                "content_type": "text/plain",
                "size_bytes": 64,
                "storage_key": "synthetic-private-key",
                "visibility": "company",
                "retrieval_partition_id": PARTITION,
                "extraction_status": "ready",
                "extraction_content_checksum": CHECKSUM,
                "extraction_text": TEXT,
                "extraction_blocks": [
                    EvidenceBlock(
                        document_id=ref.resource_id,
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
        fields = {name: getattr(ref, name) for name in ref.__dataclass_fields__}
        db.execute(tables[RetrievalProjectionEvent].insert(), fields)
        db.execute(
            tables[RetrievalProjectionHead].insert(),
            {
                key: value
                for key, value in fields.items()
                if key not in {"event_sequence", "change_kind"}
            },
        )
        db.execute(tables[OfficialProjectionOutbox].insert(), source)
        db.execute(
            tables[OfficialProjectionReceipt].insert(),
            {**source, "status": "accepted", "core_event_sequence": 1},
        )
        for model, resource_name in ((SearchIndexJob, "entity_id"), (RagSyncJob, "resource_id")):
            db.execute(
                tables[model].insert(),
                {
                    "id": "synthetic-search" if model is SearchIndexJob else "synthetic-rag",
                    resource_name: ref.resource_id,
                    "resource_type": ref.resource_type,
                    "entity_type": "file" if model is SearchIndexJob else None,
                    "projection_version": 1,
                    "projection_event_sequence": 1,
                    "retrieval_partition_id": PARTITION,
                    "desired_state": "active",
                    "operation": "upsert",
                    "status": "pending",
                    "attempts": 0,
                }
                if model is SearchIndexJob
                else {
                    "id": "synthetic-rag",
                    "resource_id": ref.resource_id,
                    "resource_type": ref.resource_type,
                    "projection_version": 1,
                    "projection_event_sequence": 1,
                    "retrieval_partition_id": PARTITION,
                    "desired_state": "active",
                    "operation": "upsert",
                    "status": "pending",
                    "attempts": 0,
                },
            )
    state = SimpleNamespace(
        engine=engine,
        tables=tables,
        ref=ref,
        sql=[],
        simulated_pg=[],
        calls=[],
        admissions=0,
        caps=0,
        commit_calls=0,
        commit_faults={},
        commit_error=RuntimeError,
        rollback_failure=False,
        rollback_error=RuntimeError,
        close_failure=False,
        close_error=RuntimeError,
        sessions=[],
        callback_count=1,
        keyword_outcome="upserted",
        vector_failure=False,
        refresh_failure=False,
        after_embed=None,
        after_vector=None,
        vector_count=1,
    )
    state.pair = effects.PreparedFileGenerationPair(
        KEYWORD_ID, VECTOR_ID, "synthetic-pair", "synthetic-keyword", "synthetic-vector"
    )
    state.spec = effects.FileMaterializationEffectSpec(OPERATION_ID, ref, state.pair, 1)
    state.batch_spec = FilesGenerationPairSpec(
        state.pair.generation_key,
        state.pair.keyword_physical_name,
        "synthetic-k-alias",
        state.pair.vector_physical_name,
        "synthetic-v-alias",
    )
    event.listen(
        engine, "before_cursor_execute", lambda _c, _cur, sql, *_rest: state.sql.append(sql)
    )

    def identity(_db):
        state.admissions += 1

    def cap(_db, _spec):
        state.caps += 1

    monkeypatch.setattr(effects, "require_file_materialization_identity", identity)
    monkeypatch.setattr(materialization_source, "_require_core_identity", identity)
    monkeypatch.setattr(effects, "lock_prepared_file_materialization", cap)

    def factory():
        db = ControlledCoreSession(state)
        state.sessions.append(db)
        return db

    state.factory = factory
    state.runner = effects.PreparedFileEffectRunner(factory)
    try:
        yield state
    finally:
        for db in state.sessions:
            Session.close(db)
        engine.dispose()


def operation(state):
    with state.engine.connect() as db:
        return (
            db.execute(select(state.tables[FileMaterializationOperation])).mappings().one_or_none()
        )


def jobs(state):
    with state.engine.connect() as db:
        return tuple(
            tuple(db.execute(select(table.c.status, table.c.attempts)).one())
            for table in (state.tables[SearchIndexJob], state.tables[RagSyncJob])
        )


def mutate(state, model, **values):
    with state.engine.begin() as db:
        db.execute(state.tables[model].update().values(**values))


def new_source_tip(state):
    with state.engine.begin() as db:
        db.execute(
            state.tables[OfficialProjectionOutbox].insert(),
            {
                "event_id": NEXT_SOURCE_ID,
                "resource_type": state.ref.resource_type,
                "resource_id": state.ref.resource_id,
                "source_revision": 2,
                "payload_digest": "2" * 64,
            },
        )


def materializer(state):
    class Keyword:
        def upsert_partitioned_document(self, document):
            state.calls.append("keyword_write")
            assert document["body"] == TEXT
            return state.keyword_outcome

        def delete_partitioned_document(self, **kwargs):
            state.calls.append("keyword_delete")
            assert kwargs["resource_id"] == state.ref.resource_id
            assert kwargs["projection_version"] == state.ref.projection_version
            return "deleted"

        def refresh_partitioned_index(self):
            state.calls.append("refresh")
            if state.refresh_failure:
                raise RuntimeError("synthetic refresh ACK lost")

    class Rag:
        def sync_projection_with_fence(self, projection, *, collection, before_vector_write):
            state.calls.append("embed")
            assert projection.text_content == TEXT
            if state.after_embed:
                state.after_embed()
            for _ in range(state.callback_count):
                before_vector_write()
            state.calls.append("vector_write")
            if state.vector_failure:
                raise RuntimeError("synthetic vector ACK lost")
            if state.after_vector:
                state.after_vector()
            return RagSyncResult(
                collection=collection,
                operation=RagSyncOperation.UPSERT,
                chunk_count=state.vector_count,
            )

        def delete_projection(self, **kwargs):
            state.calls.append("vector_delete")
            assert kwargs["retrieval_partition_id"] == PARTITION
            assert kwargs["resource_id"] == state.ref.resource_id
            return RagSyncResult(
                collection=kwargs["collection"], operation=RagSyncOperation.DELETE, deleted_count=0
            )

    def keyword_factory(_target):
        state.calls.append("keyword_factory")
        return Keyword()

    def rag_factory(_target):
        state.calls.append("rag_factory")
        return Rag()

    return composition.PreparedFilesCachedProjectionMaterializer(
        session_factory=state.factory,
        settings=SimpleNamespace(),
        generation_pair=state.pair,
        partition_metadata_version=1,
        keyword_client_factory=keyword_factory,
        rag_service_factory=rag_factory,
        retain_operation_id=lambda _event, _pair: OPERATION_ID,
    )


def batch(state, instance=None, *, after=0):
    return (instance or materializer(state)).materialize_batch(
        spec=state.batch_spec, after_event_sequence=after, through_event_sequence=1, limit=10
    )


def test_known_ack_completes_exact_operation_jobs_and_refresh_before_commit(effect_state):
    state = effect_state
    result = batch(state)
    assert result.caught_up and result.keyword_succeeded == result.vector_succeeded == 1
    assert operation(state)["state"] == "complete"
    assert jobs(state) == (("succeeded", 1), ("succeeded", 1))
    assert state.calls == [
        "keyword_factory",
        "rag_factory",
        "embed",
        "keyword_write",
        "vector_write",
        "refresh",
    ]
    assert state.commit_calls == 2


@pytest.mark.parametrize("timing", ["after"])
def test_arm_ack_unknown_never_constructs_providers_or_recreates_permit(effect_state, timing):
    state = effect_state
    state.commit_faults[1] = timing
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    unknown = caught.value
    assert unknown.phase == "arm_commit" and unknown.receipt.spec == state.spec
    assert unknown.receipt.header_digest == HEADER_DIGEST
    assert state.calls == [] and jobs(state) == (("pending", 0), ("pending", 0))
    observed = state.runner.observe(
        state.spec, expected_header_digest=unknown.receipt.header_digest
    )
    assert (observed is None) == (timing == "before")
    if observed is not None:
        assert observed.state == "armed" and observed.historical
        with pytest.raises(effects.FileMaterializationEffectUnknown) as replay:
            batch(state)
        assert replay.value.phase == "historical"
    assert state.calls == []


@pytest.mark.parametrize("timing", ["after"])
def test_complete_ack_unknown_observes_exact_history_without_repeating_effect(effect_state, timing):
    state = effect_state
    state.commit_faults[2] = timing
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    unknown = caught.value
    assert unknown.phase == "complete_commit" and unknown.receipt.state == "complete"
    observed = state.runner.observe(
        state.spec, expected_header_digest=unknown.receipt.header_digest
    )
    assert observed.spec == state.spec and observed.witness == unknown.receipt.witness
    assert observed.header_digest == unknown.receipt.header_digest
    assert observed.state == ("armed" if timing == "before" else "complete")
    assert not observed.provisional and observed.historical
    assert jobs(state) == (
        (("pending", 0), ("pending", 0))
        if timing == "before"
        else (("succeeded", 1), ("succeeded", 1))
    )
    old_calls = list(state.calls)
    if timing == "before":
        with pytest.raises(effects.FileMaterializationEffectUnknown):
            batch(state)
    else:
        assert batch(state).caught_up
    assert state.calls == old_calls


def test_latest_source_changes_after_embedding_before_any_backend_write(effect_state):
    state = effect_state
    state.after_embed = lambda: new_source_tip(state)
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert "embed" in state.calls
    assert not {"keyword_write", "vector_write", "refresh"}.intersection(state.calls)
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


@pytest.mark.parametrize("model,route", [(User, "mapper"), (FileMaterializationOperation, "table")])
def test_routed_borrowed_connection_is_rejected_before_any_query_or_cleanup(
    effect_state, monkeypatch, model, route
):
    state = effect_state
    connection = state.engine.connect()
    connection.begin()
    db = Session(state.engine, binds={model if route == "mapper" else model.__table__: connection})
    before = len(state.sql)
    cleanup = []
    for name in ("rollback", "commit", "close"):
        monkeypatch.setattr(db, name, lambda name=name: cleanup.append(name))
    try:
        with pytest.raises(effects.FileMaterializationRefused, match="engine"):
            with effects.owned_file_materialization_session(lambda: db):
                pytest.fail("routed borrowed connection was admitted")
        assert len(state.sql) == before and cleanup == [] and connection.in_transaction()
    finally:
        Session.close(db)
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("phase,timing", [("arm", "after"), ("complete", "after")])
def test_commit_cancellation_retains_exact_unknown_identity(effect_state, phase, timing):
    state = effect_state
    state.commit_error = KeyboardInterrupt
    state.commit_faults[1 if phase == "arm" else 2] = timing
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    assert caught.value.phase == phase + "_commit"
    assert caught.value.receipt.spec == state.spec
    assert caught.value.__suppress_context__
    if phase == "arm":
        assert state.calls == []
    else:
        assert state.calls.count("keyword_write") == state.calls.count("vector_write") == 1


def test_cancellation_after_compute_started_is_unknown_and_never_reissued(effect_state):
    state = effect_state

    def cancel():
        raise KeyboardInterrupt("synthetic cancellation")

    state.after_embed = cancel
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    assert caught.value.phase == "effect"
    assert state.calls == ["keyword_factory", "rag_factory", "embed"]
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


@pytest.mark.parametrize("count", [0])
def test_vector_count_must_ack_exact_source_chunks_before_refresh_or_completion(
    effect_state, count
):
    state = effect_state
    state.vector_count = count
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert "vector_write" in state.calls and "refresh" not in state.calls
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


def test_genuine_deleted_event_uses_exact_bound_deletes_and_refresh(effect_state):
    state = effect_state
    state.ref = replace(
        state.ref, change_kind="delete", desired_state="deleted", content_checksum=None
    )
    state.spec = replace(state.spec, projection_event=state.ref)
    mutate(
        state,
        RetrievalProjectionEvent,
        change_kind="delete",
        desired_state="deleted",
        content_checksum=None,
    )
    mutate(state, RetrievalProjectionHead, desired_state="deleted", content_checksum=None)
    mutate(state, FileManagerFile, deleted_at=STAMP)
    for model in (SearchIndexJob, RagSyncJob):
        mutate(state, model, desired_state="deleted", operation="delete")
    assert batch(state).caught_up
    assert state.calls == [
        "keyword_factory",
        "rag_factory",
        "keyword_delete",
        "vector_delete",
        "refresh",
    ]
    assert operation(state)["source_extracted_at"] is None
    assert operation(state)["state"] == "complete"
    assert jobs(state) == (("succeeded", 1), ("succeeded", 1))
