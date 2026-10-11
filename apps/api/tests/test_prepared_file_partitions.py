"""Retained Core descriptor identities in owned PostgreSQL; no Source allocation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import AuditLog, AuthSession, utcnow_naive
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.retrieval.models import RetrievalPartition
from miy_api.domains.retrieval.partitioning import RetrievalPartitionConflict
from miy_api.domains.retrieval.prepared_file_partitions import (
    PreparedFilePartitionSpec,
    lookup_current_file_default,
    lookup_prepared_file_partition,
    prepare_file_partition_descriptor,
)
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    BASE,
    PASSWORD,
    activate,
    move,
    role_template as role_template,
    sa_dsn,
    wait_for_blocker,
    world as world,
)


def spec(kind="company_managed", version=1):
    return PreparedFilePartitionSpec(str(uuid4()), kind, version)


def prepare(db, world, identity):
    return prepare_file_partition_descriptor(
        db, world.actor, spec=identity, expected=BASE, expected_state="active"
    )


def observe(db, world, identity):
    return lookup_prepared_file_partition(
        db, world.actor, spec=identity, expected=BASE, expected_state="active"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("partition_id", ""),
        ("partition_id", "not-a-uuid"),
        ("partition_id", None),
        ("kind", "personal"),
        ("kind", "files"),
        ("kind", None),
        ("metadata_version", True),
        ("metadata_version", 0),
        ("metadata_version", -1),
        ("metadata_version", 2_147_483_648),
        ("metadata_version", "1"),
    ],
)
def test_setup_spec_refuses_noncontract_identity(field, value):
    values = dict(partition_id=str(uuid4()), kind="company_managed", metadata_version=1)
    values[field] = value
    with pytest.raises(RetrievalPartitionConflict):
        PreparedFilePartitionSpec(**values)


def test_spec_canonicalizes_retained_uuid_without_invention():
    identifier = uuid4()
    retained = PreparedFilePartitionSpec(identifier.hex.upper(), "company_default", 1)
    assert retained.partition_id == str(identifier)
    with pytest.raises(FrozenInstanceError):
        retained.partition_id = str(uuid4())


@pytest.mark.parametrize("kind", ["company_default", "company_managed"])
def test_exact_setup_replay_retains_id_and_single_audit(world, kind):
    retained = spec(kind, 3)
    with Session(world.engine) as db:
        first = prepare(db, world, retained)
        assert first.provisional and first.created and first.spec is retained
        db.commit()
        second = prepare(db, world, retained)
        assert second.provisional and not second.created and second.spec is retained
        db.commit()
        observed = observe(db, world, retained)
        assert observed.spec == retained and observed.provisional and not observed.created
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "retrieval.file_partition.prepare")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 1


def test_default_discovery_is_read_only_and_never_reallocates(world):
    retained = spec("company_default", 2)
    with Session(world.engine) as db:
        assert (
            lookup_current_file_default(db, world.actor, expected=BASE, expected_state="active")
            is None
        )
        assert not db.new and not db.dirty
        prepare(db, world, retained)
        db.commit()
        found = lookup_current_file_default(db, world.actor, expected=BASE, expected_state="active")
        assert found.spec == retained and found.provisional
        assert not db.new and not db.dirty
        db.rollback()
        other = spec("company_default", 2)
        with pytest.raises(RetrievalPartitionConflict, match="identity_conflict"):
            prepare(db, world, other)
        db.rollback()
        assert observe(db, world, other) is None
        assert observe(db, world, retained).spec == retained


@pytest.mark.parametrize("accepted", [False, True])
def test_unknown_caller_commit_observes_only_retained_spec(world, monkeypatch, accepted):
    retained = spec()
    with Session(world.engine) as db:
        receipt = prepare(db, world, retained)
        commit = db.commit

        def lost_ack():
            if accepted:
                commit()
            raise RuntimeError("Synthetic caller ACK loss")

        monkeypatch.setattr(db, "commit", lost_ack)
        with pytest.raises(RuntimeError, match="Synthetic caller ACK loss"):
            db.commit()
        db.rollback()
        assert receipt.spec is retained and receipt.provisional
    with Session(world.engine) as db:
        found = observe(db, world, retained)
        assert (found is not None) is accepted
        assert not db.new and not db.dirty and not db.deleted
        if found:
            assert found.spec is retained and found.provisional
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == int(accepted)
        assert db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "retrieval.file_partition.prepare")
        ) == int(accepted)


@pytest.mark.parametrize("drift", ["namespace", "kind", "version", "retired"])
def test_same_uuid_drift_refuses_creation_and_observation(world, drift):
    retained = spec()
    with Session(world.engine) as db:
        prepare(db, world, retained)
        db.commit()
        row = db.get(RetrievalPartition, retained.partition_id)
        if drift == "namespace":
            row.source_namespace = "docs"
        elif drift == "kind":
            row.is_default_ingest = True
        elif drift == "version":
            row.metadata_version += 1
        else:
            row.state = "retired"
        db.commit()
        with pytest.raises(RetrievalPartitionConflict, match="descriptor_changed"):
            observe(db, world, retained)
        db.rollback()
        with pytest.raises(RetrievalPartitionConflict, match="descriptor_changed"):
            prepare(db, world, retained)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 1


@pytest.mark.parametrize("change", ["role", "expired", "revoked", "ownership"])
def test_current_core_authority_is_rechecked(world, change):
    retained = spec()
    if change == "ownership":
        move(world, BASE, "active", state="draining")
    else:
        with Session(world.engine) as db:
            if change == "role":
                db.execute(
                    text("DELETE FROM user_system_roles WHERE user_id=:id"),
                    {"id": world.user_id},
                )
            else:
                auth = db.get(AuthSession, world.session_id)
                if change == "expired":
                    auth.expires_at = utcnow_naive() - timedelta(seconds=1)
                else:
                    auth.revoked_at = utcnow_naive()
            db.commit()
    with Session(world.engine) as db:
        with pytest.raises((HTTPException, WriterControlError)):
            prepare(db, world, retained)
        db.rollback()
        with pytest.raises((HTTPException, WriterControlError, RetrievalPartitionConflict)):
            observe(db, world, retained)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 0


def test_post_wait_admin_revocation_refuses_before_descriptor_write(world):
    retained = spec()

    def waiting_setup():
        with Session(world.engine) as db:
            try:
                prepare(db, world, retained)
                db.commit()
            except Exception:
                db.rollback()
                raise

    with ThreadPoolExecutor(max_workers=1) as pool, world.connect() as blocker:
        blocker.execute(
            "SELECT scope FROM official_runtime_ownership WHERE scope='official.suite' FOR UPDATE"
        )
        blocker_id = blocker.execute("SELECT pg_backend_pid()").fetchone()[0]
        future = pool.submit(waiting_setup)
        try:
            wait_for_blocker(world, blocker_id)
            with world.connect() as conn:
                conn.execute("DELETE FROM user_system_roles WHERE user_id=%s", (world.user_id,))
            blocker.commit()
            with pytest.raises(WriterControlError, match="writer_admin_required"):
                future.result(timeout=10)
        finally:
            blocker.rollback()
            if not future.done():
                future.result(timeout=10)
    with Session(world.engine) as db:
        assert db.scalar(select(func.count()).select_from(RetrievalPartition)) == 0


@pytest.mark.parametrize("nested", [False, True])
def test_refused_caller_pending_work_is_preserved_without_sql(world, nested):
    retained = spec()
    with Session(world.engine) as db:
        if nested:
            db.begin_nested()
        marker = RetrievalPartition(
            id=str(uuid4()),
            source_namespace="files",
            candidate_scope_kind="company",
            state="active",
            metadata_version=1,
            is_default_ingest=False,
        )
        db.add(marker)
        pending = frozenset(db.new)
        outer, inner = db.get_transaction(), db.get_nested_transaction()
        calls = []

        def sql_call(*args):
            calls.append("sql")

        event.listen(world.engine, "before_cursor_execute", sql_call)
        try:
            for function in (prepare, observe):
                with pytest.raises(RetrievalPartitionConflict, match="clean_outer_required"):
                    function(db, world, retained)
            assert calls == [] and frozenset(db.new) == pending
            assert db.get_transaction() is outer and db.get_nested_transaction() is inner
        finally:
            event.remove(world.engine, "before_cursor_execute", sql_call)


def test_source_role_cannot_prepare_core_descriptor(world):
    source, _, _ = activate(world)
    source_engine = create_engine(sa_dsn(make_conninfo(world.dsn, user=source, password=PASSWORD)))
    try:
        with Session(source_engine) as db:
            with pytest.raises(RetrievalPartitionConflict, match="core_authority_required"):
                prepare_file_partition_descriptor(
                    db, world.actor, spec=spec(), expected=BASE, expected_state="active"
                )
    finally:
        source_engine.dispose()


def test_read_only_core_observer_has_no_descriptor_write_privilege(world):
    retained = spec()
    with Session(world.engine) as db:
        prepare(db, world, retained)
        db.commit()
    reader = world.role()
    # Reuse Core's current auth resolver read graph; this is not a Source profile.
    with world.connect() as conn:
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(reader)))
        conn.execute(
            sql.SQL(
                "GRANT SELECT ON retrieval_partitions,official_runtime_ownership,users,"
                "auth_sessions,user_system_roles,groups TO {}"
            ).format(sql.Identifier(reader))
        )
    reader_engine = create_engine(sa_dsn(make_conninfo(world.dsn, user=reader, password=PASSWORD)))
    calls = []

    def sql_call(connection, cursor, statement, parameters, context, many):
        calls.append(statement.strip().split()[0].upper())

    event.listen(reader_engine, "before_cursor_execute", sql_call)
    try:
        with Session(reader_engine) as db:
            assert observe(db, world, retained).spec == retained
            assert observe(db, world, spec()) is None
            db.commit()
            assert set(calls) <= {"SELECT", "SHOW"}
            with pytest.raises(RetrievalPartitionConflict, match="core_authority_required"):
                prepare(db, world, spec())
    finally:
        event.remove(reader_engine, "before_cursor_execute", sql_call)
        reader_engine.dispose()
