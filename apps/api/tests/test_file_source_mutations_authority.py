"""Fixed leaf Source mutations on the unchanged restricted Source29 profile."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import pytest
from company_admission_fixture import seed_company_app_access
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import snapshot
from test_file_projection_roles import reader_engine
from test_file_source_partition_roles import file_source_prepared as file_source_prepared
from test_file_source_partition_roles import wait_for_exact_blocker
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied,
)
from test_official_writer_roles import (
    role_template as role_template,
)
from test_official_writer_roles import (
    world as world,
)

from miy_api.domains.auth.models import AuthSession, UserSystemRole
from miy_api.domains.files import source_mutations as mutations
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceDeleteSpec,
    FileSourceMutationConflict,
    FileSourceMutationRefused,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_outbox import append_projection_intent
from miy_api.domains.retrieval.prepared_file_partitions import (
    require_prepared_file_source_partition,
)


@pytest.fixture
def native(world, file_source_prepared):
    """Only Core setup is privileged; business File/event uses actual Source."""
    with Session(world.engine) as db:
        seed_company_app_access(db, app_ids=("files",))
        # The role/owner were already explicitly prepared by a current admin.
        # The actor under test is now an ordinary owner, not that setup admin.
        db.execute(delete(UserSystemRole).where(UserSystemRole.user_id == world.user_id))
        db.commit()
    engine = reader_engine(world, file_source_prepared.source)
    identifier = str(uuid4())
    checksum = sha256(b"Owned synthetic raw input").hexdigest()
    with Session(engine) as db:
        file = FileManagerFile(
            id=identifier,
            owner_id=world.user_id,
            filename="Owned.txt",
            content_type="text/plain",
            size_bytes=25,
            storage_key="owned-no-storage/" + identifier,
            visibility="private",
            retrieval_partition_id=file_source_prepared.partition,
            extraction_status="ready",
            extraction_content_checksum=checksum,
            extraction_text="Owned synthetic ready body",
            extraction_blocks=[{"text": "Owned synthetic ready body"}],
            extraction_metadata={"parser_version": "owned-synthetic"},
            extracted_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(file)
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
                content_checksum=checksum,
            ),
            event_id=uuid4(),
        )
        before = {
            key: getattr(file, key)
            for key in (
                "storage_key",
                "size_bytes",
                "filename",
                "content_type",
                "owner_id",
                "visibility",
                "retrieval_partition_id",
                "updated_at",
                "created_at",
                "extraction_status",
                "extraction_content_checksum",
                "extraction_error_code",
                "extracted_at",
            )
        }
        tip_values = (str(tip.event_id), tip.payload_digest, tip.source_revision)
        db.commit()
    value = SimpleNamespace(
        world=world,
        roles=file_source_prepared,
        engine=engine,
        file_id=identifier,
        before=before,
        tip=tip_values,
        event_id=uuid4(),
    )
    value.original = file_row(value)
    value.spec = FileSourceDeleteSpec(
        file_id=identifier,
        actor_user_id=world.user_id,
        execution_ref=world.session_id,
        event_id=value.event_id,
        expected=FileSourceDeleteExpected(
            **{
                key: item.isoformat(timespec="microseconds") if isinstance(item, datetime) else item
                for key, item in before.items()
            },
            tip_event_id=tip_values[0],
            tip_event_digest=tip_values[1],
            tip_source_revision=tip_values[2],
        ),
    )
    value.core_before = core_rows(value)
    value.privileges_before = snapshot(world, file_source_prepared.source)
    yield value
    engine.dispose()


def file_row(native):
    with native.world.connect() as conn:
        return conn.execute(
            "SELECT owner_id,corpus_id,folder_id,visibility,retrieval_partition_id,"
            "deleted_at,extraction_status,extraction_content_checksum,extraction_text,"
            "extraction_blocks,extraction_metadata,extraction_error_code,extracted_at,updated_at "
            "FROM public.file_manager_files WHERE id=%s",
            (native.file_id,),
        ).fetchone()


def core_rows(native):
    """Fixture diagnosis cannot expand the Source caller's database authority."""
    with native.world.connect() as conn:
        counts = tuple(
            conn.execute("SELECT count(*) FROM public." + table).fetchone()[0]
            for table in (
                "official_projection_receipts",
                "retrieval_projection_events",
                "retrieval_projection_heads",
                "search_index_jobs",
                "rag_sync_jobs",
                "audit_logs",
                "file_extraction_requests",
                "file_manager_storage_cleanup_jobs",
            )
        )
        descriptors = conn.execute(
            "SELECT id,source_namespace,candidate_scope_kind,candidate_user_id,state,"
            "is_default_ingest,metadata_version,xmin::text FROM public.retrieval_partitions "
            "ORDER BY id"
        ).fetchall()
        return counts, descriptors


