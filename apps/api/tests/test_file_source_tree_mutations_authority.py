"""Actual unchanged Source29 flat-tree transactions and failure boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from test_file_source_mutations_authority import (
    assert_core_and_privileges_unchanged,
    native as native,
    extraction_prepared as extraction_prepared,
    file_source_prepared as file_source_prepared,
    isolated_data_cluster as isolated_data_cluster,
    role_template as role_template,
    world as world,
)
from test_file_source_partition_roles import wait_for_exact_blocker

from miy_api.domains.auth.models import AuthSession
from miy_api.domains.files import source_tree_mutations as mutations
from miy_api.domains.files.models import FileManagerFile, FileManagerFolder
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceMutationConflict,
    FileSourceMutationRefused,
)
from miy_api.domains.files.source_tree_mutation_contracts import (
    FileSourceFolderDeleteMember,
    FileSourceFolderDeleteSpec,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import append_projection_intent


@pytest.fixture
def flat(native, request):
    count = getattr(request, "param", 1)
    folder_id = str(uuid4())
    identifiers = [native.file_id] + [str(uuid4()) for _ in range(count - 1)]
    before = {}
    with Session(native.engine) as db:
        folder = FileManagerFolder(
            id=folder_id,
            owner_id=native.world.user_id,
            name="Owned private flat folder",
            visibility="private",
            retrieval_partition_id=native.roles.partition,
        )
        db.add(folder)
        db.flush()
        for identifier in sorted(identifiers):
            file = db.get(FileManagerFile, identifier)
            if file is None:
                file = FileManagerFile(
                    id=identifier,
                    owner_id=native.world.user_id,
                    filename="Owned extra.txt",
                    content_type="text/plain",
                    size_bytes=25,
                    storage_key="owned-no-storage/" + identifier,
                    visibility="private",
                    retrieval_partition_id=native.roles.partition,
                    extraction_status="ready",
                    extraction_content_checksum=native.before["extraction_content_checksum"],
                    extraction_text="Owned synthetic ready body",
                    extraction_blocks=[{"text": "Owned synthetic ready body"}],
                    extraction_metadata={"parser_version": "owned-synthetic"},
                    extracted_at=datetime.now(UTC).replace(tzinfo=None),
                )
                db.add(file)
            file.folder_id = folder_id
            db.flush()
            tip = append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=file.id,
                    retrieval_partition_id=file.retrieval_partition_id,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                    content_checksum=file.extraction_content_checksum,
                ),
                event_id=uuid4(),
            )
            before[identifier] = mutations._file_before(file, tip)
        folder_before = mutations._folder_before(folder)
        db.commit()
    value = SimpleNamespace(
        native=native,
        folder_id=folder_id,
        spec=FileSourceFolderDeleteSpec(
            folder_id=folder_id,
            actor_user_id=native.world.user_id,
            execution_ref=native.world.session_id,
            expected=folder_before,
            members=tuple(
                FileSourceFolderDeleteMember(
                    file_id=identifier, event_id=uuid4(), expected=expected
                )
                for identifier, expected in sorted(before.items())
            ),
        ),
    )
    value.original = rows(value)
    return value


def rows(flat):
    with flat.native.world.connect() as conn:
        folder = conn.execute(
            "SELECT owner_id,parent_id,corpus_id,visibility,retrieval_partition_id,deleted_at,updated_at "
            "FROM public.file_manager_folders WHERE id=%s",
            (flat.folder_id,),
        ).fetchone()
        files = conn.execute(
            "SELECT id,folder_id,deleted_at,extraction_status,extraction_content_checksum,extraction_text,"
            "extraction_blocks,extraction_metadata,extraction_error_code,extracted_at,updated_at "
            "FROM public.file_manager_files WHERE folder_id=%s ORDER BY id",
            (flat.folder_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_id,payload,payload_digest,source_revision FROM public.official_projection_outbox "
            "WHERE event_id=ANY(%s::uuid[]) ORDER BY event_id",
            ([str(m.event_id) for m in flat.spec.members],),
        ).fetchall()
        return folder, files, events


def observe(flat):
    with Session(flat.native.engine) as db:
        receipt = mutations.observe_native_root_folder_soft_delete(
            db,
            spec=flat.spec,
            expected_event_digests=tuple(
                mutations._intent(flat.spec, m).digest() for m in flat.spec.members
            ),
            current_execution_ref=flat.native.world.session_id,
        )
        db.commit()
        return receipt


@pytest.mark.parametrize("flat", [1, 3, 16], indirect=True)
def test_actual_source29_atomic_flat_tree_and_history_without_core_effect(flat):
    with Session(flat.native.engine) as db:
        receipt = mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert receipt.provisional and not receipt.historical
        assert rows(flat) == flat.original
        db.commit()
    folder, files, events = rows(flat)
    assert folder[5] is not None
    assert len(files) == len(events) == len(flat.spec.members)
    for file in files:
        assert file[2] == folder[5]
        assert file[3:10] == ("pending", None, None, [], {}, None, None)
    history = observe(flat)
    assert history.historical and history.provisional
    assert all(event.historical and event.provisional for event in history.events)
    assert [e.event_digest for e in history.events] == [e.event_digest for e in receipt.events]
    assert_core_and_privileges_unchanged(flat.native)


def test_actual_outer_rollback_leaves_folder_files_and_events_unchanged(flat):
    with Session(flat.native.engine) as db:
        mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        db.rollback()
    assert rows(flat) == flat.original and observe(flat) is None
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("flat", [3], indirect=True)
@pytest.mark.parametrize("failure", ["last_append", "final_authority"])
def test_actual_after_flush_and_partial_append_failure_is_atomic(flat, monkeypatch, failure):
    if failure == "last_append":
        append = mutations.append_projection_intent
        calls = []

        def fail(db, **kwargs):
            calls.append(kwargs["event_id"])
            result = append(db, **kwargs)
            if len(calls) == len(flat.spec.members):
                raise FileSourceMutationRefused("owned_final_refusal")
            return result

        monkeypatch.setattr(mutations, "append_projection_intent", fail)
    else:
        current = mutations._current

        def fail(db, folder, files, spec, execution_ref):
            current(db, folder, files, spec, execution_ref)
            if folder.deleted_at is not None:
                assert db.get(OfficialProjectionOutbox, str(spec.members[-1].event_id)) is not None
                raise FileSourceMutationRefused("owned_final_refusal")

        monkeypatch.setattr(mutations, "_current", fail)
    with Session(flat.native.engine) as db:
        with pytest.raises(FileSourceMutationRefused) as error:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert error.value.reason == "owned_final_refusal" and not db.in_transaction()
    assert rows(flat) == flat.original
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("change", ["nested", "extra", "missing"])
def test_actual_unexpected_membership_refuses_without_mutation(flat, change):
    with Session(flat.native.engine) as db:
        if change == "nested":
            db.add(
                FileManagerFolder(
                    id=str(uuid4()),
                    parent_id=flat.folder_id,
                    owner_id=flat.spec.actor_user_id,
                    name="Unexpected nested",
                    visibility="private",
                    retrieval_partition_id=flat.native.roles.partition,
                )
            )
        elif change == "missing":
            db.get(FileManagerFile, flat.spec.members[0].file_id).folder_id = None
        else:
            db.add(
                FileManagerFile(
                    id=str(uuid4()),
                    folder_id=flat.folder_id,
                    owner_id=flat.spec.actor_user_id,
                    filename="Unexpected",
                    storage_key="owned-no-storage/" + str(uuid4()),
                    visibility="private",
                    retrieval_partition_id=flat.native.roles.partition,
                )
            )
        db.commit()
    before = rows(flat)
    with Session(flat.native.engine) as db:
        with pytest.raises(FileSourceMutationConflict) as error:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert error.value.reason == "source_tree_membership_changed"
    assert rows(flat) == before and not before[2]
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("kind", ["file", "folder"])
def test_actual_folder_update_blocks_both_fk_children_only_until_commit(flat, kind):
    ready = {}
    started = Event()
    identifier = str(uuid4())

    def raw_child():
        with Session(flat.native.engine) as db:
            ready["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            if kind == "folder":
                db.add(
                    FileManagerFolder(
                        id=identifier,
                        parent_id=flat.folder_id,
                        owner_id=flat.spec.actor_user_id,
                        name="Raw child",
                        visibility="private",
                        retrieval_partition_id=flat.native.roles.partition,
                    )
                )
            else:
                db.add(
                    FileManagerFile(
                        id=identifier,
                        folder_id=flat.folder_id,
                        owner_id=flat.spec.actor_user_id,
                        filename="Raw child",
                        storage_key="owned-no-storage/" + identifier,
                        visibility="private",
                        retrieval_partition_id=flat.native.roles.partition,
                    )
                )
            db.flush()
            db.commit()

    with Session(flat.native.engine) as db, ThreadPoolExecutor(max_workers=1) as pool:
        mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        blocker = db.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(raw_child)
        assert started.wait(3)
        try:
            wait_for_exact_blocker(flat.native.world, ready["pid"], blocker)
            assert not future.done()
        finally:
            db.commit()
        future.result(timeout=8)
    with flat.native.world.connect() as conn:
        table = "file_manager_folders" if kind == "folder" else "file_manager_files"
        assert conn.execute(
            "SELECT EXISTS(SELECT 1 FROM public." + table + " WHERE id=%s)", (identifier,)
        ).fetchone()[0]
    # FK does not enforce live-parent business policy after the Stage COMMIT.
    assert observe(flat).historical
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("flat", [16], indirect=True)
def test_actual_seventeenth_member_refused_without_unbounded_discovery(flat):
    with Session(flat.native.engine) as db:
        db.add(
            FileManagerFile(
                id=str(uuid4()),
                folder_id=flat.folder_id,
                owner_id=flat.spec.actor_user_id,
                filename="Seventeenth",
                storage_key="owned-no-storage/" + str(uuid4()),
                visibility="private",
                retrieval_partition_id=flat.native.roles.partition,
            )
        )
        db.commit()
    before = rows(flat)
    assert len(before[1]) == 17
    with Session(flat.native.engine) as db:
        with pytest.raises(FileSourceMutationConflict) as error:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert error.value.reason == "source_tree_membership_changed"
    assert rows(flat) == before
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("phase", ["folder", "event"])
@pytest.mark.parametrize("revocation", ["session", "app"])
def test_actual_current_authority_rechecked_after_last_lock_wait(flat, phase, revocation):
    blocker = flat.native.world.connect(flat.native.roles.source)
    state = {}
    started = Event()

    def stage():
        with Session(flat.native.engine) as db:
            original = db.get_bind()

            # Event observation on the Engine does not override Session routing.
            def backend(connection, *args):
                if "pid" not in state:
                    state["pid"] = connection.connection.driver_connection.info.backend_pid
                    started.set()

            event.listen(original, "before_cursor_execute", backend)
            try:
                receipt = mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
                db.commit()
                return receipt
            finally:
                event.remove(original, "before_cursor_execute", backend)

    try:
        if phase == "folder":
            blocker.execute(
                "SELECT id FROM public.file_manager_folders WHERE id=%s FOR UPDATE",
                (flat.folder_id,),
            )
        else:
            blocker.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                ("official.projection.event:" + str(flat.spec.members[-1].event_id),),
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(stage)
            assert started.wait(3)
            try:
                wait_for_exact_blocker(flat.native.world, state["pid"], blocker.info.backend_pid)
                assert not future.done()
                with flat.native.world.connect() as conn:
                    if revocation == "session":
                        conn.execute(
                            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
                            (flat.native.world.session_id,),
                        )
                    else:
                        conn.execute(
                            "UPDATE public.company_app_controls SET enabled=false WHERE app_id='files'"
                        )
            finally:
                blocker.rollback()
            with pytest.raises(FileSourceMutationRefused) as error:
                future.result(timeout=8)
            assert error.value.reason == (
                "current_execution_denied"
                if revocation == "session"
                else "current_actor_or_app_denied"
            )
        assert rows(flat) == flat.original
        assert_core_and_privileges_unchanged(flat.native)
    finally:
        blocker.close()


def test_actual_collision_with_other_genuine_file_event_cannot_mutate(flat):
    collision = flat.spec.members[0].event_id
    with Session(flat.native.engine) as db:
        file = FileManagerFile(
            id=str(uuid4()),
            owner_id=flat.spec.actor_user_id,
            filename="Other native",
            storage_key="owned-no-storage/" + str(uuid4()),
            visibility="private",
            retrieval_partition_id=flat.native.roles.partition,
        )
        db.add(file)
        db.flush()
        append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file.id,
                retrieval_partition_id=file.retrieval_partition_id,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=collision,
        )
        db.commit()
    before = rows(flat)
    with Session(flat.native.engine) as db:
        with pytest.raises(FileSourceMutationRefused) as error:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert error.value.reason == "mutation_observation_required"
    assert rows(flat) == before
    with pytest.raises(FileSourceMutationConflict) as error:
        observe(flat)
    assert error.value.reason == "mutation_witness_mismatch"
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("committed", [False, True])
def test_actual_unknown_caller_commit_can_only_observe_same_event_set(flat, committed):
    with Session(flat.native.engine) as db:
        receipt = mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        commit = db.commit

        def uncertain():
            if committed:
                commit()
            raise RuntimeError("Owned synthetic COMMIT acknowledgement loss")

        db.commit = uncertain
        with pytest.raises(RuntimeError):
            db.commit()
        if not committed:
            db.rollback()
    current = observe(flat)
    assert (current is not None) is committed
    assert receipt.provisional
    if current is not None:
        assert current.historical and current.spec_digest == receipt.spec_digest
        assert [e.event_id for e in current.events] == [e.event_id for e in receipt.events]
    else:
        assert rows(flat) == flat.original
    assert_core_and_privileges_unchanged(flat.native)


def test_actual_later_tip_and_current_session_observe_history_without_reapply(flat):
    with Session(flat.native.engine) as db:
        receipt = mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        db.commit()
    with Session(flat.native.engine) as db:
        db.get(FileManagerFolder, flat.folder_id).deleted_at = None
        for member in flat.spec.members:
            file = db.get(FileManagerFile, member.file_id)
            file.deleted_at = None
            file.extraction_status = "pending"
            db.flush()
            append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=file.id,
                    retrieval_partition_id=file.retrieval_partition_id,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                ),
                event_id=uuid4(),
            )
        db.commit()
    session_id = str(uuid4())
    with Session(flat.native.world.engine) as db:
        db.get(AuthSession, flat.spec.execution_ref).revoked_at = datetime.now(UTC).replace(
            tzinfo=None
        )
        db.add(
            AuthSession(
                id=session_id,
                user_id=flat.spec.actor_user_id,
                token_hash="synthetic-" + session_id,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )
        )
        db.commit()
    before = rows(flat)
    with Session(flat.native.engine) as db:
        history = mutations.observe_native_root_folder_soft_delete(
            db,
            spec=flat.spec,
            current_execution_ref=session_id,
            expected_event_digests=tuple(e.event_digest for e in receipt.events),
        )
        db.commit()
    assert history.historical and rows(flat) == before
    assert before[0][5] is None and all(file[2] is None for file in before[1])
    assert_core_and_privileges_unchanged(flat.native)


def test_actual_legacy_exclusive_descriptor_then_folder_waits_for_source(flat):
    legacy = flat.native.world.connect()
    try:
        with Session(flat.native.engine) as db, ThreadPoolExecutor(max_workers=1) as pool:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
            blocker = db.scalar(text("SELECT pg_backend_pid()"))

            def tree():
                legacy.execute(
                    "SELECT id FROM public.retrieval_partitions WHERE id=%s::uuid FOR UPDATE",
                    (flat.native.roles.partition,),
                )
                return legacy.execute(
                    "SELECT deleted_at FROM public.file_manager_folders WHERE id=%s FOR UPDATE",
                    (flat.folder_id,),
                ).fetchone()[0]

            future = pool.submit(tree)
            try:
                wait_for_exact_blocker(flat.native.world, legacy.info.backend_pid, blocker)
                assert not future.done() and rows(flat) == flat.original
            finally:
                db.commit()
            assert future.result(timeout=8) is not None
        legacy.rollback()
        assert_core_and_privileges_unchanged(flat.native)
    finally:
        legacy.close()


def test_actual_same_target_second_stage_cannot_overtake_or_duplicate(flat):
    replacement = FileSourceFolderDeleteSpec.model_validate(
        {
            **flat.spec.model_dump(),
            "members": [
                {**member.model_dump(), "event_id": uuid4()} for member in flat.spec.members
            ],
        }
    )
    started, state = Event(), {}

    def competing():
        with Session(flat.native.engine) as db:
            engine = db.get_bind()

            def backend(connection, *args):
                if "pid" not in state:
                    state["pid"] = connection.connection.driver_connection.info.backend_pid
                    started.set()

            event.listen(engine, "before_cursor_execute", backend)
            try:
                result = mutations.stage_native_root_folder_soft_delete(db, spec=replacement)
                db.commit()
                return result
            finally:
                event.remove(engine, "before_cursor_execute", backend)

    with (
        flat.native.world.connect(autocommit=True) as observer,
        Session(flat.native.engine) as db,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        first = mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        blocker = db.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(competing)
        assert started.wait(3)
        try:
            wait_for_exact_blocker(flat.native.world, state["pid"], blocker, observer=observer)
            assert not future.done()
        finally:
            db.commit()
        with pytest.raises(FileSourceMutationRefused) as error:
            future.result(timeout=8)
        assert error.value.reason == "mutation_observation_required"
    with flat.native.world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM public.official_projection_outbox WHERE event_id=ANY(%s::uuid[])",
                ([str(member.event_id) for member in replacement.members],),
            ).fetchone()[0]
            == 0
        )
    assert len(rows(flat)[2]) == len(first.events)
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("flat", [3], indirect=True)
def test_actual_partial_immutable_witness_is_refused_without_repair(flat):
    # A trusted raw Source caller can publish a partial command witness because
    # this Stage has no SQL terminal seal. Observation must never repair it.
    with Session(flat.native.engine) as db:
        member = flat.spec.members[0]
        file = db.get(FileManagerFile, member.file_id)
        file.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        file.extraction_status = "pending"
        file.extraction_content_checksum = None
        file.extraction_text = None
        file.extraction_blocks = []
        file.extraction_metadata = {}
        file.extraction_error_code = None
        file.extracted_at = None
        db.flush()
        append_projection_intent(
            db, intent=mutations._intent(flat.spec, member), event_id=member.event_id
        )
        db.commit()
    before = rows(flat)
    with pytest.raises(FileSourceMutationConflict) as error:
        observe(flat)
    assert error.value.reason == "mutation_witness_incomplete"
    assert rows(flat) == before and len(before[2]) == 1
    assert_core_and_privileges_unchanged(flat.native)


@pytest.mark.parametrize("kind", ["company_folder", "grant", "stale_folder"])
def test_actual_current_scope_and_folder_before_are_not_detached_authority(flat, kind):
    from miy_api.domains.files.models import FileManagerFileAccessGrant

    with Session(flat.native.engine) as db:
        folder = db.get(FileManagerFolder, flat.folder_id)
        if kind == "company_folder":
            folder.visibility = "company"
        elif kind == "stale_folder":
            folder.name = "Later folder name"
        else:
            db.add(
                FileManagerFileAccessGrant(
                    id=str(uuid4()),
                    file_id=flat.spec.members[0].file_id,
                    grant_type="user",
                    target_id=flat.spec.actor_user_id,
                    grant_key="user:" + flat.spec.actor_user_id,
                )
            )
        db.commit()
    before = rows(flat)
    with Session(flat.native.engine) as db:
        expected = (
            FileSourceMutationConflict if kind == "stale_folder" else FileSourceMutationRefused
        )
        with pytest.raises(expected) as error:
            mutations.stage_native_root_folder_soft_delete(db, spec=flat.spec)
        assert error.value.reason == (
            "source_state_changed" if kind == "stale_folder" else "current_source_scope_unavailable"
        )
    assert rows(flat) == before and not before[2]
    assert_core_and_privileges_unchanged(flat.native)
