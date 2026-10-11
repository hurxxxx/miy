"""Fixed leaf Source mutations on the unchanged restricted Source29 profile."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import pytest
from company_admission_fixture import seed_company_app_access
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_projection_core_roles import snapshot as snapshot
from test_file_projection_roles import reader_engine as reader_engine
from test_file_source_partition_roles import file_source_prepared as file_source_prepared
from test_file_source_partition_roles import wait_for_exact_blocker as wait_for_exact_blocker
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied as denied,
)
from test_official_writer_roles import (
    role_template as role_template,
)
from test_official_writer_roles import (
    world as world,
)

from miy_api.domains.auth.models import UserSystemRole
from miy_api.domains.files import source_mutations as mutations
from miy_api.domains.files.models import (
    FileManagerFile,
)
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceDeleteSpec,
    FileSourceMutationRefused,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_outbox import append_projection_intent


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


@pytest.mark.parametrize("phase,revocation", [("file", "session"), ("descriptor", "app")])
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