def selected_event(native):
    with native.world.connect() as conn:
        return conn.execute(
            "SELECT resource_type,resource_id,source_revision,payload,payload_digest,"
            "producer_generation,producer_artifact,producer_role_oid,producer_role_name "
            "FROM public.official_projection_outbox WHERE event_id=%s::uuid",
            (str(native.event_id),),
        ).fetchone()


def assert_core_and_privileges_unchanged(native):
    assert core_rows(native) == native.core_before
    assert snapshot(native.world, native.roles.source) == native.privileges_before


def test_actual_existing_source_profile_admits_only_uuid_capability(native):
    with Session(native.engine) as db:
        db.execute(text("SELECT public.miy_file_extraction_admit(NULL)"))
        assert (
            str(
                require_prepared_file_source_partition(
                    db,
                    partition_id=native.roles.partition,
                    managed_metadata_version=None,
                )
            )
            == native.roles.partition
        )
        assert (
            db.scalar(
                select(FileManagerFile.id).where(
                    FileManagerFile.id == native.file_id,
                )
            )
            == native.file_id
        )
        db.rollback()
    with native.world.connect(native.roles.source) as conn:
        for statement in (
            "SELECT id FROM public.retrieval_partitions",
            "SELECT id FROM public.retrieval_partitions FOR SHARE",
            "UPDATE public.retrieval_partitions SET state=state WHERE false",
            "INSERT INTO public.official_projection_receipts SELECT * FROM public.official_projection_receipts WHERE false",
            "INSERT INTO public.retrieval_projection_events SELECT * FROM public.retrieval_projection_events WHERE false",
            "SELECT token_hash FROM public.auth_sessions",
            "SELECT password_hash FROM public.users",
            "SELECT public.miy_lock_file_projection_partition(NULL)",
        ):
            denied(conn, statement)
    assert_core_and_privileges_unchanged(native)


def stage(native, *, commit=True):
    with Session(native.engine) as db:
        receipt = mutations.stage_native_root_file_soft_delete(db, spec=native.spec)
        if commit:
            db.commit()
        else:
            db.rollback()
        return receipt


def observe(native, digest, *, execution_ref=None):
    with Session(native.engine) as db:
        receipt = mutations.observe_native_root_file_soft_delete(
            db,
            spec=native.spec,
            expected_event_digest=digest,
            current_execution_ref=execution_ref or native.spec.execution_ref,
        )
        db.commit()
        return receipt


def assert_purged_deleted(native):
    row = file_row(native)
    assert row[:5] == native.original[:5]
    assert row[5] is not None
    assert row[6:13] == ("pending", None, None, [], {}, None, None)


def test_actual_source_file_purge_delete_event_and_provenance_commit(native):
    receipt = stage(native)
    assert receipt.provisional and not receipt.historical
    assert receipt.event_id == native.spec.event_id
    assert receipt.spec_digest == native.spec.digest()
    assert receipt.source_revision == native.tip[2] + 1
    assert receipt.producer_role_name == native.roles.source
    assert receipt.producer_generation == native.roles.identity.generation
    assert receipt.producer_artifact == native.roles.identity.artifact
    with native.world.connect() as conn:
        assert (
            receipt.producer_role_oid
            == conn.execute(
                "SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s", (native.roles.source,)
            ).fetchone()[0]
        )
    assert_purged_deleted(native)
    persisted = selected_event(native)
    assert persisted[:3] == ("file_manager_file", native.file_id, native.tip[2] + 1)
    intent = ProjectionIntent.model_validate_json(persisted[3])
    assert (
        intent.operation,
        intent.change_kind,
        intent.desired_state,
        intent.content_checksum,
    ) == (
        "delete",
        "delete",
        "deleted",
        None,
    )
    assert intent.digest() == persisted[4] == receipt.event_digest
    provenance = intent.trace_context["files_source_mutation"]
    assert provenance["spec_digest"] == native.spec.digest()
    assert provenance["before_digest"] == native.spec.expected.digest()
    assert (
        provenance["previous_event_id"],
        provenance["previous_event_digest"],
        provenance["previous_source_revision"],
    ) == native.tip
    assert provenance["actor_user_id"] == native.world.user_id
    assert provenance["execution_ref"] == native.world.session_id
    assert native.spec.expected.storage_key not in persisted[3]
    assert observe(native, receipt.event_digest).historical
    assert_core_and_privileges_unchanged(native)


