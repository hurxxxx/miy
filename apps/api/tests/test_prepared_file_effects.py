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
from miy_api.domains.files.artifact_contract import FileArtifactNotReady
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


@pytest.mark.parametrize("timing", ["before", "after"])
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


def test_absent_historical_observation_has_no_effect_or_compute_authority(effect_state):
    state = effect_state
    assert state.runner.observe(state.spec) is None
    with pytest.raises(effects.FileMaterializationRefused, match="live_permit_required"):
        state.runner.execute(None, lambda *_args: state.calls.append("forbidden"))
    assert operation(state) is None and state.calls == []


@pytest.mark.parametrize("failure", ["vector", "refresh"])
def test_keyword_ack_then_failure_retains_arm_and_does_not_resolve_jobs(effect_state, failure):
    state = effect_state
    state.vector_failure = failure == "vector"
    state.refresh_failure = failure == "refresh"
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    assert caught.value.phase == "effect" and caught.value.receipt.spec == state.spec
    assert operation(state)["state"] == "armed"
    assert jobs(state) == (("pending", 0), ("pending", 0))
    assert state.calls.count("keyword_write") == state.calls.count("vector_write") == 1
    old_calls = list(state.calls)
    with pytest.raises(effects.FileMaterializationEffectUnknown, match="effect_unknown"):
        batch(state)
    assert state.calls == old_calls


@pytest.mark.parametrize("timing", ["before", "after"])
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


def test_historical_complete_is_readable_after_source_and_current_head_change(effect_state):
    state = effect_state
    batch(state)
    new_source_tip(state)
    mutate(state, FileManagerFile, extraction_status="pending", extracted_at=None)
    mutate(state, RetrievalProjectionHead, projection_version=2)
    observed = state.runner.observe(state.spec, expected_header_digest=HEADER_DIGEST)
    assert observed.state == "complete" and observed.historical
    assert observed.witness.source_event_id == SOURCE_ID
    with pytest.raises(effects.FileMaterializationRefused, match="digest_mismatch"):
        state.runner.observe(state.spec, expected_header_digest="c" * 64)
    with pytest.raises(effects.FileMaterializationRefused, match="identity_mismatch"):
        state.runner.observe(replace(state.spec, partition_metadata_version=2))


@pytest.mark.parametrize("count", [0, 2])
def test_rag_callback_must_occur_exactly_once_or_operation_stays_unknown(effect_state, count):
    state = effect_state
    state.callback_count = count
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert operation(state)["state"] == "armed"
    assert jobs(state) == (("pending", 0), ("pending", 0))
    assert state.calls.count("keyword_write") <= 1


def test_latest_source_changes_after_embedding_before_any_backend_write(effect_state):
    state = effect_state
    state.after_embed = lambda: new_source_tip(state)
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert "embed" in state.calls
    assert not {"keyword_write", "vector_write", "refresh"}.intersection(state.calls)
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


def test_final_source_mutation_after_vector_ack_keeps_progress_uncommitted(effect_state):
    state = effect_state
    state.after_vector = lambda: mutate(
        state, FileManagerFile, extracted_at=STAMP + timedelta(seconds=1)
    )
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert "keyword_write" in state.calls and "vector_write" in state.calls
    assert "refresh" not in state.calls
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


@pytest.mark.parametrize("outcome", ["unchanged", "superseded", None, 1, "unknown"])
def test_keyword_unproven_ack_stays_unknown_before_vector_mutation(effect_state, outcome):
    state = effect_state
    state.keyword_outcome = outcome
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert state.calls.count("keyword_write") == 1 and "vector_write" not in state.calls
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


def test_live_permit_cannot_be_consumed_twice(effect_state):
    state = effect_state
    permit = state.runner.arm(state.spec)
    receipt = state.runner.execute(permit, lambda *_args: state.calls.append("controlled_effect"))
    assert receipt.state == "complete" and not receipt.provisional
    with pytest.raises(effects.FileMaterializationRefused, match="permit_consumed"):
        state.runner.execute(permit, lambda *_args: state.calls.append("forbidden"))
    assert state.calls == ["controlled_effect"]


