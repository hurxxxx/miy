"""Owned Source factory rejection preserves borrowed actual PG/ORM work."""

from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.orm import Session

from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_extraction_commands import c as c
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    world as world,
)
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.auth.app_access_models import AppGroupGrant
from miy_api.domains.auth.models import AuthSession
from miy_api.domains.files.extraction_contracts import (
    FileExtractionCommitUnknown,
    FileExtractionRefused,
)
from miy_api.domains.files.extraction_runner import FileExtractionRunner
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.official_apps.file_extraction_models import FileExtractionRequest
from miy_api.domains.pms.space_models import SpaceGroupBinding


def _routed_source_caller(c, monkeypatch, *, model, bind_kind, route_kind, clause_only=False):
    """Actual caller marker precedes the factory; the rejected Session stays fresh."""
    from sqlalchemy import update
    from sqlalchemy.sql.selectable import Select

    connection = c.engine.connect()
    caller_transaction = connection.begin()
    connection.execute(
        update(FileManagerFile)
        .where(FileManagerFile.id == c.spec.file_id)
        .values(extraction_metadata={"synthetic_routed_caller_marker": True})
    )
    route = connection if route_kind == "connection" else c.engine.execution_options()

    if clause_only:

        class RoutedSession(Session):
            def get_bind(self, mapper=None, clause=None, **kwargs):
                if isinstance(clause, Select) and model.__table__ in clause.get_final_froms():
                    return route
                return super().get_bind(mapper=mapper, clause=clause, **kwargs)

        db = RoutedSession(c.engine, autoflush=False, join_transaction_mode="rollback_only")
    else:
        key = model if bind_kind == "mapper" else model.__table__
        db = Session(
            bind=c.engine,
            binds={key: route},
            autoflush=False,
            join_transaction_mode="rollback_only",
        )
    calls = []
    controls = []
    original_close = db.close
    original_rollback = db.rollback
    original_commit = db.commit

    def sql(*args):
        calls.append("sql")

    def close():
        controls.append("close")
        original_close()

    def rollback():
        controls.append("rollback")
        original_rollback()

    def commit():
        controls.append("commit")
        original_commit()

    monkeypatch.setattr(db, "close", close)
    monkeypatch.setattr(db, "rollback", rollback)
    monkeypatch.setattr(db, "commit", commit)
    return db, connection, caller_transaction, calls, controls, sql, original_close


@pytest.mark.parametrize("entry", ["stage", "runner"])
@pytest.mark.parametrize("bind_kind", ["mapper", "table"])
@pytest.mark.parametrize(
    ("model", "route_kind"),
    [
        (FileManagerFile, "connection"),
        (AuthSession, "engine"),
        (AppGroupGrant, "connection"),
        (SpaceGroupBinding, "engine"),
    ],
    ids=["source_file", "current_execution", "conditional_app_group", "conditional_team"],
)
def test_routed_source_bind_is_refused_before_sql_and_preserves_caller(
    c, monkeypatch, entry, bind_kind, model, route_kind
):
    db, connection, outer, calls, controls, sql, original_close = _routed_source_caller(
        c, monkeypatch, model=model, bind_kind=bind_kind, route_kind=route_kind
    )
    try:
        assert db.get_bind() is c.engine and not db.in_transaction()
        event.listen(c.engine, "before_cursor_execute", sql)
        try:
            with pytest.raises(FileExtractionRefused) as error:
                if entry == "stage":
                    commands.prepare_file_extraction(db, spec=c.spec)
                else:
                    FileExtractionRunner(lambda: db).prepare(c.spec)
            assert error.value.reason == "source_engine_binding_required"
            assert error.value.__cause__ is None
            assert calls == [] and controls == [] and c.reads == []
            assert not db.in_transaction()
            assert not connection.closed and connection.in_transaction() and outer.is_active
        finally:
            event.remove(c.engine, "before_cursor_execute", sql)
        assert connection.scalar(
            select(FileManagerFile.extraction_metadata).where(FileManagerFile.id == c.spec.file_id)
        ) == {"synthetic_routed_caller_marker": True}
        assert connection.scalar(select(FileExtractionRequest.request_id)) is None
    finally:
        original_close()
        outer.rollback()
        connection.close()