def test_actual_stage_flush_is_provisional_outer_rollback_restores_every_source_field(native):
    receipt = stage(native, commit=False)
    assert receipt.provisional
    assert file_row(native) == native.original
    assert selected_event(native) is None
    assert observe(native, receipt.event_digest) is None
    assert_core_and_privileges_unchanged(native)


def test_actual_file_and_intent_flush_rollback_after_final_authority_refusal(native, monkeypatch):
    original = mutations._current
    calls = []

    def refuse_after_event(db, file, spec, execution_ref):
        original(db, file, spec, execution_ref)
        persisted = db.scalar(
            select(FileManagerFile.deleted_at).where(
                FileManagerFile.id == native.file_id,
            )
        )
        if persisted is not None:
            # Both writes were really flushed on this restricted Source txn.
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM public.official_projection_outbox WHERE event_id=CAST(:id AS uuid)"
                    ),
                    {"id": str(native.event_id)},
                )
                == 1
            )
            calls.append("actual_file_and_event_flushed")
            raise FileSourceMutationRefused("owned_final_refusal")

    monkeypatch.setattr(mutations, "_current", refuse_after_event)
    with pytest.raises(FileSourceMutationRefused) as error:
        stage(native)
    assert error.value.reason == "owned_final_refusal"
    assert calls == ["actual_file_and_event_flushed"]
    assert file_row(native) == native.original and selected_event(native) is None
    assert_core_and_privileges_unchanged(native)


@pytest.mark.parametrize("change", ["filename", "binding", "tip", "grant", "metadata", "company"])
def test_actual_changed_source_state_or_scope_refuses_without_delete(native, change):
    with Session(native.engine) as db:
        if change == "filename":
            db.get(FileManagerFile, native.file_id).filename = "Changed.txt"
        elif change == "binding":
            db.get(FileManagerFile, native.file_id).retrieval_partition_id = None
        elif change == "grant":
            db.add(
                FileManagerFileAccessGrant(
                    id=str(uuid4()),
                    file_id=native.file_id,
                    grant_type="user",
                    target_id=native.world.user_id,
                    grant_key="user:" + native.world.user_id,
                )
            )
        elif change == "metadata":
            corpus_id = str(uuid4())
            db.add(
                FileManagerCorpus(
                    id=corpus_id,
                    name="Owned unsupported source corpus",
                    retrieval_partition_id=native.roles.partition,
                    created_by_id=native.world.user_id,
                )
            )
            db.flush()
            db.add(
                FileManagerFileSourceMetadata(
                    file_id=native.file_id,
                    corpus_id=corpus_id,
                    external_id="owned",
                    external_id_sha256="a" * 64,
                    source_kind="owned",
                    source_id="owned",
                    source_id_sha256="b" * 64,
                    content_checksum=native.spec.expected.extraction_content_checksum,
                )
            )
        elif change == "company":
            db.get(FileManagerFile, native.file_id).visibility = "company"
        else:
            append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=native.file_id,
                    retrieval_partition_id=native.roles.partition,
                    change_kind="visibility",
                    desired_state="active",
                    operation="visibility_update",
                    content_checksum=native.spec.expected.extraction_content_checksum,
                ),
                event_id=uuid4(),
            )
        db.commit()
    changed = file_row(native)
    with pytest.raises((FileSourceMutationRefused, FileSourceMutationConflict)):
        stage(native)
    assert file_row(native) == changed and selected_event(native) is None
    assert_core_and_privileges_unchanged(native)


def test_actual_existing_retained_event_refuses_then_mismatch_observer_conflicts(native):
    with Session(native.engine) as db:
        append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=native.file_id,
                retrieval_partition_id=native.roles.partition,
                change_kind="visibility",
                desired_state="active",
                operation="visibility_update",
                content_checksum=native.spec.expected.extraction_content_checksum,
            ),
            event_id=native.event_id,
        )
        db.commit()
    collision = selected_event(native)
    with pytest.raises((FileSourceMutationRefused, FileSourceMutationConflict)):
        stage(native)
    with pytest.raises(FileSourceMutationConflict):
        observe(native, mutations._intent(native.spec).digest())
    assert file_row(native) == native.original
    assert selected_event(native) == collision
    assert_core_and_privileges_unchanged(native)


