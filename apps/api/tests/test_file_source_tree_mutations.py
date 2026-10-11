"""Bounded flat Source tree contracts and actual unchanged Source29 transactions."""

from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from test_file_source_mutations_authority import (
    native as native,
)
from test_file_source_mutations_authority import (
    extraction_prepared as extraction_prepared,
    file_source_prepared as file_source_prepared,
    isolated_data_cluster as isolated_data_cluster,
    role_template as role_template,
    world as world,
)

from miy_api.domains.files import source_tree_mutations as mutations
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceMutationRefused,
)
from miy_api.domains.files.source_tree_mutation_contracts import (
    FileSourceFolderDeleteExpected,
    FileSourceFolderDeleteMember,
    FileSourceFolderDeleteSpec,
    FileSourceFolderFileExpected,
)


@pytest.fixture
def spec():
    actor, folder = str(uuid4()), str(uuid4())
    partition = uuid4()
    stamp = datetime(2026, 10, 8, 12).isoformat(timespec="microseconds")
    members = []
    for identifier in sorted(str(uuid4()) for _ in range(2)):
        members.append(
            FileSourceFolderDeleteMember(
                file_id=identifier,
                event_id=uuid4(),
                expected=FileSourceFolderFileExpected(
                    owner_id=actor,
                    retrieval_partition_id=partition,
                    folder_id=folder,
                    storage_key="synthetic/private/" + identifier,
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
        )
    return FileSourceFolderDeleteSpec(
        folder_id=folder,
        actor_user_id=actor,
        execution_ref=str(uuid4()),
        expected=FileSourceFolderDeleteExpected(
            owner_id=actor,
            retrieval_partition_id=partition,
            name="Synthetic folder",
            created_at=stamp,
            updated_at=stamp,
        ),
        members=tuple(members),
    )


def test_bounded_aggregate_binds_every_file_and_folder_without_body_copy(spec):
    assert spec.digest() == sha256(spec.canonical().encode()).hexdigest()
    intents = [mutations._intent(spec, member) for member in spec.members]
    for member, intent in zip(spec.members, intents, strict=True):
        trace = intent.trace_context["files_source_mutation"]
        assert trace["command"] == "native_root_flat_folder_soft_delete"
        assert trace["spec_digest"] == spec.digest()
        assert trace["folder_before_digest"] == spec.expected.digest()
        assert trace["before_digest"] == member.expected.digest()
        assert trace["previous_event_id"] == str(member.expected.tip_event_id)
        assert (intent.resource_id, intent.desired_state, intent.content_checksum) == (
            member.file_id,
            "deleted",
            None,
        )
        assert member.expected.storage_key not in intent.canonical()
    changed = spec.model_copy(
        update={"expected": spec.expected.model_copy(update={"name": "Changed folder"})}
    )
    assert all(
        mutations._intent(changed, member).digest() != intent.digest()
        for member, intent in zip(spec.members, intents, strict=True)
    )
    assert "extraction_text" not in spec.canonical()
    assert "extraction_blocks" not in spec.canonical()
    assert "extraction_metadata" not in spec.canonical()


@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "excess",
        "order",
        "duplicate_file",
        "duplicate_event",
        "old_event",
        "folder",
        "owner",
        "partition",
        "nested",
    ],
)
def test_fixed_membership_identity_and_bounds_are_validated(spec, kind):
    values = spec.model_dump()
    if kind == "empty":
        values["members"] = ()
    elif kind == "excess":
        values["members"] = [values["members"][0]] * 17
    elif kind == "order":
        values["members"] = values["members"][::-1]
    elif kind == "duplicate_file":
        values["members"][1]["file_id"] = values["members"][0]["file_id"]
    elif kind == "duplicate_event":
        values["members"][1]["event_id"] = values["members"][0]["event_id"]
    elif kind == "old_event":
        values["members"][0]["event_id"] = values["members"][1]["expected"]["tip_event_id"]
    elif kind == "nested":
        values["expected"]["parent_id"] = "synthetic-parent"
    elif kind == "folder":
        values["members"][0]["expected"]["folder_id"] = "different-folder"
    elif kind == "owner":
        values["members"][0]["expected"]["owner_id"] = "different-owner"
    else:
        values["members"][0]["expected"]["retrieval_partition_id"] = uuid4()
    with pytest.raises(ValidationError):
        FileSourceFolderDeleteSpec.model_validate(values)


