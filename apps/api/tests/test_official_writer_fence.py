from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
from uuid import uuid4

from fastapi import HTTPException
import psycopg
import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError

from miy_api.core.db import get_session_factory
from miy_api.domains.announcements.models import Announcement
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.models import AuthSession, UserSystemRole, utcnow_naive
from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.official_apps.writer import (
    WriterControlError,
    WriterIdentity,
    bind_transaction,
    snapshot,
    transition,
)
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_models import RuntimeOwnership, RuntimeTransition
from test_organization_integrations import _bootstrap_admin

LEGACY = WriterIdentity(SUITE_SCOPE, "legacy", 1)


@pytest.fixture
def writer(client):
    admin = _bootstrap_admin(client)
    response = client.post(
        "/api/v1/announcements",
        headers={"Authorization": "Bearer " + admin["token"]},
        json={"title": "Writer fixture", "body": "original"},
    )
    assert response.status_code == 201
    factory = get_session_factory()
    assert factory.kw["bind"].url.database.startswith("miy_test_")
    try:
        yield factory, admin, response.json()["id"]
    finally:
        # Privileged fixture restoration in this disposable DB only. The product
        # transition API never resets a generation or removes its audit history.
        with factory.begin() as db:
            db.execute(delete(RuntimeTransition))
            db.execute(
                update(RuntimeOwnership).values(
                    active_owner="legacy", generation=1, artifact=None, state="active"
                )
            )


def change(
    db,
    admin,
    *,
    expected=LEGACY,
    expected_state="active",
    owner="legacy",
    state="draining",
    artifact=None,
    request_id=None,
):
    actor = resolve_auth_context_from_token(db, admin["token"], update_last_seen=False)
    return transition(
        db,
        actor,
        request_id=request_id or uuid4(),
        expected=expected,
        expected_state=expected_state,
        owner=owner,
        state=state,
        artifact=artifact,
        reason="Disposable writer fence verification",
    )


def fenced(statement, factory):
    with factory() as db:
        with pytest.raises(DBAPIError) as error:
            db.execute(statement)
        assert error.value.orig.sqlstate == "55000"
        db.rollback()


def test_owner_cas_audit_idempotency_rollback_and_activation_remain_closed(writer):
    factory, admin, _ = writer
    request_id = uuid4()
    with factory.begin() as db:
        resulting = change(db, admin, request_id=request_id)
    assert resulting["generation"] == 2 and resulting["state"] == "draining"
    with factory.begin() as db:
        assert change(db, admin, request_id=request_id) == resulting
        assert len(db.scalars(select(RuntimeTransition)).all()) == 1
        audit = db.get(RuntimeTransition, str(request_id))
        assert audit.previous["generation"] == 1 and audit.actor_user_id == admin["user"]["id"]
    with factory() as db:
        with pytest.raises(WriterControlError, match="request_conflict"):
            change(db, admin, request_id=request_id, state="active")
        db.rollback()
        with pytest.raises(WriterControlError, match="compare_and_swap"):
            change(db, admin)
        db.rollback()
        with pytest.raises(WriterControlError, match="activation_unavailable"):
            change(db, admin, owner="official-suite")
        db.rollback()
        current = WriterIdentity(SUITE_SCOPE, "legacy", 2)
        change(db, admin, expected=current, expected_state="draining", state="active")
        db.rollback()
        assert snapshot(db.get(RuntimeOwnership, SUITE_SCOPE)) == resulting
        assert len(db.scalars(select(RuntimeTransition)).all()) == 1


@pytest.mark.parametrize("operation", ["insert", "update", "delete", "truncate", "orm", "copy"])
def test_draining_blocks_actual_mutation_in_orm_core_raw_sql_copy_and_truncate(writer, operation):
    factory, admin, announcement_id = writer
    with factory.begin() as db:
        change(db, admin)
    statements = {
        "insert": text(
            "INSERT INTO announcements (id,author_id,scope,title,body,is_pinned,created_at,updated_at) SELECT 'blocked',author_id,scope,'blocked','',false,now(),now() FROM announcements LIMIT 1"
        ),
        "update": update(Announcement).values(title="blocked"),
        "delete": delete(Announcement),
        "truncate": text("TRUNCATE announcements"),
    }
    if operation in statements:
        fenced(statements[operation], factory)
    elif operation == "orm":
        with factory() as db:
            db.get(Announcement, announcement_id).title = "blocked"
            with pytest.raises(DBAPIError) as error:
                db.commit()
            assert error.value.orig.sqlstate == "55000"
            db.rollback()
    else:
        connection = factory.kw["bind"].raw_connection()
        try:
            with connection.cursor() as cursor:
                with pytest.raises(psycopg.Error) as error:
                    with cursor.copy("COPY announcements (id) FROM STDIN") as copy:
                        copy.write_row(("blocked",))
                assert error.value.sqlstate == "55000"
            connection.rollback()
        finally:
            connection.close()
    with factory() as db:
        assert db.get(Announcement, announcement_id).title == "Writer fixture"


