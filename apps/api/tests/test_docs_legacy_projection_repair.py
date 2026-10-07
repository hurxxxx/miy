"""Core-owned legacy Docs repair; real PostgreSQL, synthetic providers only."""

import importlib
import json
import psycopg
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from miy_api.domains.rag.models import RagSyncJob, RagVisibilityRecomputeJob
from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.auth.models import CompanyAppControl, utcnow_naive
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import lock_projection_source
from miy_api.domains.retrieval import docs_legacy_repair as repair
from miy_api.domains.retrieval.docs_legacy_repair_contracts import DocsLegacyRepairError
from miy_api.domains.retrieval.docs_legacy_repair_models import (
    DocsLegacyProjectionRepair as Receipt,
    DocsLegacyProjectionRepairTarget as Target,
)
from miy_api.domains.retrieval.models import (
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
    RetrievalPartition,
)
from miy_api.domains.retrieval.projection_fencing import record_projection_event
from miy_api.domains.search.models import SearchIndexJob
from test_official_docs_visibility_intents import seed
from test_official_writer_roles import PASSWORD, activate, denied, sa_dsn
from test_official_writer_roles import world as world, role_template as role_template
from test_official_writer_fence import wait_for_blockers
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


@pytest.fixture(autouse=True)
def no_publication(monkeypatch):
    from miy_api.core.settings import get_settings
    from miy_api.domains.search import outbox
    from miy_api.domains.rag import job_publication

    monkeypatch.setattr(outbox, "_publish_job", lambda *a, **k: None)
    monkeypatch.setattr(job_publication, "publish_rag_job_publication", lambda *a, **k: None)
    monkeypatch.setattr(get_settings(), "rag_enabled", True)


def legacy(world, kind, *, status="pending", operation="visibility_update", **extra):
    context = seed(world)
    identifier = str(uuid4())
    with Session(world.engine) as db:
        seed_company_app_access(db, ["docs", "meeting"])
        if kind == "scope":
            job = RagVisibilityRecomputeJob(
                id=identifier,
                scope_type="meeting",
                scope_id=context.meeting,
                cursor={"doc_ids": context.docs},
                status=status,
                **extra,
            )
        elif kind == "rag":
            job = RagSyncJob(
                id=identifier,
                resource_type="docs_native_doc",
                resource_id=context.docs[0],
                scope_kind="company",
                operation=operation,
                status=status,
                **extra,
            )
        else:
            job = SearchIndexJob(
                id=identifier,
                entity_type="doc",
                entity_id=context.docs[0],
                operation="delete" if operation == "delete" else "upsert",
                status=status,
                **extra,
            )
        db.add(job)
        db.commit()
    return context, identifier


def test_repair_schema_preserves_source_inventory(world):
    from miy_api.domains.official_apps.writer_contracts import (
        COVERED_SOURCE_TABLES,
        WRITER_TRANSPORT_TABLES,
    )
    from miy_api.domains.retrieval.docs_legacy_repair_models import (
        DocsLegacyProjectionRepair,
        DocsLegacyProjectionRepairTarget,
    )

    schema = inspect(world.engine)
    for model in (DocsLegacyProjectionRepair, DocsLegacyProjectionRepairTarget):
        assert {c["name"]: c["nullable"] for c in schema.get_columns(model.__tablename__)} == {
            c.name: c.nullable for c in model.__table__.columns
        }
    with world.connect() as conn:
        assert conn.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
        ).fetchone()[0] == len(COVERED_SOURCE_TABLES) + len(WRITER_TRANSPORT_TABLES)