def test_empty_batch_and_reconciliation_include_global_armed_without_factories(effect_state):
    state = effect_state
    permit = state.runner.arm(state.spec)
    assert permit.receipt.state == "armed"
    mutate(state, SearchIndexJob, status="failed")
    mutate(state, RagSyncJob, status="failed")
    with state.engine.begin() as db:
        db.execute(state.tables[FileManagerFile].delete())
    instance = materializer(state)
    result = batch(state, instance, after=1)
    assert result.complete and not result.caught_up and result.scanned_events == 0
    assert result.keyword_remaining == result.vector_remaining == 1
    status = instance.inspect_reconciliation(through_event_sequence=1)
    assert not status.caught_up and status.keyword_remaining == status.vector_remaining == 1
    assert state.calls == [] and state.admissions > 0


def test_empty_batch_without_unknown_is_admitted_and_has_no_provider_effect(effect_state):
    state = effect_state
    mutate(state, SearchIndexJob, status="failed")
    mutate(state, RagSyncJob, status="failed")
    result = batch(state, after=1)
    assert result.caught_up and result.scanned_events == 0
    assert state.calls == [] and state.admissions > 0


@pytest.mark.parametrize("pending", ["active", "nested", "dirty", "new", "connection"])
def test_borrowed_session_is_rejected_without_sql_cleanup_or_caller_mutation(
    effect_state, monkeypatch, pending
):
    state = effect_state
    connection = state.engine.connect() if pending == "connection" else None
    db = Session(connection or state.engine)
    marker = None
    if pending == "active":
        db.begin()
        db.execute(state.tables[User].update().values(display_name="Caller transaction marker"))
    elif pending == "nested":
        db.begin_nested()
        db.execute(state.tables[User].update().values(display_name="Caller transaction marker"))
    elif pending == "dirty":
        marker = db.get(User, "synthetic-owner")
        marker.display_name = "Uncommitted caller marker"
    elif pending == "new":
        marker = User(id="caller-new", login_id="caller-new", password_hash="synthetic")
        db.add(marker)
    original_transaction = db.get_transaction()
    original_nested = db.get_nested_transaction()
    before = len(state.sql)
    cleanup = []
    for name in ("rollback", "commit", "close"):
        monkeypatch.setattr(db, name, lambda name=name: cleanup.append(name))
    try:
        with pytest.raises(effects.FileMaterializationRefused):
            with effects.owned_file_materialization_session(lambda: db):
                pytest.fail("borrowed Session was admitted")
        assert len(state.sql) == before and cleanup == []
        assert db.get_transaction() is original_transaction
        assert db.get_nested_transaction() is original_nested
        if pending in {"active", "nested"}:
            assert db.scalar(select(User.display_name)) == "Caller transaction marker"
        if pending == "dirty":
            assert marker.display_name == "Uncommitted caller marker" and marker in db.dirty
        if pending == "new":
            assert marker in db.new
    finally:
        Session.close(db)
        if connection is not None:
            connection.close()


@pytest.mark.parametrize("model", READ_MODELS, ids=lambda model: model.__name__)
@pytest.mark.parametrize("route", ["mapper", "table"])
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


