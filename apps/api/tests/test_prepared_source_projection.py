"""Real Source-only hooks and separately owned Core transactions; no live broker."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from miy_api.core.principal import user_principal
from miy_api.domains.auth.models import CompanyAppControl, User, utcnow_naive
from miy_api.domains.docs.access_grants import grant_doc_access
from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.docs.rag_sync import (
    enqueue_meeting_visibility_recompute,
    enqueue_native_doc_rag_sync,
    enqueue_native_doc_visibility,
)
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.meeting.search_hooks import enqueue_meeting_search_index
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_delivery import (
    deliver_projection_intent,
    is_prepared_source_projection,
    lookup_source_projection_receipt,
    prepared_source_projection,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.pms.models import Task, TaskList
from miy_api.domains.pms.search_hooks import enqueue_task_search_index
from miy_api.domains.rag.contracts import RagSyncOperation
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.official_projection_consumer import (
    ProjectionConsumptionCommitUnknown,
    consume_projection_once,
    next_pending_projection,
    run_projection_consumer_once,
)
from miy_api.domains.retrieval.prepared_company_partitions import (
    lookup_company_projection_defaults,
    prepare_company_projection_defaults,
)
from miy_api.domains.retrieval.partitioning import RetrievalPartitionConflict
from miy_api.domains.search.models import SearchIndexJob
from test_official_partition_reader import prepared as prepared
from company_admission_fixture import seed_company_app_access
from test_official_writer_roles import (
    BASE,
    PASSWORD,
    sa_dsn,
    wait_for_blocker,
)
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


@pytest.fixture
def publications(monkeypatch):
    from miy_api.domains.rag import outbox as rag_outbox
    from miy_api.domains.search import outbox as search_outbox

    calls = []

    def publication(*args, **kwargs):
        calls.append((args, kwargs))

    def construction():
        calls.append("publisher construction")
        raise AssertionError("prepared consumer must not construct a publisher")

    monkeypatch.setattr(search_outbox, "_publish_job", publication)
    monkeypatch.setattr(rag_outbox, "publish_rag_job_publication", publication)
    monkeypatch.setattr(search_outbox, "get_celery_client", construction)
    monkeypatch.setattr(rag_outbox, "get_celery_client", construction)
    return calls


@pytest.fixture
def c(world, prepared, monkeypatch, publications):
    from miy_api.domains.retrieval import official_projection_ingress

    monkeypatch.setattr(
        official_projection_ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True)
    )
    roles = prepared
    engines = []

    def factory(role):
        engine = create_engine(sa_dsn(make_conninfo(world.dsn, user=role, password=PASSWORD)))
        engines.append(engine)
        return sessionmaker(engine, autoflush=False)

    source, core = factory(roles.source), factory(roles.core)
    with source() as db:
        db.add(
            TaskList(
                id="prepared-list", key="PREPARED", name="Fixture", created_by_id=world.user_id
            )
        )
        db.add(NativeDoc(id="prepared-doc", owner_id=world.user_id, title="Original"))
        db.add(
            Meeting(
                id="prepared-meeting",
                title="Original",
                organizer_id=world.user_id,
                start_at=utcnow_naive(),
                end_at=utcnow_naive(),
            )
        )
        db.flush()
        db.add(
            Task(
                id="prepared-task",
                list_id="prepared-list",
                task_number=1,
                title="Original",
                reporter_id=world.user_id,
            )
        )
        db.commit()
    yield SimpleNamespace(world=world, roles=roles, source=source, core=core, factory=factory)
    for engine in engines:
        engine.dispose()


def counts(world):
    with Session(world.engine) as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                OfficialProjectionOutbox,
                OfficialProjectionReceipt,
                RetrievalProjectionEvent,
                SearchIndexJob,
                RagSyncJob,
            )
        )


def emit(c, resource="docs", operation="upsert"):
    with c.source() as db, prepared_source_projection(db) as journal:
        if resource == "docs":
            row = db.get(NativeDoc, "prepared-doc")
            row.title = "Changed"
            if operation == "delete":
                row.trashed_at = utcnow_naive()
            result = enqueue_native_doc_rag_sync(db, doc=row, operation=RagSyncOperation(operation))
        elif resource == "pms":
            row = db.get(Task, "prepared-task")
            row.title = "Changed"
            result = enqueue_task_search_index(db, task=row, operation=operation)
        else:
            row = db.get(Meeting, "prepared-meeting")
            row.title = "Changed"
            result = enqueue_meeting_search_index(db, meeting=row, operation=operation)
        assert result is None
        receipt = journal.receipts[-1]
        db.commit()
        return receipt


@pytest.mark.parametrize("resource", ["docs", "pms", "meeting"])
def test_prepared_hook_commits_source_only_then_core_stages_separately(c, publications, resource):
    source = emit(c, resource)
    assert counts(c.world) == (1, 0, 0, 0, 0)
    assert not hasattr(source, "core_event_sequence")
    assert not hasattr(source, "projection_version")
    result = run_projection_consumer_once(
        c.core, event_id=source.event_id, expected_digest=source.payload_digest
    )
    assert result.source == source and result.status == "accepted"
    assert counts(c.world) == (1, 1, 1, 1, int(resource == "docs"))
    assert run_projection_consumer_once(c.core) is None
    assert publications == []


@pytest.mark.parametrize("savepoint", [False, True])
def test_source_rollback_never_makes_journal_receipt_durable(c, savepoint):
    with c.source() as db, prepared_source_projection(db) as journal:
        nested = db.begin_nested() if savepoint else None
        row = db.get(NativeDoc, "prepared-doc")
        row.title = "Rolled back"
        enqueue_native_doc_rag_sync(db, doc=row, operation=RagSyncOperation.UPSERT)
        provisional = journal.receipts[0]
        if nested:
            nested.rollback()
            db.commit()
        else:
            db.rollback()
        assert journal.receipts == (provisional,)
        assert (
            lookup_source_projection_receipt(
                db, event_id=provisional.event_id, expected_digest=provisional.payload_digest
            )
            is None
        )
        assert db.get(NativeDoc, "prepared-doc").title == "Original"
    assert counts(c.world) == (0, 0, 0, 0, 0)
    assert run_projection_consumer_once(c.core) is None


def test_source_commit_ack_unknown_observes_same_event_without_business_reexecution(c):
    with c.source() as db, prepared_source_projection(db) as journal:
        row = db.get(NativeDoc, "prepared-doc")
        row.title = "Once"
        enqueue_native_doc_rag_sync(db, doc=row, operation=RagSyncOperation.UPSERT)
        source = journal.receipts[0]

        def lost_ack():
            db.commit()
            raise ConnectionError("synthetic source ACK loss")

        with pytest.raises(ConnectionError):
            lost_ack()
    with c.source() as db:
        assert (
            lookup_source_projection_receipt(
                db, event_id=source.event_id, expected_digest=source.payload_digest
            )
            == source
        )
        assert db.get(NativeDoc, "prepared-doc").title == "Once"
    run_projection_consumer_once(
        c.core, event_id=source.event_id, expected_digest=source.payload_digest
    )
    assert counts(c.world) == (1, 1, 1, 1, 1)


@pytest.mark.parametrize("committed", [False, True])
def test_core_unknown_commit_retains_same_event_and_reconciles_on_fresh_connection(c, committed):
    source = emit(c)

    class LostAckSession(Session):
        def commit(self):
            if committed:
                super().commit()
            raise ConnectionError("synthetic Core COMMIT uncertainty")

    factory = sessionmaker(c.core.kw["bind"], class_=LostAckSession, autoflush=False)
    with pytest.raises(ProjectionConsumptionCommitUnknown) as error:
        run_projection_consumer_once(
            factory, event_id=source.event_id, expected_digest=source.payload_digest
        )
    assert error.value.consumption.source == source
    assert counts(c.world) == (1, int(committed), int(committed), int(committed), int(committed))
    reconciled = run_projection_consumer_once(
        c.core, event_id=source.event_id, expected_digest=source.payload_digest
    )
    assert reconciled.source == error.value.consumption.source
    if committed:
        assert reconciled == error.value.consumption
    assert counts(c.world) == (1, 1, 1, 1, 1)


def test_pending_discovery_uses_source_revision_instead_of_uuid_order(c):
    with c.source() as db, prepared_source_projection(db) as journal:
        doc = db.get(NativeDoc, "prepared-doc")
        enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
        original = journal.receipts[0]
        event = db.get(OfficialProjectionOutbox, original.event_id)
        intent = ProjectionIntent.model_validate_json(event.payload)
        deliver_projection_intent(db, intent=intent, event_id=UUID(int=2))
        deliver_projection_intent(
            db,
            intent=intent.model_copy(
                update={"operation": "delete", "desired_state": "deleted", "change_kind": "delete"}
            ),
            event_id=UUID(int=1),
        )
        sources = journal.receipts
        db.commit()
    for ordinal, source in enumerate(sources, 1):
        with c.core() as db:
            assert next_pending_projection(db) == source
            assert db.scalar(text("SHOW statement_timeout")) == "15s"
            assert db.scalar(text("SHOW lock_timeout")) == "5s"
        result = run_projection_consumer_once(c.core)
        assert result.source.source_revision == ordinal
        assert result.status == ("accepted" if ordinal == 3 else "superseded")
    assert counts(c.world) == (3, 3, 1, 1, 1)


def test_pending_discovery_does_not_skip_later_commit(c):
    with c.source() as late, prepared_source_projection(late) as late_journal:
        doc = late.get(NativeDoc, "prepared-doc")
        enqueue_native_doc_rag_sync(late, doc=doc, operation=RagSyncOperation.UPSERT)
        early = emit(c, "meeting")
        assert run_projection_consumer_once(c.core).source == early
        assert run_projection_consumer_once(c.core) is None
        late.commit()
        assert run_projection_consumer_once(c.core).source == late_journal.receipts[0]
    assert counts(c.world) == (2, 2, 2, 2, 1)


def test_prepared_second_event_merges_pending_keyword_and_rag_without_publication(c, publications):
    first = emit(c)
    run_projection_consumer_once(
        c.core, event_id=first.event_id, expected_digest=first.payload_digest
    )
    second = emit(c)
    run_projection_consumer_once(
        c.core, event_id=second.event_id, expected_digest=second.payload_digest
    )
    assert counts(c.world) == (2, 2, 2, 1, 1)
    with Session(c.world.engine) as db:
        for model in (SearchIndexJob, RagSyncJob):
            assert db.scalar(select(model)).projection_version == 2
    assert publications == []


def test_bounded_source_journal_overflow_rolls_back_whole_original_transaction(c):
    with c.source() as db, prepared_source_projection(db) as journal:
        doc = db.get(NativeDoc, "prepared-doc")
        doc.title = "Must roll back"
        for _ in range(100):
            enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
        with pytest.raises(ProjectionOutboxError, match="emission_limit"):
            enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
        assert len(journal.receipts) == 100
        db.rollback()
        assert db.get(NativeDoc, "prepared-doc").title == "Original"
    assert counts(c.world) == (0, 0, 0, 0, 0)


def test_two_core_consumers_converge_to_one_receipt(c):
    source = emit(c, "meeting")
    with c.core() as first, ThreadPoolExecutor(max_workers=1) as pool:
        pid = first.scalar(text("SELECT pg_backend_pid()"))
        staged = consume_projection_once(
            first, event_id=source.event_id, expected_digest=source.payload_digest
        )
        later = pool.submit(
            run_projection_consumer_once,
            c.core,
            event_id=source.event_id,
            expected_digest=source.payload_digest,
        )
        try:
            wait_for_blocker(c.world, pid)
            assert not later.done()
        finally:
            first.commit()
        assert later.result(timeout=8) == staged
    assert counts(c.world) == (1, 1, 1, 1, 0)


@pytest.mark.parametrize("phase", ["source", "core"])
def test_source_and_core_transactions_hold_real_metadata_share_until_commit(c, phase):
    def transition(partition_id):
        with Session(c.world.engine) as db:
            db.execute(
                text("UPDATE retrieval_partitions SET state='transitioning' WHERE id=:id"),
                {"id": partition_id},
            )
            db.commit()

    source = emit(c) if phase == "core" else None
    with (
        c.source() if phase == "source" else c.core() as db,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        pid = db.scalar(text("SELECT pg_backend_pid()"))
        if phase == "source":
            with prepared_source_projection(db) as journal:
                doc = db.get(NativeDoc, "prepared-doc")
                enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
                source = journal.receipts[0]
                partition_id = doc.retrieval_partition_id
        else:
            consume_projection_once(
                db, event_id=source.event_id, expected_digest=source.payload_digest
            )
            partition_id = db.get(
                RetrievalProjectionHead, (source.resource_type, source.resource_id)
            ).retrieval_partition_id
        later = pool.submit(transition, partition_id)
        try:
            wait_for_blocker(c.world, pid)
            assert not later.done()
        finally:
            db.commit()
        later.result(timeout=8)
    if phase == "source":
        with pytest.raises(Exception) as error:
            run_projection_consumer_once(
                c.core, event_id=source.event_id, expected_digest=source.payload_digest
            )
        assert error.value.orig.sqlstate == "55000"
        assert counts(c.world) == (1, 0, 0, 0, 0)
    else:
        # An exact historical receipt remains valid after a later lifecycle change.
        assert (
            run_projection_consumer_once(
                c.core, event_id=source.event_id, expected_digest=source.payload_digest
            ).status
            == "accepted"
        )
        assert counts(c.world) == (1, 1, 1, 1, 1)


@pytest.mark.parametrize("change", ["missing", "inactive", "wrong_namespace", "managed_binding"])
def test_prepared_invalid_default_never_falls_back_or_commits_source(c, change):
    with Session(c.world.engine) as core:
        partition = core.scalar(
            select(RetrievalPartition).where(RetrievalPartition.source_namespace == "docs")
        )
        if change == "missing":
            core.delete(partition)
        elif change == "inactive":
            partition.state = "transitioning"
        elif change == "wrong_namespace":
            partition.source_namespace = "invalid_docs"
        else:
            partition = RetrievalPartition(
                source_namespace="docs", candidate_scope_kind="company", is_default_ingest=False
            )
            core.add(partition)
            core.flush()
        partition_id = partition.id
        core.commit()
    if change == "managed_binding":
        with c.source() as db:
            db.get(NativeDoc, "prepared-doc").retrieval_partition_id = partition_id
            db.commit()
    with pytest.raises(Exception) as error:
        emit(c)
    assert error.value.orig.sqlstate == "55000"
    with c.source() as db:
        assert db.get(NativeDoc, "prepared-doc").title == "Original"
    assert counts(c.world) == (0, 0, 0, 0, 0)


def test_private_docs_grant_visibility_and_trash_emit_only_source_current_state(c):
    with c.source() as db, prepared_source_projection(db) as journal:
        grant_doc_access(
            db,
            doc_id="prepared-doc",
            user_id=c.world.user_id,
            granted_by_user_id=c.world.user_id,
            granted_by_meeting_id=None,
            reason="Synthetic Source grant",
        )
        doc = db.get(NativeDoc, "prepared-doc")
        assert doc.ownership_kind == "personal" and not doc.company_visible
        company_partition = doc.retrieval_partition_id
        doc.trashed_at = utcnow_naive()
        db.flush()
        enqueue_native_doc_visibility(db, doc_id=doc.id)
        assert doc.retrieval_partition_id == company_partition
        db.commit()
    assert len(journal.receipts) == 2
    assert counts(c.world) == (2, 0, 0, 0, 0)
    assert run_projection_consumer_once(c.core).status == "superseded"
    assert run_projection_consumer_once(c.core).status == "accepted"
    with Session(c.world.engine) as db:
        assert (
            db.get(RetrievalProjectionHead, ("docs_native_doc", "prepared-doc")).desired_state
            == "deleted"
        )


def test_source_context_is_explicit_scoped_and_cannot_stage_core_reference(c):
    with c.source() as db:
        db.info["source_only"] = True
        assert not is_prepared_source_projection(db)
        with prepared_source_projection(db):
            assert is_prepared_source_projection(db)
            with pytest.raises(ProjectionOutboxError, match="already_prepared"):
                with prepared_source_projection(db):
                    pass
            with pytest.raises(ProjectionOutboxError, match="core_reference"):
                enqueue_task_search_index(
                    db, task=db.get(Task, "prepared-task"), projection_event=object()
                )
        assert not is_prepared_source_projection(db)
    assert counts(c.world) == (0, 0, 0, 0, 0)


def test_consumer_refuses_borrowed_transaction_and_partial_identity(c):
    with c.core() as db:
        db.scalar(text("SELECT 1"))
        with pytest.raises(ProjectionOutboxError, match="fresh_session"):
            run_projection_consumer_once(lambda: db)
    with pytest.raises(ProjectionOutboxError, match="identity_required"):
        run_projection_consumer_once(c.core, event_id=str(uuid4()))


def test_default_core_preparation_is_caller_owned_and_reuses_exact_ids(world):
    with Session(world.engine) as db:
        first = prepare_company_projection_defaults(
            db, world.actor, expected=BASE, expected_state="active"
        )
        assert len(first) == 3
        db.rollback()
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 0
        second = prepare_company_projection_defaults(
            db, world.actor, expected=BASE, expected_state="active"
        )
        db.commit()
    with Session(world.engine) as db:
        assert (
            prepare_company_projection_defaults(
                db, world.actor, expected=BASE, expected_state="active"
            )
            == second
        )


def test_default_legacy_hook_keeps_synchronous_core_and_publication(world, publications):
    with Session(world.engine) as db:
        doc = NativeDoc(id="legacy-doc", owner_id=world.user_id, title="Legacy")
        db.add(doc)
        enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
        db.commit()
    assert counts(world)[:4] == (1, 1, 1, 1)
    assert publications


def test_unknown_default_setup_queries_saved_uuids_and_never_allocates_replacement(world):
    with Session(world.engine) as db:
        saved = prepare_company_projection_defaults(
            db, world.actor, expected=BASE, expected_state="active"
        )
        db.commit()
        # Model setup ACK loss, then a separately authorized later lifecycle.
        row = db.get(RetrievalPartition, saved[0].partition_id)
        row.is_default_ingest = False
        row.state = "retired"
        db.commit()
    with Session(world.engine) as db:
        with pytest.raises(RetrievalPartitionConflict, match="changed"):
            lookup_company_projection_defaults(db, prepared=saved)
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 3
        assert (
            db.scalar(
                select(func.count())
                .select_from(RetrievalPartition)
                .where(RetrievalPartition.source_namespace == "docs")
            )
            == 1
        )


def test_unobserved_default_setup_lookup_does_not_create_rows(world):
    with Session(world.engine) as db:
        saved = prepare_company_projection_defaults(
            db, world.actor, expected=BASE, expected_state="active"
        )
        db.rollback()
        assert lookup_company_projection_defaults(db, prepared=saved) is None
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 0


def test_meeting_doc_fanout_uses_same_prepared_source_session_and_deduplicates(c):
    with c.source() as db, prepared_source_projection(db) as journal:
        enqueue_meeting_visibility_recompute(
            db,
            meeting_id="prepared-meeting",
            doc_ids=["prepared-doc", "missing-doc", "prepared-doc"],
        )
        assert len(journal.receipts) == 1
        assert journal.receipts[0].resource_type == "docs_native_doc"
        assert counts(c.world) == (0, 0, 0, 0, 0)
        db.commit()
    assert counts(c.world) == (1, 0, 0, 0, 0)
    assert run_projection_consumer_once(c.core).source == journal.receipts[0]


@pytest.mark.parametrize("denial", ["app_admission", "resource_acl"])
def test_original_docs_mutation_denies_before_partition_capability_or_source_write(
    c, monkeypatch, denial
):
    from miy_api.domains.docs.page_mutations import CreateNativePageCommand, create_native_page
    from miy_api.domains.retrieval import prepared_company_partitions

    def forbidden_capability(*args, **kwargs):
        raise AssertionError("denied original mutation cannot acquire a partition capability")

    monkeypatch.setattr(
        prepared_company_partitions, "require_prepared_company_partition", forbidden_capability
    )
    with Session(c.world.engine) as db:
        other = User(
            id=str(uuid4()),
            login_id=str(uuid4()),
            email="denied@example.test",
            full_name="Denied fixture",
            password_hash="synthetic",
        )
        db.add(other)
        seed_company_app_access(db, ["docs"])
        if denial == "app_admission":
            db.get(CompanyAppControl, "docs").enabled = False
        db.commit()
        other_id = other.id
    # This isolated caller retains existing Core auth/ACL reads. It does not claim
    # the restricted Source role can run the whole HTTP authentication service.
    with Session(c.world.engine) as db, prepared_source_projection(db) as journal:
        user = db.get(User, other_id)
        with pytest.raises(HTTPException) as error:
            create_native_page(
                db,
                user=user,
                principal=user_principal(user_id=user.id, source="test"),
                command=CreateNativePageCommand(item_id="prepared-doc", title="Forbidden"),
            )
        assert error.value.status_code == (403 if denial == "app_admission" else 404)
        assert journal.receipts == ()
        db.rollback()
    assert counts(c.world) == (0, 0, 0, 0, 0)