@pytest.mark.parametrize("kind", ["scope", "rag", "search"])
def test_legacy_dispatch_converts_before_any_provider(world, monkeypatch, kind):
    context, identifier = legacy(world, kind)
    provider_calls = []
    if kind == "search":
        from miy_api.domains.search.indexing import process_search_index_job

        def provider(*_):
            provider_calls.append(True)
            raise AssertionError("legacy Docs must be converted before client construction")

        with Session(world.engine) as db:
            result = process_search_index_job(db, identifier, client_factory=provider)
    else:
        tasks = importlib.import_module("miy_worker.tasks.rag_sync")
        monkeypatch.setattr(tasks, "_db_session", lambda: Session(world.engine))
        settings = tasks.get_settings().model_copy(update={"rag_enabled": True})
        monkeypatch.setattr(tasks, "get_settings", lambda: settings)

        def provider(*_):
            provider_calls.append(True)
            raise AssertionError("legacy Docs must be converted before runtime construction")

        monkeypatch.setattr(tasks, "_rag_runtime_for_job", provider)
        if kind == "scope":
            result = tasks.recompute_visibility.run(identifier)
        else:
            result = tasks.sync_resource.run(identifier)
    assert not provider_calls
    assert result == "docs-repair-converted"
    with Session(world.engine) as db:
        assert all(
            j.projection_version
            for j in db.scalars(select(RagSyncJob).where(RagSyncJob.status == "pending"))
        )


def convert(world, kind, identifier):
    with Session(world.engine) as db:
        receipt = repair.repair_docs_legacy_job(db, kind=kind, job_id=identifier)
        result = receipt.id if receipt else None
        db.commit()
        return result


def counts(world):
    with Session(world.engine) as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                Receipt,
                Target,
                RetrievalProjectionEvent,
                OfficialProjectionOutbox,
            )
        )


@pytest.mark.parametrize("kind", ["scope", "rag", "search"])
def test_exact_replay_atomic_original_and_target_identity(world, kind):
    context, identifier = legacy(world, kind)
    receipt_id = convert(world, kind, identifier)
    expected_count = 2 if kind == "scope" else 1
    assert counts(world) == (1, expected_count, expected_count, 0)
    assert convert(world, kind, identifier) == receipt_id
    assert counts(world) == (1, expected_count, expected_count, 0)
    with Session(world.engine) as db:
        targets = list(db.scalars(select(Target)))
        assert db.get(repair._MODELS[kind], identifier).status == (
            "succeeded" if kind == "scope" else "cancelled"
        )
        assert all(
            target.search_job_id != identifier and target.rag_job_id != identifier
            for target in targets
        )
        assert all(db.get(SearchIndexJob, t.search_job_id).status == "pending" for t in targets)
        # Legitimate pending-job coalescing must not invalidate a receipt's own event.
        from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
        from miy_api.domains.rag.contracts import RagSyncOperation

        enqueue_native_doc_rag_sync(
            db, doc=db.get(NativeDoc, context.docs[0]), operation=RagSyncOperation.UPSERT
        )
        db.commit()
    before = counts(world)
    assert convert(world, kind, identifier) == receipt_id
    assert counts(world) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("projection_version", 99),
        ("content_checksum", "changed"),
        ("visibility_checksum", "changed"),
        ("resource_id", "other"),
        ("change_kind", "content"),
        ("partition", None),
    ],
)
def test_persisted_event_mutation_is_rejected_and_exact_replay_survives(world, field, value):
    context, identifier = legacy(world, "rag")
    convert(world, "rag", identifier)
    with Session(world.engine) as db:
        target = db.scalar(select(Target))
        event = db.get(RetrievalProjectionEvent, target.core_event_sequence)
        if field == "partition":
            value = str(uuid4())
            db.add(
                RetrievalPartition(
                    id=value,
                    source_namespace="docs",
                    candidate_scope_kind="company",
                    is_default_ingest=False,
                )
            )
            db.flush()
            field = "retrieval_partition_id"
        setattr(event, field, value)
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert error.value.orig.sqlstate == "23514"
        db.rollback()
    before = counts(world)
    convert(world, "rag", identifier)
    assert counts(world) == before


