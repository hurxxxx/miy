"""New Docs visibility producers use the existing source/Core transaction boundary."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import world as world

from miy_api.domains.auth.models import User, utcnow_naive
from miy_api.domains.docs import access_grants, rag_sync
from miy_api.domains.docs.models import DocMeetingAccess, NativeDoc
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob
from miy_api.domains.retrieval import official_projection_ingress as ingress
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.search.models import SearchIndexJob


@pytest.fixture(autouse=True)
def no_external_publication(monkeypatch):
    from miy_api.domains.rag import job_publication
    from miy_api.domains.search import outbox

    monkeypatch.setattr(outbox, "_publish_job", lambda *a, **k: None)
    monkeypatch.setattr(job_publication, "publish_rag_job_publication", lambda *a, **k: None)
    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True))
    if hasattr(rag_sync, "get_settings"):
        monkeypatch.setattr(rag_sync, "get_settings", lambda: SimpleNamespace(rag_enabled=True))


def seed(world, *, grants=False):
    recipient = str(uuid4())
    partition_id = str(uuid4())
    meeting_id = str(uuid4())
    doc_ids = [str(uuid4()), str(uuid4())]
    with Session(world.engine) as db:
        db.add(
            User(
                id=recipient,
                login_id=recipient,
                email="visibility@example.test",
                full_name="Synthetic reader",
                password_hash="synthetic",
            )
        )
        db.add(
            RetrievalPartition(
                id=partition_id,
                source_namespace="docs",
                candidate_scope_kind="company",
                is_default_ingest=True,
            )
        )
        db.flush()
        db.add_all(
            [
                NativeDoc(
                    id=id_,
                    title="Visibility source",
                    owner_id=world.user_id,
                    retrieval_partition_id=partition_id,
                )
                for id_ in doc_ids
            ]
        )
        db.add(
            Meeting(
                id=meeting_id,
                title="Visibility meeting",
                organizer_id=world.user_id,
                start_at=utcnow_naive(),
                end_at=utcnow_naive(),
            )
        )
        db.flush()
        if grants:
            db.add_all(
                [
                    DocMeetingAccess(
                        id=str(uuid4()),
                        doc_id=id_,
                        user_id=recipient,
                        granted_by_user_id=world.user_id,
                        granted_by_meeting_id=meeting_id,
                        reason="meeting_attendee",
                    )
                    for id_ in doc_ids
                ]
            )
        db.commit()
    return SimpleNamespace(
        recipient=recipient, meeting=meeting_id, docs=doc_ids, partition=partition_id
    )


def grant(db, world, context, doc_id=None, **kwargs):
    return access_grants.grant_doc_access(
        db,
        doc_id=doc_id or context.docs[0],
        user_id=context.recipient,
        granted_by_user_id=world.user_id,
        granted_by_meeting_id=context.meeting,
        reason="meeting_attendee",
        **kwargs,
    )


def events(db):
    return list(
        db.scalars(
            select(OfficialProjectionOutbox).order_by(
                OfficialProjectionOutbox.resource_id, OfficialProjectionOutbox.source_revision
            )
        )
    )


def assert_fenced(db, expected_docs, *, rag=True, operation="visibility_update"):
    source = events(db)
    assert [event.resource_id for event in source] == sorted(expected_docs)
    assert all(event.resource_type == "docs_native_doc" for event in source)
    assert db.scalar(select(func.count()).select_from(OfficialProjectionReceipt)) == len(source)
    search = list(db.scalars(select(SearchIndexJob)))
    sync = list(db.scalars(select(RagSyncJob)))
    assert len(search) == len(set(expected_docs))
    assert len(sync) == (len(set(expected_docs)) if rag else 0)
    assert db.scalar(select(func.count()).select_from(RagVisibilityRecomputeJob)) == 0
    for job in [*search, *sync]:
        ref = db.get(RetrievalProjectionEvent, job.projection_event_sequence)
        resource_id = job.entity_id if isinstance(job, SearchIndexJob) else job.resource_id
        assert ref.resource_id == resource_id
        assert ref.projection_version == job.projection_version
        assert ref.retrieval_partition_id == job.retrieval_partition_id
        assert ref.desired_state == ("deleted" if operation == "delete" else "active")
        if isinstance(job, RagSyncJob):
            assert job.operation == operation
        else:
            assert job.operation == ("delete" if operation == "delete" else "upsert")


@pytest.mark.parametrize("failure", ["receipt"])
def test_grant_intent_core_jobs_and_receipt_rollback_together(world, monkeypatch, failure):
    from sqlalchemy.exc import DBAPIError
    from test_official_writer_roles import BASE, move

    context = seed(world)
    if failure == "drained":
        move(world, BASE, "active", state="draining")
        expected_error = DBAPIError
    else:
        original = rag_sync.deliver_projection_intent

        def fail(db, **kwargs):
            original(db, **kwargs)
            assert_fenced(db, context.docs[:1])
            raise RuntimeError("synthetic failure after acceptance")

        monkeypatch.setattr(rag_sync, "deliver_projection_intent", fail)
        expected_error = RuntimeError
    with Session(world.engine) as db:
        with pytest.raises(expected_error) as caught:
            grant(db, world, context)
        if failure == "drained":
            assert caught.value.orig.sqlstate == "55000"
        db.rollback()
        for model in (
            DocMeetingAccess,
            OfficialProjectionOutbox,
            OfficialProjectionReceipt,
            RetrievalProjectionHead,
            RetrievalProjectionEvent,
            SearchIndexJob,
            RagSyncJob,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.get(NativeDoc, context.docs[0]).title == "Visibility source"


def test_concurrent_new_grants_share_fk_lock_without_upgrade_deadlock(world, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import event

    context = seed(world)
    original = access_grants.enqueue_native_doc_visibility
    both_flushed = Barrier(2)

    def after_fk_flush(db, **kwargs):
        both_flushed.wait(timeout=10)
        original(db, **kwargs)

    monkeypatch.setattr(access_grants, "enqueue_native_doc_visibility", after_fk_flush)

    def create(recipient):
        with Session(world.engine) as db:
            access_grants.grant_doc_access(
                db,
                doc_id=context.docs[0],
                user_id=recipient,
                granted_by_user_id=world.user_id,
                granted_by_meeting_id=context.meeting,
                reason="meeting_attendee",
            )
            db.commit()

    observed_locks = []

    def inspect_lock(_conn, _cursor, statement, *_args):
        if "FROM docs_native_docs" in statement and "FOR " in statement:
            observed_locks.append(statement)

    event.listen(world.engine, "before_cursor_execute", inspect_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [
                pool.submit(create, recipient) for recipient in (world.user_id, context.recipient)
            ]
            for result in pending:
                result.result(timeout=15)
    finally:
        event.remove(world.engine, "before_cursor_execute", inspect_lock)
    assert len(observed_locks) == 2
    assert all("FOR NO KEY UPDATE" in statement for statement in observed_locks)
    with Session(world.engine) as db:
        assert_fenced(db, [context.docs[0], context.docs[0]])
        assert [event.source_revision for event in events(db)] == [1, 2]
        assert db.scalar(select(func.count()).select_from(DocMeetingAccess)) == 2