@pytest.mark.parametrize("commit_happened", [False, True])
def test_actual_unknown_caller_commit_observes_only_retained_witness(native, commit_happened):
    with Session(native.engine) as db:
        receipt = mutations.stage_native_root_file_soft_delete(db, spec=native.spec)
        if commit_happened:
            db.commit()
        # Synthetic lost ACK wraps the caller's genuine before/after COMMIT.
        with pytest.raises(RuntimeError, match="owned_commit_ack_unknown"):
            raise RuntimeError("owned_commit_ack_unknown")
    rows = file_row(native), selected_event(native)
    observed = observe(native, receipt.event_digest)
    assert (observed is not None) == commit_happened
    if observed is not None:
        assert observed.historical and observed.provisional
        assert observed.event_id == receipt.event_id
        assert observed.event_digest == receipt.event_digest
        with pytest.raises(FileSourceMutationRefused) as error:
            stage(native)
        assert error.value.reason == "mutation_observation_required"
    else:
        assert rows == (native.original, None)
    assert (file_row(native), selected_event(native)) == rows
    assert_core_and_privileges_unchanged(native)


def test_actual_immutable_event_observation_after_later_tip_and_new_current_session(native):
    receipt = stage(native)
    immutable = selected_event(native)
    current_session = str(uuid4())
    with Session(native.world.engine) as db:
        db.get(AuthSession, native.world.session_id).revoked_at = datetime.now(UTC).replace(
            tzinfo=None
        )
        db.add(
            AuthSession(
                id=current_session,
                user_id=native.world.user_id,
                token_hash=uuid4().hex + uuid4().hex,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
            )
        )
        db.commit()
    with Session(native.engine) as db:
        file = db.get(FileManagerFile, native.file_id)
        file.deleted_at = None
        file.extraction_status = "pending"
        db.flush()
        append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=native.file_id,
                retrieval_partition_id=native.roles.partition,
                change_kind="content",
                desired_state="active",
                operation="upsert",
            ),
            event_id=uuid4(),
        )
        db.commit()
    current = file_row(native)
    assert current[5] is None
    observed = observe(native, receipt.event_digest, execution_ref=current_session)
    assert observed.historical and observed.event_digest == receipt.event_digest
    assert file_row(native) == current and selected_event(native) == immutable
    with pytest.raises(FileSourceMutationRefused) as error:
        observe(native, receipt.event_digest)
    assert error.value.reason == "current_execution_denied"
    assert_core_and_privileges_unchanged(native)


def test_actual_text_router_cannot_pin_other_engine_and_spoof_current_execution(native, tmp_path):
    # Each Engine has its own pool and genuine Source29 LOGIN connection.
    alternate = reader_engine(native.world, native.roles.source)
    with native.world.connect() as conn:
        conn.execute(
            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
            (native.world.session_id,),
        )
    with native.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE auth_sessions AS SELECT id,user_id,expires_at,revoked_at,"
                "impersonator_user_id FROM public.auth_sessions"
            )
        )
        conn.execute(
            text(
                "UPDATE pg_temp.auth_sessions SET revoked_at=NULL,"
                "expires_at=clock_timestamp()+interval '1 hour'"
            )
        )
        assert conn.scalar(
            text("SELECT revoked_at IS NULL FROM pg_temp.auth_sessions WHERE id=:id"),
            {"id": native.world.session_id},
        )
        assert conn.scalar(
            text("SELECT revoked_at IS NOT NULL FROM public.auth_sessions WHERE id=:id"),
            {"id": native.world.session_id},
        )

    class TextRoutedSession(Session):
        def get_bind(self, mapper=None, clause=None, **kwargs):
            if isinstance(clause, TextClause):
                return alternate
            return super().get_bind(mapper=mapper, clause=clause, **kwargs)

    calls = {"orm_engine": 0, "text_engine": 0}

    def orm_sql(*args):
        calls["orm_engine"] += 1

    def text_sql(*args):
        calls["text_engine"] += 1

    event.listen(native.engine, "before_cursor_execute", orm_sql)
    event.listen(alternate, "before_cursor_execute", text_sql)
    try:
        with TextRoutedSession(native.engine) as db:
            refused = False
            observation = {"public_execution_revoked": True, "temporary_execution_active": True}
            try:
                receipt = mutations.stage_native_root_file_soft_delete(db, spec=native.spec)
            except FileSourceMutationRefused as error:
                refused = True
                observation["reason"] = error.reason
            else:
                observation["stage_returned_provisional_receipt"] = receipt.provisional
                observation["actual_file_delete_flushed"] = (
                    db.scalar(
                        select(FileManagerFile.deleted_at).where(
                            FileManagerFile.id == native.file_id
                        )
                    )
                    is not None
                )
            observation.update(refused=refused, **calls)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            (tmp_path / ("text-router-observation-" + stamp + ".json")).write_text(
                json.dumps(observation, indent=2, sort_keys=True) + "\n"
            )
            assert refused, "actual_revoked_execution_passed_via_orm_TEMP_and_second_text_engine"
            assert observation["reason"] == "source_engine_binding_required"
            assert calls == {"orm_engine": 0, "text_engine": 0}
            assert not db.in_transaction()
        assert file_row(native) == native.original and selected_event(native) is None
        with native.world.connect() as conn:
            assert conn.execute(
                "SELECT revoked_at IS NOT NULL FROM public.auth_sessions WHERE id=%s",
                (native.world.session_id,),
            ).fetchone()[0]
        assert_core_and_privileges_unchanged(native)
    finally:
        event.remove(native.engine, "before_cursor_execute", orm_sql)
        event.remove(alternate, "before_cursor_execute", text_sql)
        alternate.dispose()