@pytest.mark.parametrize(
    "phase",
    ["after_event", "after_jobs", "after_flush", "commit_before", "commit_after", "rollback_error"],
)
def test_atomicity_and_unknown_commit_reconcile_same_origin(world, monkeypatch, phase):
    _, identifier = legacy(world, "scope")
    with Session(world.engine) as db:
        original_commit = db.commit
        original_rollback = db.rollback
        if phase in {"commit_before", "commit_after", "rollback_error"}:

            def commit():
                if phase == "commit_after":
                    original_commit()
                raise RuntimeError("synthetic lost ACK")

            monkeypatch.setattr(db, "commit", commit)
            if phase == "rollback_error":
                monkeypatch.setattr(
                    db,
                    "rollback",
                    lambda: (_ for _ in ()).throw(RuntimeError("synthetic rollback loss")),
                )
        elif phase in {"after_event", "after_jobs"}:
            name = "record_projection_event" if phase == "after_event" else "enqueue_rag_sync_job"
            original = getattr(repair, name)

            def fail(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("synthetic boundary failure")

            monkeypatch.setattr(repair, name, fail)
        else:
            original = repair._admission
            visits = []

            def admission(*args):
                visits.append(True)
                if len(visits) == 3:
                    raise RuntimeError("synthetic final boundary")
                return original(*args)

            monkeypatch.setattr(repair, "_admission", admission)
        with pytest.raises(DocsLegacyRepairError, match="outcome_unknown"):
            repair.dispatch_docs_legacy_repair(db, kind="scope", job_id=identifier)
        original_rollback()
    monkeypatch.undo()
    assert counts(world) == ((1, 2, 2, 0) if phase == "commit_after" else (0, 0, 0, 0))
    # Restore the fixture's no-provider publications after monkeypatch.undo.
    from miy_api.domains.search import outbox
    from miy_api.domains.rag import job_publication
    from miy_api.core.settings import get_settings

    monkeypatch.setattr(outbox, "_publish_job", lambda *a, **k: None)
    monkeypatch.setattr(job_publication, "publish_rag_job_publication", lambda *a, **k: None)
    monkeypatch.setattr(get_settings(), "rag_enabled", True)
    convert(world, "scope", identifier)
    assert counts(world) == (1, 2, 2, 0)


@pytest.mark.parametrize(
    "case,code",
    [
        ("processing", "origin_not_pending"),
        ("partial", "partial_fence"),
        ("app_disabled", "app_disabled"),
        ("rag_disabled", "rag_disabled"),
        ("missing_pointer", "partition_conflict"),
        ("retired", "partition_invalid"),
        ("namespace", "partition_invalid"),
        ("missing", "source_unobserved"),
        ("tombstone", "tombstone_conflict"),
        ("pending_intent", "source_intent_pending"),
        ("live_delete_no_head", "restore_unproven"),
    ],
)
def test_current_source_and_origin_refusals_are_atomic(world, monkeypatch, case, code):
    from miy_api.core.settings import get_settings

    context, identifier = legacy(
        world, "rag", operation="delete" if case == "live_delete_no_head" else "visibility_update"
    )
    with Session(world.engine) as db:
        job = db.get(RagSyncJob, identifier)
        doc = db.get(NativeDoc, context.docs[0])
        if case == "processing":
            from datetime import timedelta

            job.status, job.updated_at = "processing", utcnow_naive() - timedelta(days=1)
        elif case == "partial":
            job.projection_version = 1
        elif case == "app_disabled":
            db.get(CompanyAppControl, "docs").enabled = False
        elif case == "rag_disabled":
            monkeypatch.setattr(get_settings(), "rag_enabled", False)
        elif case == "missing_pointer":
            doc.retrieval_partition_id = None
        elif case == "retired":
            db.get(RetrievalPartition, context.partition).state = "retired"
            db.get(RetrievalPartition, context.partition).is_default_ingest = False
        elif case == "namespace":
            # Fixed source namespace cannot be changed through the model API.
            db.execute(
                text("UPDATE retrieval_partitions SET source_namespace='meeting' WHERE id=:id"),
                {"id": context.partition},
            )
        elif case == "missing":
            db.delete(doc)
        elif case == "tombstone":
            record_projection_event(
                db,
                resource_type="docs_native_doc",
                resource_id=doc.id,
                retrieval_partition_id=context.partition,
                change_kind="delete",
                desired_state="deleted",
            )
        elif case == "pending_intent":
            from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
            from miy_api.domains.official_apps.projection_outbox import append_projection_intent

            append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="docs_native_doc",
                    resource_id=doc.id,
                    retrieval_partition_id=context.partition,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                ),
            )
        db.commit()
    before = counts(world)
    with pytest.raises(DocsLegacyRepairError, match=code):
        convert(world, "rag", identifier)
    assert counts(world) == before
    with Session(world.engine) as db:
        assert db.get(RagSyncJob, identifier).status == (
            "processing" if case == "processing" else "pending"
        )