@pytest.mark.parametrize("model", READ_MODELS, ids=lambda model: model.__name__)
@pytest.mark.parametrize("route", ["mapper", "table"])
def test_routed_alternate_engine_is_rejected_without_any_sql_or_cleanup(
    effect_state, tmp_path, monkeypatch, model, route
):
    state = effect_state
    alternate = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alternate.sqlite'}")
    alternate_sql = []
    event.listen(
        alternate, "before_cursor_execute", lambda _c, _cur, sql, *_rest: alternate_sql.append(sql)
    )
    db = Session(state.engine, binds={model if route == "mapper" else model.__table__: alternate})
    before = len(state.sql)
    cleanup = []
    for name in ("rollback", "commit", "close"):
        monkeypatch.setattr(db, name, lambda name=name: cleanup.append(name))
    try:
        with pytest.raises(effects.FileMaterializationRefused, match="single_engine_required"):
            with effects.owned_file_materialization_session(lambda: db):
                pytest.fail("alternate Engine was admitted")
        assert len(state.sql) == before and alternate_sql == [] and cleanup == []
        assert not db.in_transaction()
    finally:
        Session.close(db)
        alternate.dispose()


@pytest.mark.parametrize("phase", ["arm", "complete"])
@pytest.mark.parametrize("timing", ["before", "after"])
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


@pytest.mark.parametrize("phase", ["arm", "complete"])
@pytest.mark.parametrize("timing", ["before", "after"])
def test_cleanup_failures_do_not_replace_commit_unknown(effect_state, phase, timing):
    state = effect_state
    state.rollback_failure = state.close_failure = True
    state.commit_faults[1 if phase == "arm" else 2] = timing
    with pytest.raises(effects.FileMaterializationEffectUnknown) as caught:
        batch(state)
    assert caught.value.phase == phase + "_commit"
    assert caught.value.receipt.spec == state.spec
    assert caught.value.receipt.header_digest == HEADER_DIGEST
    assert str(caught.value) == "file_materialization_effect_unknown"


def test_successful_complete_ack_is_not_downgraded_by_close_failure(effect_state):
    state = effect_state
    state.close_failure = True
    assert batch(state).caught_up
    assert operation(state)["state"] == "complete"
    assert jobs(state) == (("succeeded", 1), ("succeeded", 1))


def test_original_control_is_not_replaced_by_cleanup_failure(effect_state, monkeypatch):
    state = effect_state
    state.rollback_failure = state.close_failure = True

    def refuse(_db):
        raise effects.FileMaterializationRefused("synthetic_fixed_identity_refusal")

    monkeypatch.setattr(effects, "require_file_materialization_identity", refuse)
    with pytest.raises(
        effects.FileMaterializationRefused, match="^synthetic_fixed_identity_refusal$"
    ):
        state.runner.arm(state.spec)
    assert state.calls == [] and operation(state) is None


def test_cleanup_cancellation_after_arm_ack_preserves_live_receipt(effect_state):
    state = effect_state
    state.close_failure = True
    state.close_error = KeyboardInterrupt
    try:
        permit = state.runner.arm(state.spec)
    except BaseException as error:
        pytest.fail(f"Cleanup replaced the known arm ACK with {type(error).__name__}")
    assert permit.receipt.spec == state.spec
    assert permit.receipt.header_digest == HEADER_DIGEST
    assert permit.receipt.state == "armed" and not permit.receipt.provisional
    assert operation(state)["state"] == "armed"
    assert state.calls == [] and jobs(state) == (("pending", 0), ("pending", 0))


def test_cleanup_cancellation_preserves_original_arm_commit_unknown(effect_state):
    state = effect_state
    state.commit_faults[1] = "before"
    state.close_failure = True
    state.close_error = KeyboardInterrupt
    # Capture BaseException so a regression reports an assertion rather than
    # interrupting pytest before the original typed receipt can be inspected.
    with pytest.raises(BaseException) as caught:
        state.runner.arm(state.spec)
    unknown = caught.value
    assert isinstance(unknown, effects.FileMaterializationEffectUnknown)
    assert unknown.phase == "arm_commit" and unknown.receipt.spec == state.spec
    assert unknown.receipt.header_digest == HEADER_DIGEST
    assert unknown.receipt.state == "armed" and unknown.receipt.provisional
    assert operation(state) is None
    assert state.calls == [] and jobs(state) == (("pending", 0), ("pending", 0))


