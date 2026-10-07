"""Source transport and Core acceptance on an owned PostgreSQL, not a consumer."""

from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

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
    emit_and_accept_projection,
)
from miy_api.domains.retrieval.official_projection_ingress import (
    accept_projection_intent,
    lookup_projection_receipt,
    pending_projection_intents,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import record_projection_event
from miy_api.domains.search.models import SearchIndexJob
from test_official_writer_roles import ACTIVE, activate, denied, sa_dsn
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


@pytest.fixture(autouse=True)
def no_external_publication(monkeypatch):
    from miy_api.domains.search import outbox
    from miy_api.domains.rag import job_publication

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


def test_migration_models_and_legacy_atomic_bridge(world):
    from miy_api.domains.official_apps.writer_contracts import (
        COVERED_SOURCE_TABLES,
        WRITER_TRANSPORT_TABLES,
    )

    intent = seed(world)
    with Session(world.engine) as db:
        db.get(Meeting, intent.resource_id).title = "Changed"
        event = emit_and_accept_projection(db, intent=intent)
        assert event.projection_version == 1
        assert counts(db) == (1, 1, 1, 1)
        db.rollback()
        assert counts(db) == (0, 0, 0, 0)
        assert db.get(Meeting, intent.resource_id).title == "Original"
        emit_and_accept_projection(db, intent=intent)
        db.commit()
        assert counts(db) == (1, 1, 1, 1)
    schema = inspect(world.engine)
    for model in (OfficialProjectionOutbox, OfficialProjectionReceipt):
        assert {c["name"]: c["nullable"] for c in schema.get_columns(model.__tablename__)} == {
            c.name: c.nullable for c in model.__table__.columns
        }
    with world.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
        ).fetchone()[0] == len(COVERED_SOURCE_TABLES) + len(WRITER_TRANSPORT_TABLES)
        for table in ("official_projection_outbox", "official_projection_receipts"):
            for statement in (
                f"UPDATE {table} SET resource_id=resource_id",
                f"DELETE FROM {table}",
                f"TRUNCATE {table} CASCADE",
            ):
                denied(conn, statement, "55000")


def test_exact_replay_does_not_repeat_source_or_core_version(world):
    intent = seed(world)
    identity = uuid4()
    event = append(world, intent, identity)
    assert append(world, intent, identity) == event
    assert accept(world, event) == accept(world, event)
    with Session(world.engine) as db:
        assert counts(db) == (1, 1, 1, 1)
        with pytest.raises(ProjectionOutboxError, match="event_conflict"):
            append_projection_intent(
                db,
                intent=intent.model_copy(update={"content_checksum": "different"}),
                event_id=identity,
            )
        db.rollback()
        with pytest.raises(ProjectionOutboxError, match="event_conflict"):
            accept_projection_intent(db, event_id=event[0], expected_digest="0" * 64)
        assert counts(db) == (1, 1, 1, 1)


def test_source_revision_and_existing_core_version_are_separate(world):
    intent = seed(world)
    with Session(world.engine) as db:
        for _ in range(3):
            record_projection_event(db, **intent.model_dump(mode="json", exclude={"operation"}))
        db.commit()
    event = append(world, intent)
    assert event[2] == 1
    accept(world, event)
    with Session(world.engine) as db:
        assert (
            db.get(RetrievalProjectionHead, ("meeting", intent.resource_id)).projection_version == 4
        )


def test_out_of_order_gap_supersession_and_tombstone_never_resurrect(world):
    intent = seed(world)
    old = append(world, intent)
    tombstone = intent.model_copy(
        update={"change_kind": "delete", "desired_state": "deleted", "operation": "delete"}
    )
    deleted = append(world, tombstone)
    with Session(world.engine) as db:
        with pytest.raises(ProjectionOutboxError, match="revision_gap"):
            accept_projection_intent(db, event_id=deleted[0], expected_digest=deleted[1])
        db.rollback()
        assert counts(db) == (2, 0, 0, 0)
    assert accept(world, old) == ("superseded", None)
    assert accept(world, deleted)[0] == "accepted"
    assert accept(world, old) == ("superseded", None)
    with Session(world.engine) as db:
        assert (
            db.get(RetrievalProjectionHead, ("meeting", intent.resource_id)).desired_state
            == "deleted"
        )
        assert counts(db) == (2, 2, 1, 1)