@pytest.mark.parametrize("entry", ["stage", "observe"])
def test_bypassed_model_is_revalidated_before_source_sql(spec, entry, monkeypatch):
    bad = spec.model_copy(update={"members": ()})
    engine = create_engine("sqlite://")
    calls = []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append("sql"))
    monkeypatch.setattr(
        mutations, "begin_file_source_stage", lambda db: pytest.fail("Source began")
    )
    try:
        with Session(engine) as db:
            with pytest.raises(FileSourceMutationRefused) as error:
                if entry == "stage":
                    mutations.stage_native_root_folder_soft_delete(db, spec=bad)
                else:
                    mutations.observe_native_root_folder_soft_delete(
                        db,
                        spec=bad,
                        expected_event_digests=(),
                        current_execution_ref=spec.execution_ref,
                    )
            assert error.value.reason == "source_contract_invalid"
            assert calls == [] and not db.in_transaction()
    finally:
        engine.dispose()


def test_bounded_canonical_total_includes_utf8_escaped_identity(spec):
    members = []
    for number in range(16):
        member = spec.members[0].model_dump()
        member.update(file_id=f"file-{number:02d}", event_id=uuid4())
        member["expected"].update(storage_key="🦄" * 1024, tip_event_id=uuid4())
        members.append(member)
    with pytest.raises(ValidationError):
        FileSourceFolderDeleteSpec.model_validate({**spec.model_dump(), "members": members})


@pytest.mark.parametrize("entry", ["stage", "observe"])
@pytest.mark.parametrize("kind", ["active", "connection", "custom_router"])
def test_borrowed_routed_caller_work_survives_before_sql_refusal(spec, entry, kind, monkeypatch):
    engine = create_engine("sqlite://")
    connection = None
    if kind == "connection":
        connection = engine.connect()
        connection.begin()
        connection.execute(text("CREATE TABLE synthetic_marker(value INTEGER)"))
        connection.execute(text("INSERT INTO synthetic_marker VALUES(1)"))
        db = Session(connection, join_transaction_mode="rollback_only")
    elif kind == "custom_router":

        class Router(Session):
            def get_bind(self, *args, **kwargs):
                pytest.fail("Custom router called")

        db = Router(engine)
    else:
        db = Session(engine)
        db.execute(text("CREATE TABLE synthetic_marker(value INTEGER)"))
        db.execute(text("INSERT INTO synthetic_marker VALUES(1)"))
    calls, controls = [], []
    event.listen(engine, "before_cursor_execute", lambda *args: calls.append("sql"))
    close, rollback = db.close, db.rollback
    monkeypatch.setattr(db, "close", lambda: controls.append("close"))
    monkeypatch.setattr(db, "rollback", lambda: controls.append("rollback"))
    try:
        with pytest.raises(FileSourceMutationRefused):
            if entry == "stage":
                mutations.stage_native_root_folder_soft_delete(db, spec=spec)
            else:
                mutations.observe_native_root_folder_soft_delete(
                    db,
                    spec=spec,
                    expected_event_digests=tuple(
                        mutations._intent(spec, m).digest() for m in spec.members
                    ),
                    current_execution_ref=spec.execution_ref,
                )
        assert calls == [] and controls == []
        if connection is not None:
            assert connection.in_transaction()
            assert connection.scalar(text("SELECT value FROM synthetic_marker")) == 1
        elif kind == "active":
            assert (
                db.in_transaction() and db.scalar(text("SELECT value FROM synthetic_marker")) == 1
            )
    finally:
        monkeypatch.setattr(db, "close", close)
        monkeypatch.setattr(db, "rollback", rollback)
        close()
        if connection is not None:
            connection.rollback()
            connection.close()
        engine.dispose()


def test_body_columns_are_not_selected():
    query = select(FileManagerFile).options(
        mutations.load_only(*mutations._FILE_COLUMNS, raiseload=True)
    )
    columns = {column.name for column in query.selected_columns}
    # SQL compilation, rather than Select.selected_columns, reflects load_only.
    from sqlalchemy.dialects import postgresql

    compiled = str(query.compile(dialect=postgresql.dialect()))
    assert columns
    assert all(
        name not in compiled
        for name in ("extraction_text", "extraction_blocks", "extraction_metadata")
    )