def submit_stage(pool, native, *, spec=None):
    """Observe the real worker PID without touching its fresh Session first."""
    started = Event()
    pids = set()

    def worker():
        thread = get_ident()

        def cursor_started(connection, cursor, *args):
            if get_ident() == thread:
                pids.add(cursor.connection.info.backend_pid)
                started.set()

        event.listen(native.engine, "before_cursor_execute", cursor_started)
        try:
            with Session(native.engine) as db:
                result = mutations.stage_native_root_file_soft_delete(db, spec=spec or native.spec)
                db.commit()
                return result
        finally:
            event.remove(native.engine, "before_cursor_execute", cursor_started)

    future = pool.submit(worker)
    assert started.wait(3), "owned worker did not start actual Source SQL"
    assert len(pids) == 1
    return future, next(iter(pids))


@pytest.mark.parametrize("phase", ["standalone", "descriptor", "file", "event"])
@pytest.mark.parametrize("revocation", ["session", "app"])
def test_actual_lock_wait_rechecks_current_authority_and_rolls_back(
    native, phase, revocation, monkeypatch
):
    phases = []
    if phase == "event":
        original_append = mutations.append_projection_intent

        def append(db, **kwargs):
            assert (
                db.scalar(
                    select(FileManagerFile.deleted_at).where(FileManagerFile.id == native.file_id)
                )
                is not None
            )
            phases.append("file_flushed")
            result = original_append(db, **kwargs)
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM public.official_projection_outbox WHERE event_id=CAST(:id AS uuid)"
                    ),
                    {"id": str(native.event_id)},
                )
                == 1
            )
            phases.append("intent_flushed")
            return result

        monkeypatch.setattr(mutations, "append_projection_intent", append)
    role = None if phase == "descriptor" else native.roles.source
    blocker = native.world.connect(role)
    try:
        if phase == "descriptor":
            blocker.execute(
                "SELECT id FROM public.retrieval_partitions WHERE id=%s::uuid FOR UPDATE",
                (native.roles.partition,),
            )
        elif phase == "file":
            blocker.execute(
                "SELECT id FROM public.file_manager_files WHERE id=%s FOR UPDATE", (native.file_id,)
            )
        else:
            identity = (
                "files.source.standalone:" + native.roles.partition
                if phase == "standalone"
                else "official.projection.event:" + str(native.event_id)
            )
            blocker.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity,))
        # Connection setup must not consume the Source's bounded lock-wait budget.
        with (
            native.world.connect(autocommit=True) as observer,
            native.world.connect() as current,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future, waiter = submit_stage(pool, native)
            try:
                wait_for_exact_blocker(
                    native.world, waiter, blocker.info.backend_pid, observer=observer
                )
                assert not future.done()
                if phase == "event":
                    assert phases == ["file_flushed"]
                with current.transaction():
                    if revocation == "session":
                        current.execute(
                            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
                            (native.world.session_id,),
                        )
                    else:
                        current.execute(
                            "UPDATE public.company_app_controls SET enabled=false WHERE app_id='files'"
                        )
            finally:
                blocker.rollback()
            with pytest.raises(FileSourceMutationRefused) as error:
                future.result(timeout=8)
        assert error.value.reason == (
            "current_execution_denied" if revocation == "session" else "current_actor_or_app_denied"
        )
        if phase == "event":
            assert phases == ["file_flushed", "intent_flushed"]
        assert file_row(native) == native.original and selected_event(native) is None
        assert_core_and_privileges_unchanged(native)
    finally:
        blocker.close()


def test_actual_source_descriptor_share_blocks_legacy_exclusive_tree_before_file(native):
    """Privileged fixture models legacy descriptor->File locking, no business DML."""
    tree = native.world.connect()
    try:
        with Session(native.engine) as producer:
            receipt = mutations.stage_native_root_file_soft_delete(producer, spec=native.spec)
            producer_pid = producer.scalar(text("SELECT pg_backend_pid()"))

            def legacy_locks():
                tree.execute(
                    "SELECT id FROM public.retrieval_partitions WHERE id=%s::uuid FOR UPDATE",
                    (native.roles.partition,),
                )
                return tree.execute(
                    "SELECT deleted_at FROM public.file_manager_files WHERE id=%s FOR UPDATE",
                    (native.file_id,),
                ).fetchone()[0]

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(legacy_locks)
                try:
                    wait_for_exact_blocker(native.world, tree.info.backend_pid, producer_pid)
                    assert not future.done()
                    assert file_row(native) == native.original
                finally:
                    producer.commit()
                assert future.result(timeout=5) is not None
            tree.rollback()
        assert receipt.provisional
        assert_purged_deleted(native)
        assert_core_and_privileges_unchanged(native)
    finally:
        tree.close()


def test_actual_two_same_target_stages_cannot_duplicate_or_overtake(native):
    replacement = native.spec.model_copy(update={"event_id": uuid4()})
    with Session(native.engine) as first, ThreadPoolExecutor(max_workers=1) as pool:
        receipt = mutations.stage_native_root_file_soft_delete(first, spec=native.spec)
        first_pid = first.scalar(text("SELECT pg_backend_pid()"))
        future, waiter = submit_stage(pool, native, spec=replacement)
        try:
            wait_for_exact_blocker(native.world, waiter, first_pid)
            assert not future.done()
        finally:
            first.commit()
        with pytest.raises(FileSourceMutationRefused) as error:
            future.result(timeout=8)
        assert error.value.reason == "mutation_observation_required"
    with native.world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM public.official_projection_outbox WHERE resource_type='file_manager_file' AND resource_id=%s",
                (native.file_id,),
            ).fetchone()[0]
            == 2
        )
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM public.official_projection_outbox WHERE event_id=%s::uuid)",
            (str(replacement.event_id),),
        ).fetchone()[0]
    assert observe(native, receipt.event_digest).historical
    assert_purged_deleted(native)
    assert_core_and_privileges_unchanged(native)


