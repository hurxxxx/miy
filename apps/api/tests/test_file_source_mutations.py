"""Pure contract and real Session ownership boundaries for the fixed Source leaf."""

from datetime import datetime
from hashlib import sha256
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import AuthSession
from miy_api.domains.files import source_mutations as mutations
from miy_api.domains.files.extraction_commands import require_fresh_file_extraction_session
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceDeleteSpec,
    FileSourceMutationConflict,
    FileSourceMutationRefused,
)


@pytest.fixture
def spec():
    stamp = datetime(2026, 10, 7, 12).isoformat(timespec="microseconds")
    actor = str(uuid4())
    return FileSourceDeleteSpec(
        file_id=str(uuid4()),
        actor_user_id=actor,
        execution_ref=str(uuid4()),
        event_id=uuid4(),
        expected=FileSourceDeleteExpected(
            owner_id=actor,
            retrieval_partition_id=uuid4(),
            storage_key="synthetic/private-object",
            filename="synthetic.txt",
            content_type="text/plain",
            size_bytes=3,
            created_at=stamp,
            updated_at=stamp,
            extraction_status="ready",
            extraction_content_checksum=sha256(b"abc").hexdigest(),
            extracted_at=stamp,
            tip_event_id=uuid4(),
            tip_event_digest="a" * 64,
            tip_source_revision=1,
        ),
    )


def test_fixed_canonical_provenance_and_no_body_copy(spec):
    payload = json.loads(spec.canonical())
    assert payload["command"] == "native_root_file_soft_delete"
    assert payload["protocol_version"] == 1
    assert spec.digest() == sha256(spec.canonical().encode()).hexdigest()
    intent = mutations._intent(spec)
    assert (intent.operation, intent.desired_state, intent.content_checksum) == (
        "delete",
        "deleted",
        None,
    )
    provenance = intent.trace_context["files_source_mutation"]
    assert provenance == {
        "protocol_version": 1,
        "command": "native_root_file_soft_delete",
        "spec_digest": spec.digest(),
        "before_digest": spec.expected.digest(),
        "actor_user_id": spec.actor_user_id,
        "execution_ref": spec.execution_ref,
        "previous_event_id": str(spec.expected.tip_event_id),
        "previous_event_digest": spec.expected.tip_event_digest,
        "previous_source_revision": 1,
    }
    assert "storage_key" not in intent.canonical()
    assert all(not key.startswith("extraction_text") for key in payload["expected"])
    assert spec.expected.storage_key not in repr(spec.expected)


@pytest.mark.parametrize(
    "field,value",
    [
        ("visibility", "company"),
        ("corpus_id", "managed"),
        ("folder_id", "child"),
        ("deleted_at", "2026-10-07T00:00:00.000000"),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("tip_source_revision", True),
        ("tip_source_revision", 0),
        ("updated_at", "2026-10-07T00:00:00Z"),
        ("tip_event_digest", "A" * 64),
        ("storage_key", "synthetic\x00invalid"),
    ],
)
def test_fixed_expected_input_refuses_unsupported_or_noncanonical(spec, field, value):
    values = spec.expected.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        FileSourceDeleteExpected.model_validate(values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_user_id", "different-actor"),
        ("execution_ref", " synthetic "),
        ("file_id", "synthetic\nidentity"),
        ("extra", "unsupported"),
    ],
)
def test_fixed_spec_refuses_identity_and_unknown_fields(spec, field, value):
    values = spec.model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        FileSourceDeleteSpec.model_validate(values)


def test_original_event_id_cannot_be_used_as_result(spec):
    with pytest.raises(ValidationError):
        FileSourceDeleteSpec.model_validate(
            {**spec.model_dump(), "event_id": spec.expected.tip_event_id}
        )


def test_model_copy_bypass_is_revalidated_before_source_sql(spec, monkeypatch):
    engine = create_engine("sqlite://")
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append("sql"))
    bad = spec.model_copy(
        update={"expected": spec.expected.model_copy(update={"size_bytes": True})}
    )
    monkeypatch.setattr(
        mutations, "begin_file_source_stage", lambda db: pytest.fail("Source stage started")
    )
    with Session(engine) as db:
        with pytest.raises(FileSourceMutationRefused) as error:
            mutations.stage_native_root_file_soft_delete(db, spec=bad)
        assert error.value.reason == "source_contract_invalid" and error.value.__cause__ is None
        assert calls == [] and not db.in_transaction()
    engine.dispose()


def test_spec_byte_bound(spec):
    values = spec.model_dump()
    values["expected"]["storage_key"] = "🦄" * 1024
    with pytest.raises(ValidationError):
        FileSourceDeleteSpec.model_validate(values)