@pytest.mark.parametrize("case", ["trashed", "hard_deleted", "rag_excluded", "rag_personal"])
def test_current_source_deletion_and_rag_exclusion_differ(world, case):
    context, identifier = legacy(world, "rag")
    with Session(world.engine) as db:
        doc = db.get(NativeDoc, context.docs[0])
        if case == "trashed":
            doc.trashed_at = utcnow_naive()
        elif case == "hard_deleted":
            record_projection_event(
                db,
                resource_type="docs_native_doc",
                resource_id=doc.id,
                retrieval_partition_id=context.partition,
                change_kind="content",
                desired_state="active",
            )
            db.delete(doc)
        else:
            doc.rag_scope = case.removeprefix("rag_")
        db.commit()
    convert(world, "rag", identifier)
    with Session(world.engine) as db:
        target = db.scalar(select(Target))
        event = db.get(RetrievalProjectionEvent, target.core_event_sequence)
        assert event.desired_state == (
            "deleted" if case in {"trashed", "hard_deleted"} else "active"
        )
        assert db.get(SearchIndexJob, target.search_job_id).operation == (
            "delete" if event.desired_state == "deleted" else "upsert"
        )
        if case.startswith("rag_"):
            from miy_api.domains.rag.docs_projection import load_native_doc_projection

            assert load_native_doc_projection(db, doc_id=context.docs[0]) is None


@pytest.mark.parametrize("case", ["empty", "dedupe", "limit", "over", "malformed", "changed_input"])
def test_scope_bounded_snapshot_and_exact_input(world, case):
    context, identifier = legacy(world, "scope")
    with Session(world.engine) as db:
        job = db.get(RagVisibilityRecomputeJob, identifier)
        if case == "empty":
            job.cursor = {}
        elif case == "dedupe":
            job.cursor = {"doc_ids": [*context.docs, *context.docs]}
        elif case in {"limit", "over"}:
            ids = [str(uuid4()) for _ in range(100 if case == "limit" else 101)]
            job.cursor = {"doc_ids": ids}
            db.add_all(
                NativeDoc(
                    id=id_,
                    title="Synthetic",
                    owner_id=world.user_id,
                    retrieval_partition_id=context.partition,
                )
                for id_ in ids
            )
        elif case == "malformed":
            job.cursor = {"doc_ids": "not-a-list"}
        db.commit()
    if case in {"over", "malformed"}:
        with pytest.raises(DocsLegacyRepairError, match="budget"):
            convert(world, "scope", identifier)
        assert counts(world) == (0, 0, 0, 0)
    else:
        receipt_id = convert(world, "scope", identifier)
        with Session(world.engine) as db:
            receipt = db.get(Receipt, receipt_id)
            assert receipt.target_count == (0 if case == "empty" else 100 if case == "limit" else 2)
            frozen = json.loads(receipt.targets_payload)
            assert frozen == sorted(set(frozen))
            if case == "changed_input":
                db.get(RagVisibilityRecomputeJob, identifier).cursor = {"doc_ids": context.docs[:1]}
                db.commit()
        if case == "changed_input":
            with pytest.raises(DocsLegacyRepairError, match="receipt_conflict"):
                convert(world, "scope", identifier)