@pytest.mark.parametrize("change", ["partition", "retired", "wrong_namespace", "source_missing"])
def test_latest_live_source_partition_revalidated(world, change):
    intent = seed(world)
    event = append(world, intent)
    with Session(world.engine) as db:
        if change == "source_missing":
            db.delete(db.get(Meeting, intent.resource_id))
        elif change == "partition":
            other = RetrievalPartition(
                source_namespace="meeting", candidate_scope_kind="company", is_default_ingest=False
            )
            db.add(other)
            db.flush()
            db.get(Meeting, intent.resource_id).retrieval_partition_id = other.id
        else:
            row = db.get(RetrievalPartition, str(intent.retrieval_partition_id))
            if change == "retired":
                row.state = "retired"
            else:
                row.source_namespace = "docs"
        db.commit()
    with Session(world.engine) as db:
        with pytest.raises(ProjectionOutboxError):
            accept_projection_intent(db, event_id=event[0], expected_digest=event[1])
        db.rollback()
        assert counts(db) == (1, 0, 0, 0)


def test_acceptance_failure_rolls_back_event_head_jobs_and_receipt(world, monkeypatch):
    intent = seed(world)
    event = append(world, intent)
    from miy_api.domains.retrieval import official_projection_ingress as ingress

    original = ingress._stage_jobs

    def fail(db, intent, event):
        original(db, intent, event)
        raise RuntimeError("synthetic failure after jobs")

    monkeypatch.setattr(ingress, "_stage_jobs", fail)
    with Session(world.engine) as db:
        with pytest.raises(RuntimeError):
            accept_projection_intent(db, event_id=event[0], expected_digest=event[1])
        db.rollback()
        assert counts(db) == (1, 0, 0, 0)
        assert db.get(RetrievalProjectionHead, ("meeting", intent.resource_id)) is None
    monkeypatch.setattr(ingress, "_stage_jobs", original)
    assert accept(world, event)[0] == "accepted"


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


def test_hardened_source_role_can_append_not_accept_or_forge_revision(world):
    intent = seed(world)
    runtime, owner, oid = activate(world)
    from psycopg.conninfo import make_conninfo
    from test_official_writer_roles import PASSWORD

    engine = create_engine(sa_dsn(make_conninfo(world.dsn, user=runtime, password=PASSWORD)))
    try:
        with Session(engine) as db:
            event = append_projection_intent(db, intent=intent)
            event_id = event.event_id
            assert (
                event.producer_role_oid == oid
                and event.producer_role_name == runtime
                and event.producer_generation == ACTIVE.generation
            )
            db.commit()
            with pytest.raises(ProjectionOutboxError, match="core_authority"):
                accept_projection_intent(db, event_id=event_id, expected_digest=intent.digest())
            db.rollback()
        with world.connect(runtime) as conn:
            assert (
                conn.execute("SELECT count(*) FROM official_projection_outbox").fetchone()[0] == 1
            )
            for table in (
                "official_projection_receipts",
                "retrieval_projection_heads",
                "retrieval_projection_events",
                "search_index_jobs",
                "rag_sync_jobs",
            ):
                denied(conn, f"INSERT INTO {table} DEFAULT VALUES")
            for query in (
                "UPDATE official_projection_outbox SET source_revision=9",
                "DELETE FROM official_projection_outbox",
                "TRUNCATE official_projection_outbox",
                "SELECT * FROM official_projection_receipts",
            ):
                denied(conn, query)
            with pytest.raises(psycopg.Error) as error:
                conn.execute(
                    "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,99,%s,%s)",
                    [
                        uuid4(),
                        intent.resource_type,
                        intent.resource_id,
                        intent.canonical(),
                        intent.digest(),
                    ],
                )
            assert error.value.sqlstate == "23514"
            conn.rollback()
        # Core acceptance is permitted independently from source writer privileges.
        assert accept(world, (event_id, intent.digest(), 1))[0] == "accepted"
    finally:
        engine.dispose()


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