def test_cleanup_cancellation_after_complete_ack_preserves_known_complete(effect_state):
    state = effect_state
    permit = state.runner.arm(state.spec)
    state.close_failure = True
    state.close_error = KeyboardInterrupt
    try:
        receipt = state.runner.execute(permit, lambda *_args: state.calls.append("effect"))
    except BaseException as error:
        pytest.fail(f"Cleanup replaced the known complete ACK with {type(error).__name__}")
    assert receipt.spec == state.spec and receipt.header_digest == HEADER_DIGEST
    assert receipt.state == "complete" and not receipt.provisional
    assert operation(state)["state"] == "complete" and state.calls == ["effect"]
    assert state.commit_calls == 2


@pytest.mark.parametrize("original", ["body", "preflight", "commit_unknown"])
def test_cleanup_cancellation_during_rollback_preserves_original_outcome(effect_state, original):
    state = effect_state
    permit = state.runner.arm(state.spec) if original != "body" else None
    state.rollback_failure = True
    state.rollback_error = KeyboardInterrupt
    if original == "commit_unknown":
        state.commit_faults[2] = "before"
        with pytest.raises(BaseException) as caught:
            state.runner.execute(permit, lambda *_args: state.calls.append("effect"))
        unknown = caught.value
        assert isinstance(unknown, effects.FileMaterializationEffectUnknown)
        assert unknown.phase == "complete_commit" and unknown.receipt.spec == state.spec
        assert unknown.receipt.header_digest == HEADER_DIGEST
        assert unknown.receipt.state == "complete" and unknown.receipt.provisional
        assert operation(state)["state"] == "armed" and state.calls == ["effect"]
    else:
        expected = (
            effects.FileMaterializationRefused("synthetic_fixed_body_refusal")
            if original == "body"
            else effects.FileMaterializationPreflightRefused(permit.receipt)
        )
        with pytest.raises(BaseException) as caught:
            with effects.owned_file_materialization_session(state.factory) as db:
                # Real SQL opens the owned transaction, forcing rollback in
                # finally while the original controlled outcome is in flight.
                db.scalar(select(state.tables[FileManagerFile].c.id))
                raise expected
        assert caught.value is expected
        if original == "preflight":
            assert caught.value.receipt == permit.receipt
            assert operation(state)["state"] == "armed"
        else:
            assert operation(state) is None
        assert state.calls == []
    assert jobs(state) == (("pending", 0), ("pending", 0))


def test_stale_source_preflight_retains_arm_consumed_permit_and_zero_attempts(effect_state):
    state = effect_state
    permit = state.runner.arm(state.spec)
    new_source_tip(state)
    with pytest.raises(effects.FileMaterializationPreflightRefused) as caught:
        state.runner.execute(permit, lambda *_args: state.calls.append("forbidden"))
    assert caught.value.receipt == permit.receipt
    assert state.calls == [] and operation(state)["state"] == "armed"
    with pytest.raises(effects.FileMaterializationRefused, match="permit_consumed"):
        state.runner.execute(permit, lambda *_args: state.calls.append("forbidden"))
    assert state.calls == []


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


@pytest.mark.parametrize("count", [0, 2])
def test_vector_count_must_ack_exact_source_chunks_before_refresh_or_completion(
    effect_state, count
):
    state = effect_state
    state.vector_count = count
    with pytest.raises(effects.FileMaterializationEffectUnknown):
        batch(state)
    assert "vector_write" in state.calls and "refresh" not in state.calls
    assert operation(state)["state"] == "armed" and jobs(state) == (("pending", 0), ("pending", 0))


@pytest.mark.parametrize("status", ["pending", "failed", "unsupported"])
def test_active_unavailable_source_never_arms_or_deletes(effect_state, status):
    state = effect_state
    mutate(state, FileManagerFile, extraction_status=status)
    with pytest.raises(FileArtifactNotReady):
        batch(state)
    assert operation(state) is None and state.calls == []
    assert jobs(state) == (("pending", 0), ("pending", 0))


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