@pytest.mark.parametrize("kind", ["rag", "search"])
def test_fully_fenced_original_event_and_operation_passthrough(world, kind):
    context, identifier = legacy(world, kind)
    with Session(world.engine) as db:
        event = record_projection_event(
            db,
            resource_type="docs_native_doc",
            resource_id=context.docs[0],
            retrieval_partition_id=context.partition,
            change_kind="content",
            desired_state="active",
        )
        job = db.get(repair._MODELS[kind], identifier)
        for key in (
            "resource_type",
            "projection_version",
            "retrieval_partition_id",
            "desired_state",
        ):
            setattr(job, key, getattr(event, key))
        job.projection_event_sequence = event.event_sequence
        db.commit()
        before = job.operation
        assert repair.repair_docs_legacy_job(db, kind=kind, job_id=identifier) is None
        assert job.operation == before
    assert counts(world) == (0, 0, 1, 0)


def test_concurrent_same_origin_has_one_acceptance(world):
    _, identifier = legacy(world, "scope")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(convert, world, "scope", identifier) for _ in range(2)]
        assert futures[0].result(timeout=20) == futures[1].result(timeout=20)
    assert counts(world) == (1, 2, 2, 0)


@pytest.mark.parametrize("operation", ["content", "trash", "restore"])
def test_source_row_locked_before_its_late_intent_does_not_block_core_select(world, operation):
    from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
    from miy_api.domains.rag.contracts import RagSyncOperation

    context, identifier = legacy(world, "rag")
    if operation == "restore":
        with Session(world.engine) as db:
            db.get(NativeDoc, context.docs[0]).trashed_at = utcnow_naive()
            record_projection_event(
                db,
                resource_type="docs_native_doc",
                resource_id=context.docs[0],
                retrieval_partition_id=context.partition,
                change_kind="delete",
                desired_state="deleted",
            )
            db.commit()
    entered = Event()
    pids = {}
    with Session(world.engine) as core:
        lock_projection_source(core, "docs_native_doc", context.docs[0])
        core_pid = core.scalar(text("SELECT pg_backend_pid()"))

        def source():
            with Session(world.engine) as db:
                pids["source"] = db.scalar(text("SELECT pg_backend_pid()"))
                doc = db.get(NativeDoc, context.docs[0])
                doc.title = "Committed after repair"
                if operation != "content":
                    doc.trashed_at = utcnow_naive() if operation == "trash" else None
                db.flush()
                entered.set()
                enqueue_native_doc_rag_sync(
                    db,
                    doc=doc,
                    operation=RagSyncOperation.DELETE
                    if operation == "trash"
                    else RagSyncOperation.UPSERT,
                )
                db.commit()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(source)
            try:
                assert entered.wait(10)
                wait_for_blockers(lambda: Session(world.engine), pids["source"], {core_pid})
                receipt = repair.repair_docs_legacy_job(core, kind="rag", job_id=identifier)
                accepted_id = receipt.id
                core.commit()
            finally:
                core.rollback()
            future.result(timeout=20)
    with Session(world.engine) as db:
        head = db.get(RetrievalProjectionHead, ("docs_native_doc", context.docs[0]))
        target = db.scalar(select(Target).where(Target.receipt_id == accepted_id))
        event = db.get(RetrievalProjectionEvent, target.core_event_sequence)
        assert head.projection_version == event.projection_version + 1
        assert head.desired_state == ("deleted" if operation == "trash" else "active")
    assert convert(world, "rag", identifier) == accepted_id