def test_identity_is_exact_transaction_local_and_stale_finalizers_cannot_adopt_generation(writer):
    factory, admin, announcement_id = writer
    with factory.begin() as db:
        change(db, admin)
    digest = "sha256:" + "a" * 64
    with factory.begin() as db:
        change(
            db,
            admin,
            expected=WriterIdentity(SUITE_SCOPE, "legacy", 2),
            expected_state="draining",
            state="active",
            artifact=digest,
        )
    current = WriterIdentity(SUITE_SCOPE, "legacy", 3, digest)
    fenced(update(Announcement).values(title="stale default"), factory)
    with factory() as db:
        bind_transaction(db, LEGACY)
        with pytest.raises(DBAPIError):
            db.execute(update(Announcement).values(title="stale finalizer"))
        db.rollback()
        bind_transaction(db, WriterIdentity(SUITE_SCOPE, "legacy", 3, "sha256:" + "b" * 64))
        with pytest.raises(DBAPIError):
            db.execute(update(Announcement).values(title="wrong artifact"))
        db.rollback()
        bind_transaction(db, current)
        with pytest.raises(WriterControlError, match="already_bound"):
            bind_transaction(db, LEGACY)
        db.execute(update(Announcement).values(title="current writer"))
        db.commit()
        assert db.scalar(text("SELECT current_setting('miy.official_writer', true)")) in (None, "")
        with pytest.raises(DBAPIError):
            db.execute(update(Announcement).values(title="not rebound"))
        db.rollback()
        bind_transaction(db, current)
        db.execute(update(Announcement).values(title="rolled back"))
        db.rollback()
        assert db.scalar(text("SELECT current_setting('miy.official_writer', true)")) in (None, "")
        assert db.get(Announcement, announcement_id).title == "current writer"


def wait_for_blockers(factory, pid, expected, *, any_expected=False):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with factory() as db:
            blockers = set(db.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}))
        if (expected & blockers) if any_expected else (expected <= blockers):
            return blockers
        time.sleep(0.02)
    pytest.fail("The ownership transition did not wait on the expected transaction locks")


def test_shared_writers_hold_cas_until_both_finish_and_stale_commit_is_rejected(writer):
    factory, admin, _ = writer
    entered = [Event(), Event()]
    finish = [Event(), Event()]
    pids = {}
    controller_entered = Event()

    def source(index):
        with factory() as db:
            pids[index] = db.scalar(text("SELECT pg_backend_pid()"))
            # Even a zero-row statement must participate in the transaction fence.
            model = Announcement if index == 0 else NativeDoc
            db.execute(update(model).where(model.id == "absent").values(title="none"))
            entered[index].set()
            assert finish[index].wait(5)
            db.commit()

    def control():
        with factory.begin() as db:
            pids["controller"] = db.scalar(text("SELECT pg_backend_pid()"))
            controller_entered.set()
            return change(db, admin)

    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = [pool.submit(source, index) for index in (0, 1)]
        try:
            assert all(event.wait(5) for event in entered)
            controller = pool.submit(control)
            assert controller_entered.wait(5)
            # A tuple MultiXact can wait on one member XID at a time. Both
            # sources already acquired SHARE; observe/release whichever member
            # currently blocks the controller, then prove the other still does.
            blockers = wait_for_blockers(
                factory, pids["controller"], {pids[0], pids[1]}, any_expected=True
            )
            first = next(index for index in (0, 1) if pids[index] in blockers)
            remaining = 1 - first
            finish[first].set()
            sources[first].result(timeout=5)
            wait_for_blockers(factory, pids["controller"], {pids[remaining]})
            assert not controller.done()
            finish[remaining].set()
            sources[remaining].result(timeout=5)
            assert controller.result(timeout=5)["state"] == "draining"
        finally:
            for event in finish:
                event.set()
    fenced(update(Announcement).values(title="stale after CAS"), factory)