def test_actual_same_engine_temp_session_cannot_shadow_public_revocation(native):
    with native.world.connect() as conn:
        conn.execute(
            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
            (native.world.session_id,),
        )
    with native.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE auth_sessions AS SELECT id,user_id,expires_at,revoked_at,"
                "impersonator_user_id FROM public.auth_sessions"
            )
        )
        conn.execute(text("UPDATE pg_temp.auth_sessions SET revoked_at=NULL"))
        assert conn.scalar(text("SELECT bool_and(revoked_at IS NULL) FROM pg_temp.auth_sessions"))
    with pytest.raises(FileSourceMutationRefused) as error:
        stage(native)
    assert error.value.reason == "current_execution_denied"
    assert file_row(native) == native.original and selected_event(native) is None
    assert_core_and_privileges_unchanged(native)


@pytest.mark.parametrize("change", ["session", "app", "binding", "digest"])
def test_actual_historical_observation_requires_current_scope_and_exact_witness(native, change):
    receipt = stage(native)
    immutable = selected_event(native)
    if change in {"session", "app"}:
        with native.world.connect() as current:
            if change == "session":
                current.execute(
                    "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
                    (native.world.session_id,),
                )
            else:
                current.execute(
                    "UPDATE public.company_app_controls SET enabled=false WHERE app_id='files'"
                )
    elif change == "binding":
        with Session(native.engine) as db:
            db.get(FileManagerFile, native.file_id).retrieval_partition_id = None
            db.commit()
    current = file_row(native)
    digest = "0" * 64 if change == "digest" else receipt.event_digest
    with pytest.raises((FileSourceMutationRefused, FileSourceMutationConflict)):
        observe(native, digest)
    assert file_row(native) == current and selected_event(native) == immutable
    assert_core_and_privileges_unchanged(native)