def core_role(world):
    name = world.role()
    with world.connect() as conn:
        for tables, privileges in (
            (
                [
                    "docs_legacy_projection_repairs",
                    "docs_legacy_projection_repair_targets",
                    "retrieval_projection_events",
                ],
                "SELECT,INSERT",
            ),
            (
                [
                    "retrieval_projection_heads",
                    "rag_sync_jobs",
                    "rag_visibility_recompute_jobs",
                    "search_index_jobs",
                ],
                "SELECT,INSERT,UPDATE",
            ),
            (["retrieval_partitions"], "SELECT,UPDATE"),
            (
                [
                    "docs_native_docs",
                    "docs_meeting_access",
                    "meeting_doc_links",
                    "meetings",
                    "company_app_controls",
                    "official_projection_outbox",
                    "official_projection_receipts",
                ],
                "SELECT",
            ),
        ):
            conn.execute(
                sql.SQL("GRANT {} ON {} TO {}").format(
                    sql.SQL(privileges),
                    sql.SQL(",").join(sql.Identifier("public", table) for table in tables),
                    sql.Identifier(name),
                )
            )
        conn.execute(
            sql.SQL(
                "GRANT USAGE ON SEQUENCE public.retrieval_projection_events_event_sequence_seq TO {}"
            ).format(sql.Identifier(name))
        )
    return create_engine(sa_dsn(make_conninfo(world.dsn, user=name, password=PASSWORD)))


def test_core_select_only_sources_and_source_principal_cannot_repair(world):
    _, identifier = legacy(world, "scope")
    core = core_role(world)
    try:
        with core.connect() as conn:
            with pytest.raises(Exception) as error:
                conn.execute(text("SELECT id FROM docs_native_docs FOR SHARE"))
            assert error.value.orig.sqlstate == "42501"
            conn.rollback()
            with pytest.raises(Exception) as error:
                conn.execute(text("UPDATE docs_native_docs SET title=title WHERE false"))
            assert error.value.orig.sqlstate == "42501"
            conn.rollback()
        with Session(core) as db:
            repair.repair_docs_legacy_job(db, kind="scope", job_id=identifier)
            db.commit()
    finally:
        core.dispose()
    assert counts(world) == (1, 2, 2, 0)
    runtime, _, _ = activate(world)
    with world.connect(runtime) as conn:
        for table in ("docs_legacy_projection_repairs", "docs_legacy_projection_repair_targets"):
            denied(conn, f"INSERT INTO {table} SELECT * FROM {table} WHERE false")
            denied(
                conn,
                f"UPDATE {table} SET receipt_id=receipt_id WHERE false"
                if table.endswith("targets")
                else f"UPDATE {table} SET id=id WHERE false",
            )


def test_receipt_target_immutability_and_fk_retention(world):
    _, identifier = legacy(world, "rag")
    convert(world, "rag", identifier)
    with world.connect() as conn:
        for table in ("docs_legacy_projection_repairs", "docs_legacy_projection_repair_targets"):
            column = "id" if table.endswith("repairs") else "receipt_id"
            for statement in (
                f"UPDATE {table} SET {column}={column} WHERE false",
                f"DELETE FROM {table}",
                f"TRUNCATE {table} CASCADE",
            ):
                denied(conn, statement, "55000")
        denied(conn, f"DELETE FROM rag_sync_jobs WHERE id='{identifier}'", "23001")
        # Baseline event immutability rejects before its new RESTRICT FK.
        denied(conn, "DELETE FROM retrieval_projection_events", "23514")
        denied(conn, "TRUNCATE retrieval_projection_events RESTRICT", "0A000")
        denied(conn, "TRUNCATE retrieval_projection_events CASCADE", "55000")


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_isolation_is_fail_closed_without_mutation(world, isolation):
    _, identifier = legacy(world, "rag")
    engine = create_engine(sa_dsn(world.dsn), isolation_level=isolation)
    try:
        with Session(engine) as db, pytest.raises(DocsLegacyRepairError, match="read_committed"):
            repair.repair_docs_legacy_job(db, kind="rag", job_id=identifier)
    finally:
        engine.dispose()
    assert counts(world) == (0, 0, 0, 0)