@pytest.mark.parametrize("entry", ["stage", "runner"])
def test_public_clause_only_routing_is_refused_before_sql(c, monkeypatch, entry):
    db, connection, outer, calls, controls, sql, original_close = _routed_source_caller(
        c,
        monkeypatch,
        model=AuthSession,
        bind_kind="mapper",
        route_kind="connection",
        clause_only=True,
    )
    try:
        assert db.get_bind(mapper=AuthSession) is c.engine
        assert not db.in_transaction()
        event.listen(c.engine, "before_cursor_execute", sql)
        try:
            with pytest.raises(FileExtractionRefused) as error:
                if entry == "stage":
                    commands.prepare_file_extraction(db, spec=c.spec)
                else:
                    FileExtractionRunner(lambda: db).prepare(c.spec)
            assert error.value.reason == "source_engine_binding_required"
            assert calls == [] and controls == [] and c.reads == []
            assert not db.in_transaction() and outer.is_active and not connection.closed
        finally:
            event.remove(c.engine, "before_cursor_execute", sql)
        assert connection.scalar(
            select(FileManagerFile.extraction_metadata).where(FileManagerFile.id == c.spec.file_id)
        ) == {"synthetic_routed_caller_marker": True}
    finally:
        original_close()
        outer.rollback()
        connection.close()


def test_explicit_same_engine_routes_keep_one_acknowledged_source_transaction(c):
    def factory():
        return Session(
            bind=c.engine,
            binds={
                FileManagerFile: c.engine,
                AppGroupGrant.__table__: c.engine,
                SpaceGroupBinding: c.engine,
            },
        )

    receipt = FileExtractionRunner(factory).prepare(c.spec)
    assert receipt.state == "prepared" and not receipt.provisional
    assert c.reads == []
    with Session(c.engine) as db:
        row = db.get(FileExtractionRequest, str(c.spec.request_id))
        assert row is not None and row.request_digest == c.spec.digest()