@pytest.mark.parametrize("isolation", ["AUTOCOMMIT", "REPEATABLE READ", "SERIALIZABLE"])
def test_projection_control_requires_current_atomic_transaction(world, isolation):
    intent = seed(world)
    with Session(world.engine.execution_options(isolation_level=isolation)) as db:
        with pytest.raises(ProjectionOutboxError, match="requires_read_committed"):
            append_projection_intent(db, intent=intent)
        db.rollback()
    with Session(world.engine) as db:
        assert counts(db) == (0, 0, 0, 0)


def test_hardened_migration_requires_drain_and_explicit_new_principal(world, monkeypatch):
    from alembic import command
    from miy_api.domains.official_apps import writer_roles
    from miy_api.domains.official_apps.writer import WriterIdentity
    from miy_api.domains.official_apps.writer_roles import install_role_guard, revoke_principal
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import BASE, prepare, move, sa_dsn

    config = _migration_config(sa_dsn(world.dsn))
    previous = "official_source_writer_20261007"
    revision = "official_projection_20261007"
    # This is the historical 88→89 transition, independent of newer transports.
    monkeypatch.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ("official_projection_outbox",))
    command.downgrade(config, previous)
    with monkeypatch.context() as old:
        old.setattr(writer_roles, "WRITER_TRANSPORT_TABLES", ())
        runtime, owner, oid = activate(world)
    with pytest.raises(RuntimeError, match="requires_draining"):
        command.upgrade(config, revision)
    draining = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    command.upgrade(config, revision)
    assert prepare(world, runtime, ACTIVE, draining, "draining") == oid
    with world.connect() as conn:
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_projection_outbox','INSERT')", [runtime]
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 89
        )
    identity = WriterIdentity(BASE.scope, "legacy", 5, "sha256:" + "c" * 64)
    new_role = world.role()
    prepare(world, new_role, identity, draining, "draining")
    with Session(world.engine) as db:
        install_role_guard(db, world.actor, guard_owner=owner, expected=draining)
        revoke_principal(
            db, world.actor, role_oid=oid, expected=draining, expected_state="draining"
        )
        db.commit()
    move(world, draining, "draining", state="active", artifact=identity.artifact)
    with world.connect(new_role) as conn:
        assert conn.execute(
            "SELECT has_table_privilege(session_user,'official_projection_outbox','INSERT')"
        ).fetchone()[0]
        conn.execute("UPDATE meetings SET title=title WHERE false")
    with world.connect(runtime) as conn:
        denied(conn, "UPDATE meetings SET title=title WHERE false", "55000")
    with pytest.raises(RuntimeError, match="explicit_retirement"):
        command.downgrade(config, previous)


def test_legacy_migration_roundtrip_preserves_business_rows_and_refuses_intent_loss(world):
    from alembic import command
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import sa_dsn

    intent = seed(world)
    config = _migration_config(sa_dsn(world.dsn))
    expanded = "official_projection_20261007"
    for revision in (
        "official_source_writer_20261007",
        expanded,
        "official_source_writer_20261007",
        expanded,
    ):
        command.downgrade(config, revision) if revision != expanded else command.upgrade(
            config, revision
        )
        with Session(world.engine) as db:
            assert db.get(Meeting, intent.resource_id).title == "Original"
    append(world, intent)
    with pytest.raises(RuntimeError, match="record_retention"):
        command.downgrade(config, "official_source_writer_20261007")
    with Session(world.engine) as db:
        assert counts(db) == (1, 0, 0, 0)