def test_admission_revoked_after_flush_rolls_back_whole_conversion(world, monkeypatch):
    _, identifier = legacy(world, "scope")
    original = repair._admission
    visits = []

    def admission(db, kind):
        visits.append(True)
        if len(visits) == 3:
            with Session(world.engine) as other:
                other.get(CompanyAppControl, "docs").enabled = False
                other.commit()
        return original(db, kind)

    monkeypatch.setattr(repair, "_admission", admission)
    with pytest.raises(DocsLegacyRepairError, match="app_disabled"):
        convert(world, "scope", identifier)
    assert counts(world) == (0, 0, 0, 0)
    with Session(world.engine) as db:
        assert db.get(RagVisibilityRecomputeJob, identifier).status == "pending"


def test_source_intent_committed_before_core_lock_is_observed_as_tombstone(world):
    from miy_api.domains.docs.rag_sync import enqueue_native_doc_rag_sync
    from miy_api.domains.rag.contracts import RagSyncOperation

    context, identifier = legacy(world, "rag")
    pids = {}
    entered = Event()
    with Session(world.engine) as source:
        doc = source.get(NativeDoc, context.docs[0])
        doc.trashed_at = utcnow_naive()
        enqueue_native_doc_rag_sync(source, doc=doc, operation=RagSyncOperation.DELETE)
        source_pid = source.scalar(text("SELECT pg_backend_pid()"))

        def core():
            with Session(world.engine) as db:
                pids["core"] = db.scalar(text("SELECT pg_backend_pid()"))
                entered.set()
                receipt = repair.repair_docs_legacy_job(db, kind="rag", job_id=identifier)
                result = receipt.id
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(core)
            try:
                assert entered.wait(10)
                wait_for_blockers(lambda: Session(world.engine), pids["core"], {source_pid})
                source.commit()
            finally:
                source.rollback()
            future.result(timeout=20)
    with Session(world.engine) as db:
        head = db.get(RetrievalProjectionHead, ("docs_native_doc", context.docs[0]))
        assert head.desired_state == "deleted" and head.projection_version == 2


def test_empty_receipt_cannot_gain_targets_later(world):
    from miy_api.domains.rag.contracts import RagSyncOperation
    from miy_api.domains.rag.outbox import enqueue_rag_sync_job
    from miy_api.domains.search.outbox import enqueue_search_index_job

    context, identifier = legacy(world, "scope")
    with Session(world.engine) as db:
        db.get(RagVisibilityRecomputeJob, identifier).cursor = {}
        db.commit()
    receipt_id = convert(world, "scope", identifier)
    with Session(world.engine) as db:
        event = record_projection_event(
            db,
            resource_type="docs_native_doc",
            resource_id=context.docs[0],
            retrieval_partition_id=context.partition,
            change_kind="repair",
            desired_state="active",
        )
        search = enqueue_search_index_job(
            db, entity_type="doc", entity_id=context.docs[0], projection_event=event
        )
        rag = enqueue_rag_sync_job(
            db,
            resource_type="docs_native_doc",
            resource_id=context.docs[0],
            operation=RagSyncOperation.UPSERT,
            projection_event=event,
        )
        values = (
            receipt_id,
            context.docs[0],
            event.event_sequence,
            "upsert",
            search.id,
            rag.id,
        )
        db.commit()
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT target_count FROM docs_legacy_projection_repairs WHERE id=%s", (receipt_id,)
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                conn.execute("SET CONSTRAINTS ALL DEFERRED")
                conn.execute(
                    "INSERT INTO docs_legacy_projection_repair_targets (receipt_id,resource_id,core_event_sequence,operation,search_job_id,rag_job_id) VALUES (%s,%s,%s,%s,%s,%s)",
                    values,
                )
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert error.value.sqlstate == "23514"


