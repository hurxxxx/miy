"""Real Source-only hooks and separately owned Core transactions; no live broker."""

from types import SimpleNamespace

import pytest
from psycopg.conninfo import make_conninfo
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.docs.rag_sync import (
    enqueue_native_doc_rag_sync,
)
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.meeting.search_hooks import enqueue_meeting_search_index
from miy_api.domains.official_apps.projection_delivery import (
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
    RetrievalProjectionEvent,
)
from miy_api.domains.retrieval.official_projection_consumer import (
    run_projection_consumer_once,
)
from miy_api.domains.search.models import SearchIndexJob
from test_official_partition_reader import prepared as prepared
from test_official_writer_roles import (
    BASE as BASE,
    PASSWORD as PASSWORD,
    sa_dsn as sa_dsn,
    wait_for_blocker as wait_for_blocker,
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


@pytest.mark.parametrize("resource", ["docs"])
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


@pytest.mark.parametrize("savepoint", [False])
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


def test_default_legacy_hook_keeps_synchronous_core_and_publication(world, publications):
    with Session(world.engine) as db:
        doc = NativeDoc(id="legacy-doc", owner_id=world.user_id, title="Legacy")
        db.add(doc)
        enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.UPSERT)
        db.commit()
    assert counts(world)[:4] == (1, 1, 1, 1)
    assert publications
