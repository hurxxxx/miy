"""Genuine Source events and restricted, inactive Files-only Core acceptance."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
import psycopg
from sqlalchemy import func, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from test_file_extraction_authority import (
    extraction_prepared as extraction_prepared,
    seeded_request,
)
from test_file_projection_core_roles import file_core_prepared as file_core_prepared
from test_file_projection_roles import reader_engine
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied,
    role_template as role_template,
    wait_for_blocker,
    world as world,
)
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files.extraction_contracts import (
    FileExtractionComputedResult,
    FileExtractionInput,
    FileExtractionRequestSpec,
)
from miy_api.domains.files.extraction_runner import FileExtractionRunner
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_delivery import (
    PREPARED_PROJECTION_RESOURCES,
    SourceProjectionReceipt,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_outbox import append_projection_intent
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval import files_projection_consumer as consumer
from miy_api.domains.retrieval import official_projection_ingress as ingress
from miy_api.domains.retrieval.files_projection_consumer import (
    FileProjectionConsumptionCommitUnknown,
    consume_file_projection_once,
    next_pending_file_projection,
    run_file_projection_consumer_once,
    run_file_projection_observation,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.partitioning import (
    create_managed_partition,
    ensure_default_partition,
)
from miy_api.domains.search.models import SearchIndexJob

RAW = b"Synthetic text"
SHA = sha256(RAW).hexdigest()


@pytest.fixture
def publications(monkeypatch):
    from miy_api.domains.rag import outbox as rag_outbox
    from miy_api.domains.search import outbox as search_outbox
    from miy_api.domains.files import core_projection, rag_projection, selected_storage

    calls = []

    def trap(*args, **kwargs):
        calls.append("effect")
        raise AssertionError("Core ingress cannot construct or call an effect")

    for module, names in (
        (rag_outbox, ("get_celery_client", "publish_rag_job_publication")),
        (search_outbox, ("get_celery_client", "_publish_job")),
        (rag_projection, ("load_file_rag_projection",)),
        (core_projection, ("load_ready_file_rag_projection",)),
        (selected_storage, ("read_selected_object",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, trap)
    return calls


@pytest.fixture
def c(world, file_core_prepared, monkeypatch, publications):
    from miy_api.domains.files import retrieval_contract

    with Session(world.engine) as db:
        seed_company_app_access(db, app_ids=("files", "pms"))
        db.commit()
    roles = file_core_prepared
    values = seeded_request(world, roles)
    payload = json.loads(values["request_payload"])
    spec = FileExtractionRequestSpec(
        request_id=values["request_id"],
        result_id=values["result_id"],
        event_id=values["event_id"],
        file_id=values["file_id"],
        actor_user_id=world.user_id,
        execution_ref=world.session_id,
        expected_input=FileExtractionInput.model_validate_json(payload["input_canonical"]),
    )
    source_engine, core_engine = (
        reader_engine(world, roles.source),
        reader_engine(world, roles.core),
    )
    reads = []

    def source_read(file):
        reads.append(file.id)
        return RAW

    monkeypatch.setattr(commands, "_read_source", source_read)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", True)
    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True))
    result = SimpleNamespace(
        world=world,
        roles=roles,
        source_engine=source_engine,
        core_engine=core_engine,
        source=lambda: Session(source_engine),
        core=lambda: Session(core_engine),
        spec=spec,
        token=uuid4(),
        reads=reads,
        publications=publications,
    )
    result.runner = FileExtractionRunner(result.source)
    yield result
    source_engine.dispose()
    core_engine.dispose()


def events(c):
    with c.source() as db:
        return [
            SourceProjectionReceipt.from_event(row)
            for row in db.scalars(
                select(OfficialProjectionOutbox)
                .where(OfficialProjectionOutbox.resource_id == c.spec.file_id)
                .order_by(OfficialProjectionOutbox.source_revision)
            )
        ]


def counts(c):
    with Session(c.world.engine) as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                OfficialProjectionReceipt,
                RetrievalProjectionEvent,
                SearchIndexJob,
                RagSyncJob,
            )
        )


def extract(c, outcome="ready"):
    if outcome == "ready":
        return c.runner.run(c.spec, claim_token=c.token)
    c.runner.prepare(c.spec)
    common = dict(
        request_id=c.spec.request_id,
        request_digest=c.spec.digest(),
        execution_ref=c.spec.execution_ref,
        claim_token=c.token,
    )
    c.runner._owned("claim", commands.claim_file_extraction, **common)
    bound = c.runner._owned("input_bind", commands.bind_file_extraction_input, **common)
    return c.runner._owned(
        "apply",
        commands.apply_file_extraction_result,
        **common,
        computed_result=FileExtractionComputedResult(outcome, bound.receipt.input_sha256),
    )


def consume(c, source):
    return run_file_projection_consumer_once(
        c.core, event_id=source.event_id, expected_digest=source.payload_digest
    )


def append(c, *, state="active", checksum=None, partition=None):
    with c.source() as db:
        row = append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=c.spec.file_id,
                retrieval_partition_id=partition or c.roles.partition,
                change_kind="delete" if state == "deleted" else "content",
                desired_state=state,
                operation="delete" if state == "deleted" else "upsert",
                content_checksum=checksum,
            ),
            event_id=uuid4(),
        )
        result = SourceProjectionReceipt.from_event(row)
        db.commit()
        return result


@pytest.mark.parametrize("open_gates", [False, True])
def test_pending_accepts_control_fence_without_any_jobs(c, monkeypatch, open_gates):
    from miy_api.domains.files import retrieval_contract

    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", open_gates)
    source = events(c)[0]
    staged = consume(c, source)
    assert not staged.provisional and staged.source == source
    assert counts(c) == (1, 1, 0, 0)
    with c.core() as db:
        head = db.get(RetrievalProjectionHead, ("file_manager_file", c.spec.file_id))
        assert (head.desired_state, head.content_checksum) == ("active", None)
    assert c.reads == [] and c.publications == []


@pytest.mark.parametrize("outcome", ["ready", "unsupported", "failed", "ocr_required"])
@pytest.mark.parametrize("open_gates", [False, True])
def test_genuine_f2_outcomes_stage_only_ready_or_deleted_jobs(c, monkeypatch, outcome, open_gates):
    from miy_api.domains.files import retrieval_contract

    extract(c, outcome)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", open_gates)
    all_events = events(c)
    results = [run_file_projection_consumer_once(c.core) for _ in all_events]
    terminal = results[-1]
    work = int(open_gates and outcome in {"ready", "unsupported"})
    assert counts(c) == (len(all_events), 1, work, work)
    assert terminal.source == all_events[-1] and not terminal.provisional
    if len(all_events) == 2:
        assert results[0].status == "superseded" and results[0].core_event_sequence is None
    with c.core() as db:
        head = db.get(RetrievalProjectionHead, ("file_manager_file", c.spec.file_id))
        assert head.desired_state == ("deleted" if outcome == "unsupported" else "active")
        assert head.content_checksum == (SHA if outcome == "ready" else None)
        if work:
            search = db.scalar(select(SearchIndexJob))
            rag = db.scalar(select(RagSyncJob))
            assert (
                search.projection_event_sequence
                == rag.projection_event_sequence
                == terminal.core_event_sequence
            )
            assert (
                search.operation
                == rag.operation
                == ("delete" if outcome == "unsupported" else "upsert")
            )
    assert run_file_projection_consumer_once(c.core) is None
    assert c.reads == [c.spec.file_id] and c.publications == []


def test_closed_gate_receipt_replay_does_not_backfill_after_enable(c, monkeypatch):
    from miy_api.domains.files import retrieval_contract

    extract(c)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", False)
    source = events(c)[-1]
    run_file_projection_consumer_once(c.core)
    accepted = consume(c, source)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", True)
    assert consume(c, source) == accepted and counts(c) == (2, 1, 0, 0)
    assert c.publications == []


def test_gap_refuses_then_oldest_discovery_supersedes_then_accepts(c):
    extract(c)
    first, latest = events(c)
    with pytest.raises(ProjectionOutboxError, match="projection_revision_gap"):
        consume(c, latest)
    assert counts(c) == (0, 0, 0, 0)
    with c.core() as db:
        assert next_pending_file_projection(db) == first
    older = run_file_projection_consumer_once(c.core)
    assert older.source == first and older.status == "superseded"
    assert counts(c) == (1, 0, 0, 0)
    assert run_file_projection_consumer_once(c.core).source == latest
    assert counts(c) == (2, 1, 1, 1) and c.publications == []


@pytest.mark.parametrize(
    "drift", ["ready_checksum", "pending_ready", "fake_delete", "missing", "deleted", "binding"]
)
def test_current_source_conflicts_refuse_before_core_mutation(c, drift):
    source = events(c)[0]
    if drift in {"ready_checksum", "fake_delete"}:
        consume(c, source)
        source = append(
            c,
            state="deleted" if drift == "fake_delete" else "active",
            checksum=SHA if drift == "ready_checksum" else None,
        )
    with c.source() as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        if drift == "pending_ready":
            file.extraction_status = "ready"
            file.extraction_content_checksum = SHA
        elif drift == "missing":
            db.delete(file)
        elif drift == "deleted":
            from miy_api.domains.auth.models import utcnow_naive

            file.deleted_at = utcnow_naive()
        elif drift == "binding":
            file.retrieval_partition_id = None
        db.commit()
    before = counts(c)
    with pytest.raises(ProjectionOutboxError):
        consume(c, source)
    assert counts(c) == before and c.publications == [] and c.reads == []


def test_two_consumers_converge_one_actual_event_and_job_pair(c):
    extract(c)
    first, source = events(c)
    consume(c, first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(c, source), range(2)))
    assert results[0] == results[1]
    assert counts(c) == (2, 1, 1, 1) and c.publications == []


def test_hard_delete_uses_genuine_source_intent_and_never_source_callback(c):
    consume(c, events(c)[0])
    with c.source() as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        row = append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file.id,
                retrieval_partition_id=file.retrieval_partition_id,
                change_kind="delete",
                desired_state="deleted",
                operation="delete",
            ),
            event_id=uuid4(),
        )
        source = SourceProjectionReceipt.from_event(row)
        db.delete(file)
        db.commit()
    result = consume(c, source)
    assert result.status == "accepted" and counts(c) == (2, 2, 1, 1)
    assert c.reads == [] and c.publications == []


def test_existing_pending_jobs_merge_without_publisher_construction(c):
    extract(c)
    first, ready = events(c)
    consume(c, first)
    consume(c, ready)
    with c.core() as db:
        before = (db.scalar(select(SearchIndexJob.id)), db.scalar(select(RagSyncJob.id)))
    newer = append(c, checksum=SHA)
    result = consume(c, newer)
    with c.core() as db:
        search, rag = db.scalar(select(SearchIndexJob)), db.scalar(select(RagSyncJob))
        assert (search.id, rag.id) == before
        assert (
            search.projection_event_sequence
            == rag.projection_event_sequence
            == result.core_event_sequence
        )
    assert counts(c) == (3, 2, 1, 1) and c.publications == []


def test_partition_lifecycle_waits_for_core_share_then_new_event_refuses(c):
    with c.core() as db:
        source = events(c)[0]
        staged = consume_file_projection_once(
            db, event_id=source.event_id, expected_digest=source.payload_digest
        )
        assert staged.provisional
        backend = db.scalar(text("SELECT pg_backend_pid()"))
        with ThreadPoolExecutor(max_workers=1) as pool:

            def retire():
                with Session(c.world.engine) as admin:
                    partition = admin.get(RetrievalPartition, c.roles.partition)
                    partition.state = "retired"
                    partition.is_default_ingest = False
                    admin.commit()

            future = pool.submit(retire)
            try:
                wait_for_blocker(c.world, backend)
            finally:
                db.commit()
                future.result(timeout=10)
    historical = consume(c, source)
    assert (
        not historical.provisional and historical.core_event_sequence == staged.core_event_sequence
    )
    newer = append(c)
    with pytest.raises(ProjectionOutboxError):
        consume(c, newer)
    assert counts(c) == (1, 1, 0, 0)


def test_post_flush_failure_rolls_back_event_jobs_and_receipt(c, monkeypatch):
    extract(c)
    first, latest = events(c)
    consume(c, first)
    original = ingress._stage_file_jobs

    def after_actual_flush(db, *args, **kwargs):
        original(db, *args, **kwargs)
        assert db.scalar(select(func.count()).select_from(SearchIndexJob)) == 1
        raise ProjectionOutboxError("synthetic_after_job_flush")

    monkeypatch.setattr(ingress, "_stage_file_jobs", after_actual_flush)
    with pytest.raises(ProjectionOutboxError, match="synthetic_after_job_flush"):
        consume(c, latest)
    assert counts(c) == (1, 0, 0, 0) and c.publications == []


@pytest.mark.parametrize("after_commit", [False, True])
def test_actual_commit_ack_unknown_preserves_identity_and_observation_only(
    c, after_commit, monkeypatch
):
    extract(c)
    first, source = events(c)
    consume(c, first)

    class FaultSession(Session):
        def commit(self):
            if after_commit:
                super().commit()
            raise StatementError("private commit detail", "private SQL", {"secret": "hidden"}, None)

        def close(self):
            super().close()
            raise RuntimeError("private cleanup detail")

    with pytest.raises(FileProjectionConsumptionCommitUnknown) as caught:
        run_file_projection_consumer_once(
            lambda: FaultSession(c.core_engine),
            event_id=source.event_id,
            expected_digest=source.payload_digest,
        )
    retained = caught.value.consumption
    assert retained.source == source and retained.provisional
    assert "private" not in str(caught.value)
    before = counts(c)

    def no_accept(*args, **kwargs):
        raise AssertionError("observation cannot repeat acceptance")

    monkeypatch.setattr(consumer, "accept_prepared_file_projection_intent", no_accept)
    observed = run_file_projection_observation(
        c.core,
        event_id=source.event_id,
        expected_digest=source.payload_digest,
        expected_consumption=retained,
    )
    assert (observed is not None) == after_commit
    if observed is not None:
        assert observed == replace(retained, provisional=False)
    assert counts(c) == before and c.reads == [c.spec.file_id] and c.publications == []


def test_successful_ack_and_cleanup_failure_preserve_durable_result(c):
    class CloseFaultSession(Session):
        def close(self):
            super().close()
            raise RuntimeError("private cleanup detail")

    source = events(c)[0]
    result = run_file_projection_consumer_once(
        lambda: CloseFaultSession(c.core_engine),
        event_id=source.event_id,
        expected_digest=source.payload_digest,
    )
    assert not result.provisional and counts(c) == (1, 1, 0, 0)


@pytest.mark.parametrize("join_mode", ["rollback_only", "create_savepoint"])
@pytest.mark.parametrize("outer", [False, True])
def test_connection_backed_factory_preserves_external_marker_before_sql(c, join_mode, outer):
    with c.core_engine.connect() as conn:
        transaction = conn.begin() if outer else None
        if outer:
            conn.execute(text("SELECT 42"))
        source = events(c)[0]
        db = Session(bind=conn, join_transaction_mode=join_mode)
        with pytest.raises(ProjectionOutboxError, match="file_projection_engine_binding_required"):
            run_file_projection_consumer_once(
                lambda: db, event_id=source.event_id, expected_digest=source.payload_digest
            )
        assert conn.in_transaction() == outer and not db.in_transaction()
        assert counts(c) == (0, 0, 0, 0)
        if transaction:
            assert conn.scalar(text("SELECT 42")) == 42
            transaction.rollback()
        db.close()


def test_core_source_write_row_lock_and_private_read_remain_denied(c):
    with c.world.connect(c.roles.core) as conn:
        for query in (
            "UPDATE file_manager_files SET extraction_status='ready' WHERE false",
            "DELETE FROM file_manager_files WHERE false",
            "SELECT id FROM file_manager_files FOR SHARE",
            "SELECT storage_key FROM file_manager_files",
            "SELECT extraction_text FROM file_manager_files",
            "SELECT token_hash FROM auth_sessions",
        ):
            denied(conn, query)
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction(), conn.cursor() as cursor:
                with cursor.copy("COPY file_manager_files(id) FROM STDIN"):
                    pass
        assert caught.value.sqlstate == "42501"
    assert counts(c) == (0, 0, 0, 0)


def test_caller_observation_of_own_flushed_receipt_is_still_provisional(c):
    source = events(c)[0]
    with c.core() as db:
        staged = consume_file_projection_once(
            db, event_id=source.event_id, expected_digest=source.payload_digest
        )
        observed = consumer.observe_file_projection_consumption(
            db,
            event_id=source.event_id,
            expected_digest=source.payload_digest,
            expected_consumption=staged,
        )
        assert observed.provisional
        with pytest.raises(
            ProjectionOutboxError, match="projection_consumption_requires_fresh_session"
        ):
            run_file_projection_observation(
                lambda: db, event_id=source.event_id, expected_digest=source.payload_digest
            )
        assert db.in_transaction()
        db.rollback()
    assert counts(c) == (0, 0, 0, 0)
    assert (
        run_file_projection_observation(
            c.core, event_id=source.event_id, expected_digest=source.payload_digest
        )
        is None
    )


def test_wrong_digest_and_historical_witness_conflict_create_no_work(c):
    source = events(c)[0]
    with pytest.raises(ProjectionOutboxError, match="projection_event_conflict"):
        run_file_projection_consumer_once(
            c.core, event_id=source.event_id, expected_digest="f" * 64
        )
    assert counts(c) == (0, 0, 0, 0)
    actual = consume(c, source)
    with pytest.raises(ProjectionOutboxError, match="projection_receipt_conflict"):
        run_file_projection_observation(
            c.core,
            event_id=source.event_id,
            expected_digest=source.payload_digest,
            expected_consumption=replace(
                actual, core_event_sequence=actual.core_event_sequence + 1
            ),
        )
    assert counts(c) == (1, 1, 0, 0)


def test_rag_gate_closed_keeps_ready_control_receipt_without_jobs(c, monkeypatch):
    extract(c)
    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=False))
    run_file_projection_consumer_once(c.core)
    source = events(c)[-1]
    result = consume(c, source)
    assert not result.provisional and counts(c) == (2, 1, 0, 0)
    assert c.publications == []


def test_fixed_files_discovery_skips_genuine_docs_and_old3_stays_fixed(c):
    from miy_api.domains.docs.models import NativeDoc

    with Session(c.world.engine) as admin:
        partition = ensure_default_partition(
            admin, source_namespace="docs", candidate_scope_kind="company"
        )
        docs_partition = str(partition.id)
        admin.commit()
    with c.source() as db:
        doc = NativeDoc(
            id=str(uuid4()),
            owner_id=c.world.user_id,
            title="Synthetic",
            retrieval_partition_id=docs_partition,
        )
        db.add(doc)
        db.flush()
        row = append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="docs_native_doc",
                resource_id=doc.id,
                retrieval_partition_id=docs_partition,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=uuid4(),
        )
        docs_source = SourceProjectionReceipt.from_event(row)
        db.commit()
    assert PREPARED_PROJECTION_RESOURCES == {"docs_native_doc", "pms_task", "meeting"}
    source = events(c)[0]
    assert run_file_projection_consumer_once(c.core).source == source
    assert run_file_projection_consumer_once(c.core) is None
    with pytest.raises(ProjectionOutboxError, match="projection_consumer_resource_unavailable"):
        consume(c, docs_source)
    assert counts(c) == (1, 1, 0, 0) and c.publications == []


@pytest.mark.parametrize("drift", [None, "external_checksum", "corpus_binding"])
def test_managed_partition_and_safe_metadata_checksum_are_current(c, drift):
    with Session(c.world.engine) as admin:
        partition = create_managed_partition(
            admin, source_namespace="files", candidate_scope_kind="company"
        )
        managed_partition = str(partition.id)
        admin.commit()
    with c.source() as db:
        corpus = FileManagerCorpus(
            id=str(uuid4()),
            name="Synthetic managed corpus",
            access_scope_kind="company",
            retrieval_partition_id=managed_partition,
            created_by_id=c.world.user_id,
            source_managed=True,
            authorization_mode="explicit_grants",
        )
        db.add(corpus)
        db.flush()
        file = db.get(FileManagerFile, c.spec.file_id)
        file.corpus_id = corpus.id
        file.retrieval_partition_id = managed_partition
        db.flush()
        db.add(
            FileManagerFileSourceMetadata(
                file_id=file.id,
                corpus_id=corpus.id,
                external_id="synthetic-external",
                external_id_sha256="a" * 64,
                source_kind="synthetic",
                source_id="synthetic-source",
                source_id_sha256="b" * 64,
                content_checksum=SHA,
                acl_resolved=True,
            )
        )
        append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file.id,
                retrieval_partition_id=managed_partition,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=uuid4(),
        )
        db.commit()
    captured = c.runner.capture(
        actor_user_id=c.spec.actor_user_id,
        execution_ref=c.spec.execution_ref,
        file_id=c.spec.file_id,
    )
    c.spec = c.spec.model_copy(update={"expected_input": captured})
    extract(c)
    old, pending, ready = events(c)
    assert consume(c, old).status == consume(c, pending).status == "superseded"
    if drift is not None:
        with c.source() as db:
            file = db.get(FileManagerFile, c.spec.file_id)
            if drift == "external_checksum":
                db.get(FileManagerFileSourceMetadata, file.id).content_checksum = "f" * 64
            else:
                db.get(FileManagerCorpus, file.corpus_id).retrieval_partition_id = c.roles.partition
            db.commit()
        with pytest.raises(ProjectionOutboxError):
            consume(c, ready)
        assert counts(c) == (2, 0, 0, 0)
    else:
        result = consume(c, ready)
        with c.core() as db:
            head = db.get(RetrievalProjectionHead, ("file_manager_file", c.spec.file_id))
            assert head.retrieval_partition_id == managed_partition
        assert result.status == "accepted" and counts(c) == (3, 1, 1, 1)
    assert c.publications == [] and c.reads == [c.spec.file_id]