@pytest.mark.parametrize("revocation", ["session", "role"])
def test_controller_rechecks_admin_after_waiting_for_source_transactions(writer, revocation):
    factory, admin, _ = writer
    entered = Event()
    pid = []
    with factory() as source:
        source.execute(update(Announcement).where(Announcement.id == "absent").values(title="none"))
        source_pid = source.scalar(text("SELECT pg_backend_pid()"))

        def control():
            with factory.begin() as db:
                actor = resolve_auth_context_from_token(db, admin["token"], update_last_seen=False)
                pid.append(db.scalar(text("SELECT pg_backend_pid()")))
                entered.set()
                return transition(
                    db,
                    actor,
                    request_id=uuid4(),
                    expected=LEGACY,
                    expected_state="active",
                    owner="legacy",
                    state="draining",
                    artifact=None,
                    reason="Delayed controller",
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(control)
            try:
                assert entered.wait(5)
                wait_for_blockers(factory, pid[0], {source_pid})
                with factory.begin() as revoke:
                    if revocation == "session":
                        revoke.execute(
                            update(AuthSession)
                            .where(AuthSession.user_id == admin["user"]["id"])
                            .values(revoked_at=utcnow_naive())
                        )
                    else:
                        revoke.execute(
                            delete(UserSystemRole).where(
                                UserSystemRole.user_id == admin["user"]["id"]
                            )
                        )
                source.rollback()
                with pytest.raises((HTTPException, WriterControlError)):
                    future.result(timeout=5)
            finally:
                source.rollback()
    with factory() as db:
        assert db.get(RuntimeOwnership, SUITE_SCOPE).generation == 1
        assert db.scalar(select(RuntimeTransition)) is None


def test_savepoint_rollback_releases_fence_and_local_identity_then_stale_outer_transaction_fails(
    writer,
):
    factory, admin, _ = writer
    with factory() as db:
        nested = db.begin_nested()
        bind_transaction(db, LEGACY)
        db.execute(update(Announcement).values(title="savepoint only"))
        nested.rollback()
        assert db.scalar(text("SELECT current_setting('miy.official_writer', true)")) in (None, "")
        with factory.begin() as control:
            control.execute(text("SET LOCAL lock_timeout = '2s'"))
            change(control, admin)
        with pytest.raises(DBAPIError) as error:
            db.execute(update(Announcement).values(title="stale outer"))
        assert error.value.orig.sqlstate == "55000"
        db.rollback()


@pytest.mark.parametrize("revocation", ["session", "role"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_control_rejects_snapshot_isolation_even_when_cached_admin_was_valid(
    writer, isolation, revocation
):
    factory, admin, _ = writer
    with factory() as db:
        # Isolation strings are fixed parameterized test literals, not user SQL.
        db.execute(text("SET TRANSACTION ISOLATION LEVEL " + isolation))
        actor = resolve_auth_context_from_token(db, admin["token"], update_last_seen=False)
        with factory.begin() as revoke:
            if revocation == "session":
                revoke.execute(
                    update(AuthSession)
                    .where(AuthSession.id == actor.session.id)
                    .values(revoked_at=utcnow_naive())
                )
            else:
                revoke.execute(
                    delete(UserSystemRole).where(UserSystemRole.user_id == actor.user.id)
                )
        with pytest.raises(WriterControlError, match="writer_transition_requires_read_committed"):
            transition(
                db,
                actor,
                request_id=uuid4(),
                expected=LEGACY,
                expected_state="active",
                owner="legacy",
                state="draining",
                artifact=None,
                reason="Stale snapshot refusal",
            )
        db.rollback()
    with factory() as db:
        assert db.get(RuntimeOwnership, SUITE_SCOPE).generation == 1
        assert db.scalar(select(RuntimeTransition)) is None


def test_control_rejects_dbapi_autocommit_before_any_ownership_or_audit_write(writer):
    factory, admin, _ = writer
    autocommit_bind = factory.kw["bind"].execution_options(isolation_level="AUTOCOMMIT")
    with factory(bind=autocommit_bind) as db:
        actor = resolve_auth_context_from_token(db, admin["token"], update_last_seen=False)
        assert db.connection().connection.driver_connection.autocommit is True
        with pytest.raises(WriterControlError, match="writer_transition_requires_transaction"):
            transition(
                db,
                actor,
                request_id=uuid4(),
                expected=LEGACY,
                expected_state="active",
                owner="legacy",
                state="draining",
                artifact=None,
                reason="Atomic transaction required",
            )
    with factory() as db:
        assert db.connection().connection.driver_connection.autocommit is False
        assert db.get(RuntimeOwnership, SUITE_SCOPE).generation == 1
        assert db.scalar(select(RuntimeTransition)) is None