def test_migration_preserves_existing_jobs_and_refuses_receipt_loss(world):
    from alembic import command
    from test_alembic_migrations import _migration_config

    context, identifier = legacy(world, "rag")
    command.downgrade(_migration_config(sa_dsn(world.dsn)), "official_projection_20261007")
    with Session(world.engine) as db:
        assert db.get(NativeDoc, context.docs[0]).title == "Visibility source"
        assert db.get(RagSyncJob, identifier).status == "pending"
    command.upgrade(_migration_config(sa_dsn(world.dsn)), "docs_legacy_repair_20261007")
    convert(world, "rag", identifier)
    with pytest.raises(RuntimeError, match="retention_required"):
        command.downgrade(_migration_config(sa_dsn(world.dsn)), "official_projection_20261007")
    assert counts(world) == (1, 1, 1, 0)


def test_keyword_worker_repair_refusal_never_enters_generic_retry(world, monkeypatch):
    _, identifier = legacy(world, "search", status="processing")
    tasks = importlib.import_module("miy_worker.tasks.search_index")
    monkeypatch.setattr(tasks, "_db_session", lambda: Session(world.engine))
    monkeypatch.setattr(tasks, "_search_job_app_enabled", lambda *args: True)

    def unexpected(*args, **kwargs):
        raise AssertionError("refused Core repair cannot create a provider or generic retry")

    monkeypatch.setattr(tasks, "_search_client_for_job", unexpected)
    monkeypatch.setattr(tasks, "_handle_job_failure", unexpected)
    with pytest.raises(DocsLegacyRepairError, match="origin_not_pending"):
        tasks.index_resource.run(identifier)
    with Session(world.engine) as db:
        job = db.get(SearchIndexJob, identifier)
        assert job.status == "processing" and job.attempts == 0
    assert counts(world) == (0, 0, 0, 0)


def test_lock_timeout_rolls_back_without_provider_and_resets_local_settings(world, monkeypatch):
    context, identifier = legacy(world, "rag")
    monkeypatch.setattr(repair, "LOCK_TIMEOUT", "100ms")
    with Session(world.engine) as holder, Session(world.engine) as caller:
        lock_projection_source(holder, "docs_native_doc", context.docs[0])
        before = caller.execute(text("SHOW lock_timeout")).scalar_one()
        with pytest.raises(DocsLegacyRepairError, match="outcome_unknown"):
            repair.dispatch_docs_legacy_repair(caller, kind="rag", job_id=identifier)
        assert caller.execute(text("SHOW lock_timeout")).scalar_one() == before
        assert caller.get(RagSyncJob, identifier).status == "pending"
        holder.rollback()
        assert (
            repair.dispatch_docs_legacy_repair(caller, kind="rag", job_id=identifier)
            == "docs-repair-converted"
        )
    assert counts(world) == (1, 1, 1, 0)


def test_original_job_changed_during_stream_wait_is_not_silently_adopted(world):
    context, identifier = legacy(world, "rag")
    entered = Event()
    pids = {}
    with Session(world.engine) as holder:
        lock_projection_source(holder, "docs_native_doc", context.docs[0])
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))

        def convert_after_wait():
            with Session(world.engine) as db:
                pids["caller"] = db.scalar(text("SELECT pg_backend_pid()"))
                entered.set()
                with pytest.raises(DocsLegacyRepairError, match="origin_changed"):
                    repair.dispatch_docs_legacy_repair(db, kind="rag", job_id=identifier)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(convert_after_wait)
            try:
                assert entered.wait(10)
                wait_for_blockers(lambda: Session(world.engine), pids["caller"], {holder_pid})
                with Session(world.engine) as mutation:
                    mutation.get(RagSyncJob, identifier).operation = "delete"
                    mutation.commit()
            finally:
                holder.rollback()
            future.result(timeout=20)
    assert counts(world) == (0, 0, 0, 0)
    with Session(world.engine) as db:
        job = db.get(RagSyncJob, identifier)
        assert job.operation == "delete" and job.status == "pending"