@pytest.mark.parametrize(
    "hazard", ["stamp_disabled", "stamp_public", "stamp_invoker", "immutable_disabled"]
)
def test_new_principal_requires_exact_transport_guard_before_grants(world, hazard):
    from miy_api.domains.official_apps.writer import WriterControlError
    from test_official_writer_roles import prepare

    with world.connect() as conn:
        query = {
            "stamp_disabled": "ALTER TABLE official_projection_outbox DISABLE TRIGGER miy_official_projection_stamp",
            "stamp_public": "GRANT EXECUTE ON FUNCTION miy_stamp_official_projection_event() TO PUBLIC",
            "stamp_invoker": "ALTER FUNCTION miy_stamp_official_projection_event() SECURITY INVOKER",
            "immutable_disabled": "ALTER TABLE official_projection_receipts DISABLE TRIGGER miy_official_projection_immutable",
        }[hazard]
        conn.execute(query)
    role = world.role()
    with pytest.raises(
        WriterControlError, match="transport_guard_contract|function_privilege_forbidden"
    ):
        prepare(world, role)
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_projection_outbox','INSERT')", [role]
        ).fetchone()[0]


@pytest.mark.parametrize("files_active", [False, True])
def test_legacy_four_hooks_preserve_existing_job_rules(world, monkeypatch, files_active):
    from types import SimpleNamespace
    from miy_api.domains.docs.models import NativeDoc
    from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
    from miy_api.domains.files.models import FileManagerFile
    from miy_api.domains.files.rag_sync import enqueue_file_retrieval_sync
    from miy_api.domains.files import retrieval_contract
    from miy_api.domains.meeting.search_hooks import enqueue_meeting_search_index
    from miy_api.domains.pms.models import Task, TaskList
    from miy_api.domains.pms.search_hooks import enqueue_task_search_index
    from miy_api.domains.rag.contracts import RagSyncOperation
    from miy_api.domains.rag.models import RagSyncJob
    from miy_api.domains.retrieval import official_projection_ingress as ingress

    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True))
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", files_active)
    meeting_intent = seed(world)
    with Session(world.engine) as db:
        partitions = {}
        for namespace in ("docs", "pms", "files"):
            partition = RetrievalPartition(
                source_namespace=namespace, candidate_scope_kind="company", is_default_ingest=True
            )
            db.add(partition)
            db.flush()
            partitions[namespace] = partition.id
        doc = NativeDoc(
            id="projection-doc",
            title="Original",
            owner_id=world.user_id,
            retrieval_partition_id=partitions["docs"],
        )
        file = FileManagerFile(
            id="projection-file",
            filename="synthetic.txt",
            storage_key="synthetic/only",
            owner_id=world.user_id,
            retrieval_partition_id=partitions["files"],
        )
        task_list = TaskList(
            id="projection-list", key="projection", name="Original", created_by_id=world.user_id
        )
        db.add_all([doc, file, task_list])
        db.flush()
        task = Task(
            id="projection-task",
            task_number=1,
            list_id=task_list.id,
            title="Original",
            reporter_id=world.user_id,
            retrieval_partition_id=partitions["pms"],
        )
        db.add(task)
        db.flush()
        enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.VISIBILITY_UPDATE)
        enqueue_file_retrieval_sync(db, file=file, operation=RagSyncOperation.UPSERT)
        enqueue_task_search_index(db, task=task)
        enqueue_meeting_search_index(db, meeting=db.get(Meeting, meeting_intent.resource_id))
        assert counts(db) == (4, 4, 4, 3)
        jobs = list(db.scalars(select(RagSyncJob)))
        assert len(jobs) == (2 if files_active else 1)
        doc_job = next(j for j in jobs if j.resource_id == doc.id)
        assert doc_job.operation == "visibility_update"
        doc_event = db.scalar(
            select(RetrievalProjectionEvent).where(RetrievalProjectionEvent.resource_id == doc.id)
        )
        assert doc_event.change_kind == "content"
        enqueue_native_doc_rag_sync(db, doc=doc, operation=RagSyncOperation.DELETE)
        enqueue_file_retrieval_sync(db, file=file, operation=RagSyncOperation.DELETE)
        enqueue_task_search_index(db, task=task, operation="delete")
        enqueue_meeting_search_index(
            db, meeting=db.get(Meeting, meeting_intent.resource_id), operation="delete"
        )
        assert counts(db) == (8, 8, 8, 4 if files_active else 3)
        assert all(
            head.desired_state == "deleted" and head.projection_version == 2
            for head in db.scalars(select(RetrievalProjectionHead))
        )
        assert all(job.operation == "delete" for job in db.scalars(select(SearchIndexJob)))
        assert all(job.operation == "delete" for job in db.scalars(select(RagSyncJob)))
        # Existing current-ACL loaders remain authoritative; intent is not an ACL grant.
        db.rollback()
        assert counts(db) == (0, 0, 0, 0)


