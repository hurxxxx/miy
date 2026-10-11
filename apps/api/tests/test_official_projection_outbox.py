"""Source transport and Core acceptance on an owned PostgreSQL, not a consumer."""

from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import ACTIVE, activate, sa_dsn
from test_official_writer_roles import role_template as role_template
from test_official_writer_roles import world as world

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_outbox import (
    append_projection_intent,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
)
from miy_api.domains.retrieval.official_projection_ingress import (
    accept_projection_intent,
    lookup_projection_receipt,
    pending_projection_intents,
)
from miy_api.domains.search.models import SearchIndexJob


@pytest.fixture(autouse=True)
def no_external_publication(monkeypatch):
    from miy_api.domains.rag import job_publication
    from miy_api.domains.search import outbox

    monkeypatch.setattr(outbox, "_publish_job", lambda *a, **k: None)
    monkeypatch.setattr(job_publication, "publish_rag_job_publication", lambda *a, **k: None)


def seed(world, resource_id="source-meeting"):
    partition_id = str(uuid4())
    with Session(world.engine) as db:
        db.add(
            RetrievalPartition(
                id=partition_id,
                source_namespace="meeting",
                candidate_scope_kind="company",
                is_default_ingest=False,
            )
        )
        db.flush()
        db.add(
            Meeting(
                id=resource_id,
                title="Original",
                organizer_id=world.user_id,
                start_at=utcnow_naive(),
                end_at=utcnow_naive(),
                retrieval_partition_id=partition_id,
            )
        )
        db.commit()
    return ProjectionIntent(
        resource_type="meeting",
        resource_id=resource_id,
        retrieval_partition_id=partition_id,
        change_kind="content",
        desired_state="active",
        operation="upsert",
    )


def append(world, intent, event_id=None):
    with Session(world.engine) as db:
        event = append_projection_intent(db, intent=intent, event_id=event_id)
        result = (event.event_id, event.payload_digest, event.source_revision)
        db.commit()
        return result


def accept(world, event):
    with Session(world.engine) as db:
        receipt = accept_projection_intent(db, event_id=event[0], expected_digest=event[1])
        result = (receipt.status, receipt.core_event_sequence)
        db.commit()
        return result


def counts(db):
    return tuple(
        db.scalar(select(func.count()).select_from(model))
        for model in (
            OfficialProjectionOutbox,
            OfficialProjectionReceipt,
            RetrievalProjectionEvent,
            SearchIndexJob,
        )
    )


def test_commit_ack_unknown_recovers_same_event_without_business_retry(world):
    intent = seed(world)
    event = append(world, intent)
    with Session(world.engine) as db:
        receipt = accept_projection_intent(db, event_id=event[0], expected_digest=event[1])
        sequence = receipt.core_event_sequence

        def commit_then_lose_ack():
            db.commit()
            raise ConnectionError("synthetic ACK lost")

        with pytest.raises(ConnectionError):
            commit_then_lose_ack()
        db.rollback()
    with Session(world.engine) as db:
        assert lookup_projection_receipt(db, event_id=event[0]).core_event_sequence == sequence
    assert accept(world, event) == ("accepted", sequence)
    with Session(world.engine) as db:
        assert counts(db) == (1, 1, 1, 1)
        assert db.get(Meeting, intent.resource_id).title == "Original"


