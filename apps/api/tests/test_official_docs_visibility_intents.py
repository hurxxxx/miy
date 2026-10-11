"""New Docs visibility producers use the existing source/Core transaction boundary."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import User, utcnow_naive
from miy_api.domains.docs import access_grants, rag_sync
from miy_api.domains.docs.models import DocMeetingAccess, NativeDoc
from miy_api.domains.meeting.models import Meeting, MeetingDocLink
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
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


@pytest.fixture(autouse=True)
def no_external_publication(monkeypatch):
    from miy_api.domains.search import outbox
    from miy_api.domains.rag import job_publication

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


@pytest.mark.parametrize("producer", ["new_grant", "existing_grant", "revoke", "meeting"])
def test_four_visibility_production_points_have_source_intents(world, producer):
    context = seed(world, grants=producer in {"existing_grant", "revoke"})
    with Session(world.engine) as db:
        if producer in {"new_grant", "existing_grant"}:
            grant(db, world, context, access_level="edit")
            expected = context.docs[:1]
        elif producer == "revoke":
            assert (
                access_grants.revoke_doc_grants_for_meeting(
                    db,
                    meeting_id=context.meeting,
                    revoked_by_user_id=world.user_id,
                    reason="meeting_deleted",
                )
                == 2
            )
            expected = context.docs
        else:
            rag_sync.enqueue_meeting_visibility_recompute(
                db, meeting_id=context.meeting, doc_ids=context.docs
            )
            expected = context.docs
        assert_fenced(db, expected)
        db.commit()
        assert_fenced(db, expected)


@pytest.mark.parametrize("rag_enabled", [False, True])
def test_meeting_fanout_deduplicates_missing_and_preserves_captured_deleted_meeting_ids(
    world, monkeypatch, rag_enabled
):
    context = seed(world)
    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=rag_enabled))
    with Session(world.engine) as db:
        meeting = db.get(Meeting, context.meeting)
        meeting.notes_doc_id = context.docs[0]
        db.add(
            MeetingDocLink(
                id=str(uuid4()),
                meeting_id=context.meeting,
                doc_id=context.docs[1],
                added_by_id=world.user_id,
            )
        )
        db.flush()
        captured = rag_sync.collect_meeting_visibility_doc_ids(db, meeting_id=context.meeting)
        assert captured == sorted(context.docs)
        for row in db.scalars(select(MeetingDocLink)):
            db.delete(row)
        db.delete(meeting)
        db.flush()
        rag_sync.enqueue_meeting_visibility_recompute(
            db, meeting_id=context.meeting, doc_ids=[*captured, captured[0], "missing", ""]
        )
        assert_fenced(db, context.docs, rag=rag_enabled)
        db.commit()
        assert db.get(Meeting, context.meeting) is None
        assert_fenced(db, context.docs, rag=rag_enabled)


@pytest.mark.parametrize("mutation", ["attendee", "attachment", "meeting", "expiry"])
def test_grant_batch_changes_emit_once_per_document(world, mutation):
    context = seed(world, grants=True)
    with Session(world.engine) as db:
        # Another grant for the same document is a separate ACL row, not a second document.
        db.add(
            DocMeetingAccess(
                id=str(uuid4()),
                doc_id=context.docs[0],
                user_id=world.user_id,
                granted_by_user_id=world.user_id,
                granted_by_meeting_id=context.meeting,
                reason="meeting_attendee",
            )
        )
        db.commit()
        args = dict(meeting_id=context.meeting, revoked_by_user_id=world.user_id, reason="removed")
        if mutation == "attendee":
            count = access_grants.revoke_doc_grants_for_meeting_attendee(
                db, user_id=context.recipient, **args
            )
            expected = context.docs
            assert count == 2
        elif mutation == "attachment":
            count = access_grants.revoke_doc_grants_for_attachment(
                db, doc_id=context.docs[0], **args
            )
            expected = context.docs[:1]
            assert count == 2
        elif mutation == "meeting":
            count = access_grants.revoke_doc_grants_for_meeting(db, **args)
            expected = context.docs
            assert count == 3
        else:
            end = utcnow_naive() + timedelta(days=1)
            count = access_grants.bump_doc_grant_expiry_for_meeting(
                db, meeting_id=context.meeting, new_end_at=end
            )
            assert count == 3
            assert all(
                g.expires_at == end + timedelta(days=7)
                for g in db.scalars(select(DocMeetingAccess))
            )
            expected = context.docs
        assert_fenced(db, expected)
        db.commit()


def test_notes_grant_and_current_acl_expiry_revocation_remain_source_owned(world):
    from dev_accounts import configure_company_app_access
    from miy_api.domains.auth.access import ensure_seed_data
    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.meeting.notes_lifecycle import grant_notes_doc_to_attendee
    from miy_api.domains.source_access import SourceAclPolicy

    context = seed(world)
    with Session(world.engine) as db:
        ensure_seed_data(db)
        configure_company_app_access(db, app_ids=["docs", "meeting"])
        user = db.get(User, context.recipient)
        policy = SourceAclPolicy.for_user(db, user=user)
        assert not policy.can_read_resource("docs_native_doc", context.docs[0])
        grant_notes_doc_to_attendee(
            db,
            meeting=db.get(Meeting, context.meeting),
            doc=db.get(NativeDoc, context.docs[0]),
            attendee_user=user,
            granted_by_user_id=world.user_id,
        )
        assert_fenced(db, context.docs[:1])
        assert policy.can_read_resource("docs_native_doc", context.docs[0])
        control = db.get(CompanyAppControl, "docs")
        control.enabled = False
        db.flush()
        assert not policy.can_read_resource("docs_native_doc", context.docs[0])
        control.enabled = True
        db.flush()
        assert policy.can_read_resource("docs_native_doc", context.docs[0])
        row = db.scalar(select(DocMeetingAccess))
        assert row.access_level == "edit" and row.expires_at is None
        grant(db, world, context, expires_at=utcnow_naive() - timedelta(seconds=1))
        assert not policy.can_read_resource("docs_native_doc", context.docs[0])
        grant(db, world, context, expires_at=utcnow_naive() + timedelta(days=1))
        assert policy.can_read_resource("docs_native_doc", context.docs[0])
        access_grants.revoke_doc_grants_for_meeting_attendee(
            db,
            meeting_id=context.meeting,
            user_id=context.recipient,
            revoked_by_user_id=world.user_id,
            reason="removed",
        )
        assert not policy.can_read_resource("docs_native_doc", context.docs[0])
        assert len(events(db)) == 4
        db.commit()


@pytest.mark.parametrize("failure", ["after_accept", "drained"])
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


def test_cached_document_refreshed_and_trashed_visibility_never_resurrects(world):
    from miy_api.domains.rag.contracts import RagSyncOperation

    context = seed(world)
    with Session(world.engine) as cached:
        old = cached.get(NativeDoc, context.docs[0])
        assert old.trashed_at is None
        with Session(world.engine) as deletion:
            doc = deletion.get(NativeDoc, old.id)
            doc.trashed_at = utcnow_naive()
            rag_sync.enqueue_native_doc_rag_sync(
                deletion, doc=doc, operation=RagSyncOperation.DELETE
            )
            deletion.commit()
        grant(cached, world, context)
        assert old.trashed_at is not None
        assert_fenced(cached, [old.id, old.id], operation="delete")
        cached.commit()
        assert (
            cached.get(RetrievalProjectionHead, ("docs_native_doc", old.id)).desired_state
            == "deleted"
        )


def test_visibility_waits_for_inflight_trash_then_keeps_its_tombstone(world):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import text
    from miy_api.domains.rag.contracts import RagSyncOperation
    from test_official_writer_fence import wait_for_blockers

    context = seed(world)
    started = Event()
    pids = []

    def visibility():
        with Session(world.engine) as db:
            pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            grant(db, world, context)
            db.commit()

    with Session(world.engine) as deleting, ThreadPoolExecutor(max_workers=1) as pool:
        doc = deleting.get(NativeDoc, context.docs[0])
        doc.trashed_at = utcnow_naive()
        deleting.flush()
        blocker = deleting.scalar(text("SELECT pg_backend_pid()"))
        pending = pool.submit(visibility)
        try:
            assert started.wait(5)
            wait_for_blockers(lambda: Session(world.engine), pids[0], {blocker})
            rag_sync.enqueue_native_doc_rag_sync(
                deleting, doc=doc, operation=RagSyncOperation.DELETE
            )
            deleting.commit()
            pending.result(timeout=5)
        finally:
            deleting.rollback()
    with Session(world.engine) as db:
        assert_fenced(db, [context.docs[0], context.docs[0]], operation="delete")
        assert [event.source_revision for event in events(db)] == [1, 2]


def test_existing_legacy_scope_job_is_not_rewritten_or_claimed_complete(world):
    context = seed(world)
    with Session(world.engine) as db:
        old = RagVisibilityRecomputeJob(
            id=str(uuid4()),
            scope_type="meeting",
            scope_id=context.meeting,
            cursor={"doc_ids": context.docs},
            status="pending",
        )
        db.add(old)
        db.commit()
        rag_sync.enqueue_meeting_visibility_recompute(
            db, meeting_id=context.meeting, doc_ids=context.docs
        )
        db.commit()
        db.refresh(old)
        assert old.status == "pending" and old.cursor == {"doc_ids": context.docs}
        assert db.scalar(select(func.count()).select_from(RagVisibilityRecomputeJob)) == 1
        assert len(events(db)) == 2


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