@pytest.mark.parametrize("entry", ["stage", "runner"])
def test_public_route_lookup_error_is_stable_without_session_ownership(c, monkeypatch, entry):
    from sqlalchemy.exc import UnboundExecutionError

    class UnboundRouteSession(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            if mapper is AuthSession:
                raise UnboundExecutionError("synthetic private route diagnostic")
            return super().get_bind(mapper=mapper, clause=clause, **kwargs)

    db = UnboundRouteSession(c.engine)
    calls = []
    original_close = db.close

    def forbidden(*args, **kwargs):
        calls.append("caller_control")
        raise AssertionError("rejected route must remain caller owned")

    monkeypatch.setattr(db, "execute", forbidden)
    monkeypatch.setattr(db, "close", forbidden)
    monkeypatch.setattr(db, "rollback", forbidden)
    monkeypatch.setattr(db, "commit", forbidden)
    try:
        with pytest.raises(FileExtractionRefused) as error:
            if entry == "stage":
                commands.prepare_file_extraction(db, spec=c.spec)
            else:
                FileExtractionRunner(lambda: db).prepare(c.spec)
        assert error.value.reason == "source_engine_binding_required"
        assert error.value.__cause__ is None and calls == [] and not db.in_transaction()
        assert "synthetic private" not in str(error.value)
    finally:
        original_close()


@pytest.mark.parametrize("entry", ["stage", "runner"])
@pytest.mark.parametrize("work", ["active", "dirty", "new", "deleted", "savepoint"])
def test_rejected_engine_caller_retains_actual_marker_and_orm(c, monkeypatch, entry, work):
    db = Session(c.engine, autoflush=False)
    calls = []
    controls = []
    original_close = db.close
    original_rollback = db.rollback

    def traced_close():
        controls.append("close")
        original_close()

    def traced_rollback():
        controls.append("rollback")
        original_rollback()

    def sql(*args):
        calls.append("sql")

    try:
        file = db.get(FileManagerFile, c.spec.file_id)
        file.extraction_metadata = {"synthetic_caller_marker": True}
        db.flush()
        if work == "savepoint":
            db.begin_nested()
            file.extraction_metadata = {"synthetic_caller_marker": "nested"}
            db.flush()
        elif work == "dirty":
            file.filename = "Synthetic pending caller.txt"
        elif work == "new":
            db.add(
                FileManagerFile(
                    id=str(uuid4()),
                    retrieval_partition_id=file.retrieval_partition_id,
                    owner_id=c.spec.actor_user_id,
                    filename="Synthetic pending new.txt",
                    content_type="text/plain",
                    size_bytes=0,
                    storage_key="synthetic-caller-only",
                    visibility="private",
                )
            )
        elif work == "deleted":
            db.delete(file)
        outer = db.get_transaction()
        nested = db.get_nested_transaction()
        connection = db.connection()
        pending = (frozenset(db.new), frozenset(db.dirty), frozenset(db.deleted))
        monkeypatch.setattr(db, "close", traced_close)
        monkeypatch.setattr(db, "rollback", traced_rollback)
        event.listen(c.engine, "before_cursor_execute", sql)
        try:
            with pytest.raises(FileExtractionRefused) as error:
                if entry == "stage":
                    commands.prepare_file_extraction(db, spec=c.spec)
                else:
                    FileExtractionRunner(lambda: db).prepare(c.spec)
            assert error.value.reason == "fresh_clean_outer_transaction_required"
            assert calls == [] and c.reads == []
            assert controls == []
            assert db.get_transaction() is outer and db.get_nested_transaction() is nested
            assert (frozenset(db.new), frozenset(db.dirty), frozenset(db.deleted)) == pending
            assert not connection.closed and connection.in_transaction()
        finally:
            event.remove(c.engine, "before_cursor_execute", sql)
        assert connection.scalar(
            select(FileManagerFile.extraction_metadata).where(FileManagerFile.id == c.spec.file_id)
        )["synthetic_caller_marker"] == ("nested" if work == "savepoint" else True)
        assert connection.scalar(select(FileExtractionRequest.request_id)) is None
    finally:
        original_rollback()
        original_close()


@pytest.mark.parametrize("entry", ["stage", "runner"])
def test_unbound_pending_factory_is_stable_and_remains_caller_owned(monkeypatch, entry):
    db = Session()
    file = FileManagerFile(
        id=str(uuid4()),
        owner_id=str(uuid4()),
        filename="Synthetic unbound pending.txt",
        content_type="text/plain",
        size_bytes=0,
        storage_key="synthetic-unbound-caller-only",
        visibility="private",
    )
    db.add(file)
    outer = db.get_transaction()
    calls = []
    original_close = db.close

    def called(*args, **kwargs):
        calls.append("caller_method")
        raise AssertionError("rejected factory must not acquire ownership")

    monkeypatch.setattr(db, "close", called)
    monkeypatch.setattr(db, "rollback", called)
    monkeypatch.setattr(db, "execute", called)
    try:
        with pytest.raises(FileExtractionRefused) as error:
            if entry == "stage":
                commands.capture_file_extraction_input(
                    db, actor_user_id=file.owner_id, execution_ref="synthetic", file_id=file.id
                )
            else:
                FileExtractionRunner(lambda: db).capture(
                    actor_user_id=file.owner_id, execution_ref="synthetic", file_id=file.id
                )
        assert error.value.reason == "source_engine_binding_required"
        assert error.value.__cause__ is None and calls == []
        assert db.get_transaction() is outer and file in db.new
    finally:
        original_close()


@pytest.mark.parametrize(
    "scenario",
    [
        "known_ack_close_cancel",
        "commit_before_unknown_close_cancel",
        "commit_after_unknown_close_cancel",
        "commit_before_unknown_rollback_cancel",
        "body_refusal_close_cancel",
        "commit_before_cancel",
        "commit_after_cancel",
        "stage_refusal_rollback_cancel",
    ],
)
def test_source_cancellation_retains_ack_or_original_control_with_actual_request(c, scenario):
    """Actual restricted Source SQL/receipts; only response/cleanup faults injected."""
    close_cancel = scenario.endswith("close_cancel")
    rollback_cancel = scenario.endswith("rollback_cancel")
    timing = (
        "before" if "commit_before" in scenario else "after" if "commit_after" in scenario else None
    )
    commit_error = (
        KeyboardInterrupt
        if scenario in {"commit_before_cancel", "commit_after_cancel"}
        else RuntimeError
    )
    if "refusal" in scenario:
        with Session(c.world.engine) as db:
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == c.spec.execution_ref)
                .values(revoked_at=func.now())
            )
            db.commit()
    sessions = []

    class CancellationSession(Session):
        def commit(self):
            if timing == "before":
                raise commit_error("synthetic COMMIT response cancellation")
            super().commit()
            if timing == "after":
                raise commit_error("synthetic COMMIT response cancellation")

        def rollback(self):
            if rollback_cancel:
                raise KeyboardInterrupt("synthetic rollback cancellation")
            return super().rollback()

        def close(self):
            super().close()
            if close_cancel:
                raise KeyboardInterrupt("synthetic close cancellation")

    def factory():
        db = CancellationSession(c.engine)
        sessions.append(db)
        return db

    runner = FileExtractionRunner(factory)
    try:
        if "refusal" in scenario:
            with pytest.raises(BaseException) as caught:
                if scenario.startswith("stage_"):
                    db = factory()
                    try:
                        commands.prepare_file_extraction(db, spec=c.spec)
                    finally:
                        # Direct stages remain caller-owned; cleanup belongs
                        # only to this test's fresh Session, after invocation.
                        Session.close(db)
                else:
                    runner.prepare(c.spec)
            assert isinstance(caught.value, FileExtractionRefused)
            assert not isinstance(caught.value, FileExtractionCommitUnknown)
            assert caught.value.reason == "current_execution_denied"
        elif timing is not None:
            # Catch BaseException so an untyped cancellation is an assertion
            # failure rather than aborting the entire owned PostgreSQL run.
            with pytest.raises(BaseException) as caught:
                runner.prepare(c.spec)
            unknown = caught.value
            assert isinstance(unknown, FileExtractionCommitUnknown)
            assert unknown.phase == "prepare" and unknown.__cause__ is None
            assert unknown.receipt.state == "prepared" and unknown.receipt.provisional
            assert unknown.receipt.request_digest == c.spec.digest()
            assert (
                unknown.receipt.request_id,
                unknown.receipt.result_id,
                unknown.receipt.event_id,
            ) == (c.spec.request_id, c.spec.result_id, c.spec.event_id)
            assert unknown.receipt.producer_role_oid > 0
            if timing == "after":
                observed = FileExtractionRunner(lambda: Session(c.engine)).observe(spec=c.spec)
                assert observed.state == "prepared" and not observed.provisional
                assert observed.request_digest == unknown.receipt.request_digest
                assert observed.request_id == unknown.receipt.request_id
                assert observed.result_id == unknown.receipt.result_id
                assert observed.event_id == unknown.receipt.event_id
        else:
            try:
                receipt = runner.prepare(c.spec)
            except BaseException as error:
                pytest.fail(f"Cleanup replaced the known Source ACK with {type(error).__name__}")
            assert receipt.state == "prepared" and not receipt.provisional
            assert receipt.request_digest == c.spec.digest()
            assert (receipt.request_id, receipt.result_id, receipt.event_id) == (
                c.spec.request_id,
                c.spec.result_id,
                c.spec.event_id,
            )
        with Session(c.engine) as db:
            row = db.get(FileExtractionRequest, str(c.spec.request_id))
            if scenario == "known_ack_close_cancel" or timing == "after":
                assert row is not None and row.state == "prepared"
                assert row.request_digest == c.spec.digest()
            else:
                assert row is None
        assert c.reads == []
    finally:
        for db in sessions:
            Session.close(db)