@pytest.mark.parametrize("entry", ["stage", "observer"])
@pytest.mark.parametrize("kind", ["active", "nested", "connection", "routed", "clause_routed"])
def test_actual_borrowed_or_routed_session_refusal_preserves_caller(spec, entry, kind, monkeypatch):
    engine = create_engine("sqlite://")
    connection = None
    if kind == "connection":
        connection = engine.connect()
        connection.begin()
        connection.execute(text("CREATE TABLE synthetic_marker(value INTEGER)"))
        connection.execute(text("INSERT INTO synthetic_marker VALUES(1)"))
        db = Session(connection, join_transaction_mode="rollback_only")
    elif kind == "routed":
        db = Session(engine, binds={AuthSession: engine.execution_options()})
    elif kind == "clause_routed":
        alternate = engine.execution_options()
        from sqlalchemy.sql.selectable import Select

        class RoutedSession(Session):
            def get_bind(self, mapper=None, clause=None, **kwargs):
                if (
                    isinstance(clause, Select)
                    and FileManagerFile.__table__ in clause.get_final_froms()
                ):
                    return alternate
                return super().get_bind(mapper=mapper, clause=clause, **kwargs)

        db = RoutedSession(engine)
    else:
        db = Session(engine)
        db.execute(text("CREATE TABLE synthetic_marker(value INTEGER)"))
        db.execute(text("INSERT INTO synthetic_marker VALUES(1)"))
        if kind == "nested":
            db.begin_nested()
    calls = []
    controls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append("sql"))
    original_close, original_rollback = db.close, db.rollback
    monkeypatch.setattr(db, "close", lambda: controls.append("close"))
    monkeypatch.setattr(db, "rollback", lambda: controls.append("rollback"))
    try:
        with pytest.raises(FileSourceMutationRefused):
            if entry == "stage":
                mutations.stage_native_root_file_soft_delete(db, spec=spec)
            else:
                mutations.observe_native_root_file_soft_delete(
                    db,
                    spec=spec,
                    expected_event_digest=mutations._intent(spec).digest(),
                    current_execution_ref=spec.execution_ref,
                )
        assert calls == [] and controls == []
        if kind in {"active", "nested"}:
            assert db.in_transaction()
            assert db.in_nested_transaction() == (kind == "nested")
            assert db.scalar(text("SELECT value FROM synthetic_marker")) == 1
        elif connection is not None:
            assert not connection.closed and connection.in_transaction()
            assert connection.scalar(text("SELECT value FROM synthetic_marker")) == 1
        else:
            assert not db.in_transaction()
    finally:
        original_rollback()
        original_close()
        if connection is not None:
            connection.rollback()
            connection.close()
        engine.dispose()


def test_mismatched_observer_digest_refuses_before_sql(spec, monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(
        mutations, "begin_file_source_stage", lambda db: pytest.fail("Source stage started")
    )
    with Session(engine) as db:
        with pytest.raises(FileSourceMutationConflict) as error:
            mutations.observe_native_root_file_soft_delete(
                db,
                spec=spec,
                expected_event_digest="0" * 64,
                current_execution_ref=spec.execution_ref,
            )
        assert error.value.reason == "mutation_witness_mismatch" and not db.in_transaction()
    engine.dispose()


def test_selective_file_load_never_requests_artifact_body():
    query = select(FileManagerFile).options(
        mutations.load_only(*mutations._FILE_COLUMNS, raiseload=True)
    )
    selected = str(query)
    assert "extraction_text" not in selected and "extraction_blocks" not in selected
    assert "extraction_metadata" not in selected


@pytest.mark.parametrize("entry", ["validator", "stage", "observer"])
@pytest.mark.parametrize("routing", ["text_only", "instance", "delegating"])
def test_custom_public_router_is_refused_before_invoking_it_or_sql(spec, entry, routing):
    from types import MethodType
    from sqlalchemy.sql.elements import TextClause

    first, second = create_engine("sqlite://"), create_engine("sqlite://")
    routes, sql = [], []
    event.listen(first, "before_cursor_execute", lambda *args: sql.append("first"))
    event.listen(second, "before_cursor_execute", lambda *args: sql.append("second"))

    def route(db, mapper=None, clause=None, **kwargs):
        routes.append("get_bind")
        if isinstance(clause, TextClause):
            return second
        return Session.get_bind(db, mapper=mapper, clause=clause, **kwargs)

    if routing == "text_only":

        class TextRoutedSession(Session):
            get_bind = route

        db = TextRoutedSession(first)
    elif routing == "instance":
        db = Session(first)
        db.get_bind = MethodType(route, db)
    else:

        class DelegatingSession(Session):
            def get_bind(self, **kwargs):
                routes.append("get_bind")
                return super().get_bind(**kwargs)

        db = DelegatingSession(first)
    try:
        # The declared ORM/default route does not expose a selective Text route.
        assert db.get_bind() is first
        if routing != "delegating":
            assert db.get_bind(clause=text("SET LOCAL search_path=public")) is second
        routes.clear()
        with pytest.raises(FileSourceMutationRefused) as error:
            if entry == "validator":
                require_fresh_file_extraction_session(db)
            elif entry == "stage":
                mutations.stage_native_root_file_soft_delete(db, spec=spec)
            else:
                mutations.observe_native_root_file_soft_delete(
                    db,
                    spec=spec,
                    expected_event_digest=mutations._intent(spec).digest(),
                    current_execution_ref=spec.execution_ref,
                )
        assert error.value.reason == "source_engine_binding_required"
        assert routes == [] and sql == [] and not db.in_transaction()
    finally:
        db.close()
        first.dispose()
        second.dispose()


def test_inherited_standard_router_and_same_engine_binds_remain_fresh():
    class InheritingSession(Session):
        pass

    engine = create_engine("sqlite://")
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append("sql"))
    with InheritingSession(
        engine, binds={AuthSession: engine, FileManagerFile.__table__: engine}
    ) as db:
        require_fresh_file_extraction_session(db)
        assert not db.in_transaction() and calls == []
    engine.dispose()