@pytest.mark.parametrize("fail_truncate", [False, True])
def test_disposable_fixture_reset_restores_immutable_triggers(world, fail_truncate):
    from sqlalchemy import event as sa_event
    from conftest import _truncate_test_database

    intent = seed(world)
    append(world, intent)

    def reject_truncate(_connection, _cursor, statement, *_args):
        if statement.startswith("TRUNCATE TABLE"):
            raise RuntimeError("synthetic reset failure")

    if fail_truncate:
        sa_event.listen(world.engine, "before_cursor_execute", reject_truncate)
    try:
        if fail_truncate:
            with pytest.raises(RuntimeError, match="reset failure"):
                _truncate_test_database(world.engine)
        else:
            _truncate_test_database(world.engine)
    finally:
        if fail_truncate:
            sa_event.remove(world.engine, "before_cursor_execute", reject_truncate)
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_projection_immutable' AND tgenabled='O'"
            ).fetchone()[0]
            == 2
        )
        assert conn.execute("SELECT count(*) FROM official_projection_outbox").fetchone()[0] == int(
            fail_truncate
        )
        denied(conn, "TRUNCATE official_projection_outbox CASCADE", "55000")


def test_concurrent_acceptance_has_one_receipt_and_one_core_event(world):
    from concurrent.futures import ThreadPoolExecutor
    from test_official_writer_roles import wait_for_blocker

    intent = seed(world)
    event = append(world, intent)
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
    with Session(world.engine) as db:
        assert counts(db) == (1, 1, 1, 1)


def test_acceptance_refreshes_cached_core_head_after_other_core_writer(world):
    intent = seed(world)
    payload = intent.model_dump(mode="json", exclude={"operation"})
    with Session(world.engine) as writer:
        record_projection_event(writer, **payload)
        writer.commit()
    with Session(world.engine) as cached:
        head = cached.get(RetrievalProjectionHead, ("meeting", intent.resource_id))
        assert head.projection_version == 1
        with Session(world.engine) as writer:
            record_projection_event(writer, **payload)
            writer.commit()
        event = append(world, intent)
        receipt = accept_projection_intent(cached, event_id=event[0], expected_digest=event[1])
        cached.commit()
        assert head.projection_version == 3
        assert (
            cached.get(RetrievalProjectionEvent, receipt.core_event_sequence).projection_version
            == 3
        )


def test_historical_intent_can_be_accepted_after_producer_revoke_but_cannot_append(world):
    from psycopg.conninfo import make_conninfo
    from miy_api.domains.official_apps.writer_roles import revoke_principal
    from test_official_writer_roles import PASSWORD, move

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


@pytest.mark.parametrize("resource_id", [" source-meeting", "source-meeting ", " ", "\x00"])
def test_source_identity_cannot_alias_core_canonical_key(resource_id):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProjectionIntent(
            resource_type="meeting",
            resource_id=resource_id,
            retrieval_partition_id=uuid4(),
            change_kind="content",
            desired_state="active",
            operation="upsert",
        )


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
