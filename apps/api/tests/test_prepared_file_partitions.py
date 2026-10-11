"""Retained Core descriptor identities in owned PostgreSQL; no Source allocation."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import AuditLog
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.retrieval.models import RetrievalPartition
from miy_api.domains.retrieval.prepared_file_partitions import (
    PreparedFilePartitionSpec,
    lookup_prepared_file_partition,
    prepare_file_partition_descriptor,
)
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    BASE as BASE,
    PASSWORD as PASSWORD,
    activate as activate,
    move as move,
    role_template as role_template,
    sa_dsn as sa_dsn,
    wait_for_blocker as wait_for_blocker,
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


@pytest.mark.parametrize("kind", ["company_managed"])
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