def test_same_uuid_concurrent_exact_and_conflicting_payload(world):
    from concurrent.futures import ThreadPoolExecutor
    from test_official_writer_roles import wait_for_blocker

    intent = seed(world)
    identifier = uuid4()
    with Session(world.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        pid = first.scalar(text("SELECT pg_backend_pid()"))
        original = append_projection_intent(first, intent=intent, event_id=identifier)
        expected = (original.event_id, original.payload_digest, original.source_revision)
        later = pool.submit(append, world, intent, identifier)
        try:
            wait_for_blocker(world, pid)
            assert not later.done()
        finally:
            first.commit()
        assert later.result(timeout=8) == expected
    event = expected
    with Session(world.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        pid = first.scalar(text("SELECT pg_backend_pid()"))
        receipt = accept_projection_intent(first, event_id=event[0], expected_digest=event[1])
        expected = (receipt.status, receipt.core_event_sequence)
        later = pool.submit(accept, world, event)
        try:
            wait_for_blocker(world, pid)
            assert not later.done()
        finally:
            first.commit()
        assert later.result(timeout=8) == expected
    with Session(world.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        other = uuid4()
        pid = first.scalar(text("SELECT pg_backend_pid()"))
        append_projection_intent(first, intent=intent, event_id=other)
        later = pool.submit(
            append, world, intent.model_copy(update={"resource_id": "other"}), other
        )
        try:
            wait_for_blocker(world, pid)
        finally:
            first.commit()
        with pytest.raises(ProjectionOutboxError, match="event_conflict"):
            later.result(timeout=8)
    with Session(world.engine) as db:
        assert counts(db) == (2, 1, 1, 1)


def test_same_resource_revision_serializes_and_pending_does_not_skip_late_commit(world):
    from concurrent.futures import ThreadPoolExecutor

    from test_official_writer_roles import wait_for_blocker

    intent = seed(world)
    other = seed(world, "other-meeting")
    with Session(world.engine) as early, ThreadPoolExecutor(max_workers=1) as pool:
        pid = early.scalar(text("SELECT pg_backend_pid()"))
        first = append_projection_intent(early, intent=intent, event_id=UUID(int=1))
        later = pool.submit(append, world, intent)
        try:
            wait_for_blocker(world, pid)
            committed = append(world, other, UUID(int=2))
            with Session(world.engine) as reader:
                assert [e.event_id for e in pending_projection_intents(reader)] == [committed[0]]
            accept(world, committed)
        finally:
            early.commit()
        assert later.result(timeout=8)[2] == 2
        with Session(world.engine) as reader:
            pending = pending_projection_intents(reader)
            assert first.event_id in {e.event_id for e in pending}
            assert {e.source_revision for e in pending} == {1, 2}


def test_source_intent_holds_writer_share_until_commit_and_drain_rejects_append(world):
    from concurrent.futures import ThreadPoolExecutor

    from test_official_writer_roles import BASE, move, wait_for_blocker

    intent = seed(world)
    with Session(world.engine) as db, ThreadPoolExecutor(max_workers=1) as pool:
        pid = db.scalar(text("SELECT pg_backend_pid()"))
        append_projection_intent(db, intent=intent)
        pending = pool.submit(move, world, BASE, "active", state="draining")
        try:
            wait_for_blocker(world, pid)
            assert not pending.done()
        finally:
            db.commit()
        pending.result(timeout=8)
    with Session(world.engine) as db:
        with pytest.raises(Exception) as error:
            append_projection_intent(db, intent=intent)
        assert error.value.orig.sqlstate == "55000"
        db.rollback()
        assert counts(db) == (1, 0, 0, 0)


def test_historical_intent_can_be_accepted_after_producer_revoke_but_cannot_append(world):
    from psycopg.conninfo import make_conninfo
    from test_official_writer_roles import PASSWORD, move

    from miy_api.domains.official_apps.writer_roles import revoke_principal

    intent = seed(world)
    runtime, _owner, oid = activate(world)
    engine = create_engine(sa_dsn(make_conninfo(world.dsn, user=runtime, password=PASSWORD)))
    try:
        with Session(engine) as db:
            event = append_projection_intent(db, intent=intent)
            event_id = event.event_id
            db.commit()
        draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
        with Session(world.engine) as core:
            revoke_principal(
                core, world.actor, role_oid=oid, expected=draining, expected_state="draining"
            )
            core.commit()
        assert accept(world, (event_id, intent.digest(), 1))[0] == "accepted"
        with Session(engine) as db:
            with pytest.raises(Exception) as error:
                append_projection_intent(db, intent=intent)
            assert error.value.orig.sqlstate == "55000"
            db.rollback()
    finally:
        engine.dispose()


def test_actual_copy_stamps_provenance_and_drain_rejects_even_empty_copy(world):
    from test_official_writer_roles import move

    intent = seed(world)
    runtime, _owner, oid = activate(world)
    identifier = uuid4()
    copy_sql = """COPY official_projection_outbox
        (event_id,resource_type,resource_id,source_revision,payload,payload_digest,
         producer_generation,producer_artifact,producer_role_oid,producer_role_name)
        FROM STDIN"""
    with world.connect(runtime) as conn:
        with conn.cursor().copy(copy_sql) as copy:
            copy.write_row(
                (
                    identifier,
                    intent.resource_type,
                    intent.resource_id,
                    1,
                    intent.canonical(),
                    intent.digest(),
                    999,
                    "sha256:" + "0" * 64,
                    1,
                    "forged",
                )
            )
        conn.commit()
        assert conn.execute(
            "SELECT producer_generation,producer_artifact,producer_role_oid,producer_role_name FROM official_projection_outbox WHERE event_id=%s",
            [identifier],
        ).fetchone() == (ACTIVE.generation, ACTIVE.artifact, oid, runtime)
        conn.commit()
        move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
        with pytest.raises(psycopg.Error) as error:
            with conn.cursor().copy(copy_sql):
                pass
        assert error.value.sqlstate == "55000"
        conn.rollback()
        assert conn.execute("SELECT count(*) FROM official_projection_outbox").fetchone()[0] == 1
