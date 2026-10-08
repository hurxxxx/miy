"""Source command and live-frame runner boundaries on disposable restricted PG."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from test_file_extraction_authority import (
    extraction_prepared as extraction_prepared,
    seeded_request,
)
from test_file_projection_roles import reader_engine
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    wait_for_blocker,
    world as world,
)
from miy_api.domains.auth.models import AuthSession
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files import extraction_runner as runner_module
from miy_api.domains.files.extraction_contracts import (
    FileExtractionCommitUnknown,
    FileExtractionComputedResult,
    FileExtractionConflict,
    FileExtractionInput,
    FileExtractionRefused,
    FileExtractionRequestSpec,
)
from miy_api.domains.files.extraction_runner import (
    FileExtractionRunner,
    compute_local_file_extraction,
)
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.official_apps.file_extraction_models import FileExtractionRequest
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import lock_projection_source

RAW = b"Synthetic text"


@pytest.fixture
def c(world, extraction_prepared, monkeypatch):
    with Session(world.engine) as db:
        seed_company_app_access(db, app_ids=("files", "pms"))
        db.commit()
    values = seeded_request(world, extraction_prepared)
    payload = json.loads(values["request_payload"])
    spec = FileExtractionRequestSpec(
        request_id=values["request_id"],
        result_id=values["result_id"],
        event_id=values["event_id"],
        file_id=values["file_id"],
        actor_user_id=world.user_id,
        execution_ref=world.session_id,
        expected_input=FileExtractionInput.model_validate_json(payload["input_canonical"]),
    )
    engine = reader_engine(world, extraction_prepared.source)
    calls = []

    def read(file):
        calls.append(file.id)
        return RAW

    monkeypatch.setattr(commands, "_read_source", read)

    def factory():
        return Session(engine, info={"extraction_test_owned": True})

    result = SimpleNamespace(
        world=world,
        roles=extraction_prepared,
        engine=engine,
        spec=spec,
        token=uuid4(),
        reads=calls,
        runner=FileExtractionRunner(factory),
    )
    yield result
    engine.dispose()


def invoke(c, function, **kwargs):
    return c.runner._owned(
        "test",
        function,
        request_id=c.spec.request_id,
        request_digest=c.spec.digest(),
        execution_ref=c.spec.execution_ref,
        claim_token=c.token,
        **kwargs,
    )


def bound(c):
    assert c.runner.prepare(c.spec).state == "prepared"
    assert invoke(c, commands.claim_file_extraction).newly_acquired
    return invoke(c, commands.bind_file_extraction_input)


def current(c):
    with Session(c.engine) as db:
        row = db.get(FileExtractionRequest, str(c.spec.request_id))
        file = db.get(FileManagerFile, c.spec.file_id)
        events = list(
            db.scalars(
                select(OfficialProjectionOutbox)
                .where(OfficialProjectionOutbox.resource_id == c.spec.file_id)
                .order_by(OfficialProjectionOutbox.source_revision)
            )
        )
        return SimpleNamespace(
            state=row.state if row else None,
            digest=row.result_digest if row else None,
            file_status=file.extraction_status,
            checksum=file.extraction_content_checksum,
            text=file.extraction_text,
            events=[(r.event_id, r.source_revision, r.payload_digest) for r in events],
            updated_at=file.updated_at,
        )


def test_actual_ready_atomic_source_result_and_no_core_writes(c):
    receipt = c.runner.run(c.spec, claim_token=c.token)
    assert (receipt.state, receipt.provisional, receipt.historical) == ("ready", False, True)
    assert receipt.result_digest and receipt.input_sha256 == sha256(RAW).hexdigest()
    assert c.reads == [c.spec.file_id]
    state = current(c)
    assert (state.state, state.file_status, state.text) == (
        "ready",
        "ready",
        "[Document] Synthetic text",
    )
    assert len(state.events) == 2 and state.events[-1][0] == str(c.spec.event_id)
    with c.world.connect() as db:
        for table in (
            "retrieval_projection_events",
            "retrieval_projection_heads",
            "rag_sync_jobs",
            "search_index_jobs",
        ):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("outcome", ["unsupported", "failed", "ocr_required"])
def test_terminal_or_ocr_outcomes_are_source_only(c, outcome):
    item = bound(c)
    receipt = invoke(
        c,
        commands.apply_file_extraction_result,
        computed_result=FileExtractionComputedResult(outcome, item.receipt.input_sha256),
    )
    state = current(c)
    assert state.checksum is None
    if outcome == "ocr_required":
        assert (receipt.state, receipt.hold_reason, state.file_status, len(state.events)) == (
            "input_bound",
            "ocr_required",
            "pending",
            1,
        )
    else:
        assert (receipt.state, state.file_status) == (outcome, outcome)
        assert len(state.events) == (2 if outcome == "unsupported" else 1)
        assert receipt.result_digest


def test_same_token_runner_replay_never_reads_or_computes(c, monkeypatch):
    c.runner.prepare(c.spec)
    invoke(c, commands.claim_file_extraction)
    monkeypatch.setattr(
        runner_module, "compute_local_file_extraction", lambda _: pytest.fail("replay compute")
    )
    receipt = FileExtractionRunner(lambda: Session(c.engine)).run(c.spec, claim_token=c.token)
    assert receipt.state == "claimed" and not receipt.newly_acquired and c.reads == []


def test_concurrent_prepare_and_claim_converge_one_acquisition(c):
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: c.runner.prepare(c.spec), range(2)))
        claims = list(pool.map(lambda _: invoke(c, commands.claim_file_extraction), range(2)))
    assert {r.request_id for r in receipts} == {c.spec.request_id}
    assert sum(r.newly_acquired for r in claims) == 1 and c.reads == []


def test_new_ids_same_input_are_conflict(c):
    c.runner.prepare(c.spec)
    other = c.spec.model_copy(update=dict(request_id=uuid4(), result_id=uuid4(), event_id=uuid4()))
    with pytest.raises(FileExtractionConflict, match="file_extraction_conflict") as error:
        c.runner.prepare(other)
    assert error.value.reason == "input_already_requested"


@pytest.mark.parametrize("mutation", ["token", "input", "outcome", "artifact"])
def test_terminal_apply_always_requires_history_observation(c, mutation):
    item = bound(c)
    computed = compute_local_file_extraction(item)
    receipt = invoke(c, commands.apply_file_extraction_result, computed_result=computed)
    before = current(c)
    token = c.token
    if mutation == "token":
        token = uuid4()
    if mutation == "input":
        computed = replace(computed, input_sha256="f" * 64)
    if mutation == "outcome":
        computed = FileExtractionComputedResult("failed", computed.input_sha256)
    if mutation == "artifact":
        computed = replace(
            computed, artifact=replace(computed.artifact, text="changed synthetic result")
        )
    with pytest.raises(FileExtractionRefused) as error:
        c.runner._owned(
            "apply",
            commands.apply_file_extraction_result,
            request_id=c.spec.request_id,
            request_digest=c.spec.digest(),
            execution_ref=c.spec.execution_ref,
            claim_token=token,
            computed_result=computed,
            expected_result_digest=receipt.result_digest,
        )
    assert error.value.reason == "terminal_observation_required"
    assert current(c).__dict__ == before.__dict__


def test_terminal_history_uses_new_current_session_without_rewriting(c):
    receipt = c.runner.run(c.spec, claim_token=c.token)
    new_session = str(uuid4())
    with Session(c.world.engine) as db:
        old = db.get(AuthSession, c.spec.execution_ref)
        old.revoked_at = commands._clock()
        db.add(
            AuthSession(
                id=new_session,
                user_id=c.spec.actor_user_id,
                token_hash=uuid4().hex + uuid4().hex,
                expires_at=commands._clock() + timedelta(hours=1),
            )
        )
        db.commit()
    before = current(c)
    observed = c.runner.observe(
        spec=c.spec,
        execution_ref=new_session,
        expected_result_digest=receipt.result_digest,
        expected_claim_token=c.token,
        expected_input_sha256=receipt.input_sha256,
    )
    assert observed.historical and observed.result_digest == receipt.result_digest
    assert current(c).__dict__ == before.__dict__
    with pytest.raises(FileExtractionRefused):
        c.runner.observe(spec=c.spec, expected_result_digest=receipt.result_digest)
    with pytest.raises(FileExtractionConflict):
        c.runner.observe(spec=c.spec, execution_ref=new_session, expected_result_digest="f" * 64)


def test_apply_actual_flushed_file_and_intent_rollback_no_residue(c, monkeypatch):
    item = bound(c)
    original = commands.append_projection_intent

    def fail_after_flush(db, **kwargs):
        original(db, **kwargs)
        assert (
            db.scalar(
                select(FileManagerFile.extraction_status).where(
                    FileManagerFile.id == c.spec.file_id
                )
            )
            == "ready"
        )
        assert db.scalar(
            select(OfficialProjectionOutbox.event_id).where(
                OfficialProjectionOutbox.event_id == str(c.spec.event_id)
            )
        )
        raise FileExtractionRefused("injected_after_source_flush")

    monkeypatch.setattr(commands, "append_projection_intent", fail_after_flush)
    with Session(c.engine) as db, pytest.raises(FileExtractionRefused):
        commands.apply_file_extraction_result(
            db,
            request_id=c.spec.request_id,
            request_digest=c.spec.digest(),
            execution_ref=c.spec.execution_ref,
            claim_token=c.token,
            computed_result=compute_local_file_extraction(item),
        )
    state = current(c)
    assert (state.state, state.file_status, state.checksum, len(state.events)) == (
        "input_bound",
        "pending",
        None,
        1,
    )


def test_apply_terminal_guard_after_file_outbox_flush_rolls_back(c):
    item = bound(c)
    with pytest.raises(FileExtractionConflict):
        invoke(
            c,
            commands.apply_file_extraction_result,
            computed_result=compute_local_file_extraction(item),
            expected_result_digest="f" * 64,
        )
    state = current(c)
    assert (state.state, state.file_status, len(state.events)) == ("input_bound", "pending", 1)


@pytest.mark.parametrize("nested", [False, True])
def test_existing_or_nested_caller_transaction_is_preserved(c, nested):
    with Session(c.engine) as db:
        db.execute(text("SELECT 1"))
        if nested:
            db.begin_nested()
        with pytest.raises(FileExtractionRefused) as error:
            commands.prepare_file_extraction(db, spec=c.spec)
        assert error.value.reason == "fresh_clean_outer_transaction_required"
        assert db.in_transaction() and bool(db.in_nested_transaction()) == nested
        assert db.scalar(select(FileExtractionRequest.request_id)) is None


@pytest.mark.parametrize("change", ["session", "app", "actor"])
def test_advisory_wait_rechecks_current_authority_before_prepare(c, change):
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        lock_projection_source(blocker, "file_manager_file", c.spec.file_id)
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(c.runner.prepare, c.spec)
        try:
            wait_for_blocker(c.world, pid)
            with c.world.connect() as core:
                if change == "session":
                    core.execute(
                        "UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                        [c.spec.execution_ref],
                    )
                if change == "app":
                    core.execute(
                        "UPDATE company_app_controls SET enabled=false WHERE app_id='files'"
                    )
                if change == "actor":
                    core.execute(
                        "UPDATE users SET login_blocked=true WHERE id=%s", [c.spec.actor_user_id]
                    )
        finally:
            blocker.rollback()
        with pytest.raises(FileExtractionRefused):
            future.result(timeout=8)
    assert current(c).state is None and c.reads == []


def test_storage_read_holds_source_and_file_fences_and_rechecks_clock(c, monkeypatch):
    c.runner.prepare(c.spec)
    invoke(c, commands.claim_file_extraction)

    def revoke_during_read(file):
        with c.world.connect() as core:
            core.execute(
                "UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                [c.spec.execution_ref],
            )
        return RAW

    monkeypatch.setattr(commands, "_read_source", revoke_during_read)
    with pytest.raises(FileExtractionRefused) as error:
        invoke(c, commands.bind_file_extraction_input)
    assert error.value.reason == "current_execution_denied" and current(c).state == "claimed"


def test_running_loop_refuses_before_session_storage_or_write(c):
    calls = []
    runner = FileExtractionRunner(lambda: calls.append("session"))

    async def attempt():
        with pytest.raises(FileExtractionRefused) as error:
            runner.run(c.spec, claim_token=c.token)
        assert error.value.reason == "synchronous_runner_required"

    asyncio.run(attempt())
    assert calls == [] and c.reads == [] and current(c).state is None


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("phase", ["claim", "input_bind", "apply"])
def test_actual_commit_unknown_preserves_same_ids_and_once_compute(c, monkeypatch, phase, when):
    original_commit = Session.commit
    original_close = Session.close
    hit = []
    closes = []

    def commit(db):
        state = (
            db.scalar(
                select(FileExtractionRequest.state).where(
                    FileExtractionRequest.request_id == str(c.spec.request_id)
                )
            )
            if db.info.get("extraction_test_owned")
            else None
        )
        target = {"claim": "claimed", "input_bind": "input_bound", "apply": "ready"}[phase]
        if state == target and not hit:
            hit.append(target)
            if when == "after":
                original_commit(db)
            raise StatementError(
                "synthetic sensitive COMMIT",
                "sensitive SQL",
                {"text": "synthetic source body"},
                RuntimeError(),
            )
        original_commit(db)

    def close(db):
        original_close(db)
        if db.info.get("extraction_test_owned"):
            closes.append(True)
            raise StatementError("synthetic sensitive close", None, None, RuntimeError())

    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(Session, "close", close)
    parses = []
    original_compute = runner_module.compute_local_file_extraction

    def compute(value):
        parses.append(True)
        return original_compute(value)

    monkeypatch.setattr(runner_module, "compute_local_file_extraction", compute)
    if when == "before" or phase == "apply":
        with pytest.raises(FileExtractionCommitUnknown) as error:
            c.runner.run(c.spec, claim_token=c.token)
        unknown = error.value
        assert (
            unknown.receipt.request_id,
            unknown.receipt.result_id,
            unknown.receipt.event_id,
        ) == (c.spec.request_id, c.spec.result_id, c.spec.event_id)
        assert unknown.phase == phase and unknown.__cause__ is None
        if when == "after":
            observed = c.runner.observe_unknown(unknown, spec=c.spec)
            assert (
                observed.result_digest == unknown.receipt.result_digest
                and observed.state == "ready"
            )
        assert len(parses) == (1 if phase == "apply" else 0)
    else:
        assert c.runner.run(c.spec, claim_token=c.token).state == "ready" and len(parses) == 1
    assert len(c.reads) == (0 if phase == "claim" and when == "before" else 1)
    assert closes


def test_runtime_db_error_and_cleanup_do_not_expose_parameters(c, monkeypatch):
    with Session(c.engine) as db:
        original_execute = db.execute

        def execute(statement, *args, **kwargs):
            if "miy_file_extraction_admit" in str(statement):
                raise StatementError(
                    "sensitive runtime", "SQL raw", {"storage_key": "sensitive-key"}, RuntimeError()
                )
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(db, "execute", execute)
        monkeypatch.setattr(
            db, "rollback", lambda: (_ for _ in ()).throw(RuntimeError("cleanup sensitive"))
        )
        with pytest.raises(FileExtractionRefused) as error:
            commands.prepare_file_extraction(db, spec=c.spec)
        assert error.value.reason == "source_database_refused" and error.value.__cause__ is None
        assert "sensitive" not in str(error.value)


def test_successful_ack_survives_close_error_without_reissuing_permit(c, monkeypatch):
    original_close = Session.close

    def close(db):
        original_close(db)
        if db.info.get("extraction_test_owned"):
            raise StatementError("synthetic sensitive close", None, None, RuntimeError())

    monkeypatch.setattr(Session, "close", close)
    receipt = c.runner.run(c.spec, claim_token=c.token)
    assert receipt.state == "ready" and not receipt.provisional and receipt.result_digest
    assert c.reads == [c.spec.file_id]
    replay = c.runner.run(c.spec, claim_token=c.token)
    assert replay.state == "ready" and not replay.newly_acquired and c.reads == [c.spec.file_id]


def test_original_refusal_survives_rollback_and_close_errors(c, monkeypatch):
    original_close = Session.close

    def close(db):
        original_close(db)
        if db.info.get("extraction_test_owned"):
            raise StatementError("synthetic sensitive close", None, None, RuntimeError())

    with c.world.connect() as core:
        core.execute(
            "UPDATE auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
            [c.spec.execution_ref],
        )
    monkeypatch.setattr(Session, "close", close)
    monkeypatch.setattr(
        Session, "rollback", lambda db: (_ for _ in ()).throw(RuntimeError("cleanup"))
    )
    with pytest.raises(FileExtractionRefused) as error:
        c.runner.run(c.spec, claim_token=c.token)
    assert error.value.reason == "current_execution_denied" and c.reads == []
    assert current(c).state is None


@pytest.mark.parametrize("mode", ["rollback_only", "create_savepoint"])
@pytest.mark.parametrize("existing", [False, True])
def test_connection_backed_stage_and_runner_preserve_external_owner(c, mode, existing):
    with c.engine.connect() as connection:
        if existing:
            connection.begin()
            connection.execute(
                text(
                    "UPDATE file_manager_files SET extraction_metadata=jsonb_build_object('synthetic_marker',true) WHERE id=:id"
                ),
                {"id": c.spec.file_id},
            )
        assert connection.in_transaction() == existing
        with Session(bind=connection, join_transaction_mode=mode) as db:
            assert not db.in_transaction()
            with pytest.raises(FileExtractionRefused) as error:
                commands.prepare_file_extraction(db, spec=c.spec)
            assert error.value.reason == "source_engine_binding_required"
            assert not db.in_transaction() and connection.in_transaction() == existing
        runner = FileExtractionRunner(lambda: Session(bind=connection, join_transaction_mode=mode))
        with pytest.raises(FileExtractionRefused) as error:
            runner.run(c.spec, claim_token=c.token)
        assert (
            error.value.reason == "source_engine_binding_required"
            and connection.in_transaction() == existing
        )
        assert not connection.closed
        assert connection.scalar(select(FileExtractionRequest.request_id)) is None
        if existing:
            assert connection.scalar(
                select(FileManagerFile.extraction_metadata).where(
                    FileManagerFile.id == c.spec.file_id
                )
            )["synthetic_marker"]
        connection.rollback()
    assert c.reads == [] and current(c).state is None


def test_deferred_commit_rejection_is_unknown_and_never_recomputes(c, monkeypatch):
    original_commit = Session.commit
    hit = []

    def commit(db):
        if db.info.get("extraction_test_owned") and not hit:
            state = db.scalar(
                select(FileExtractionRequest.state).where(
                    FileExtractionRequest.request_id == str(c.spec.request_id)
                )
            )
            if state == "ready":
                hit.append(True)
                db.execute(
                    text(
                        "UPDATE file_manager_files SET extraction_text='Synthetic post-result mutation' WHERE id=:id"
                    ),
                    {"id": c.spec.file_id},
                )
        original_commit(db)

    monkeypatch.setattr(Session, "commit", commit)
    parses = []
    original_compute = runner_module.compute_local_file_extraction

    def compute(value):
        parses.append(True)
        return original_compute(value)

    monkeypatch.setattr(runner_module, "compute_local_file_extraction", compute)
    with pytest.raises(FileExtractionCommitUnknown) as error:
        c.runner.run(c.spec, claim_token=c.token)
    assert error.value.phase == "apply" and error.value.receipt.result_digest
    assert (
        error.value.receipt.request_id,
        error.value.receipt.result_id,
        error.value.receipt.event_id,
    ) == (c.spec.request_id, c.spec.result_id, c.spec.event_id)
    with pytest.raises(FileExtractionConflict):
        c.runner.observe_unknown(error.value, spec=c.spec)
    state = current(c)
    assert (state.state, state.file_status, len(state.events)) == ("input_bound", "pending", 1)
    assert len(parses) == 1 and c.reads == [c.spec.file_id]


def test_historical_digest_is_not_recomputed_after_source_timestamp_change(c):
    receipt = c.runner.run(c.spec, claim_token=c.token)
    with Session(c.engine) as db:
        file = db.get(FileManagerFile, c.spec.file_id)
        file.filename = "Synthetic renamed.txt"
        db.commit()
    before = current(c)
    observed = c.runner.observe(
        spec=c.spec,
        expected_result_digest=receipt.result_digest,
        expected_claim_token=c.token,
        expected_input_sha256=receipt.input_sha256,
    )
    assert observed.historical and observed.result_digest == receipt.result_digest
    assert current(c).__dict__ == before.__dict__ and c.reads == [c.spec.file_id]


def test_factory_sql_error_is_stable_before_source_session(c):
    def factory():
        raise StatementError(
            "synthetic sensitive factory", "SQL", {"key": "synthetic-private"}, RuntimeError()
        )

    with pytest.raises(FileExtractionRefused) as error:
        FileExtractionRunner(factory).run(c.spec, claim_token=c.token)
    assert error.value.reason == "source_session_factory_failed" and error.value.__cause__ is None
    assert c.reads == [] and current(c).state is None


@pytest.mark.parametrize("change", ["session", "app"])
def test_event_identity_wait_rechecks_authority_and_rolls_back_actual_flushes(
    c, monkeypatch, change
):
    item = bound(c)
    computed = compute_local_file_extraction(item)
    original = commands.append_projection_intent
    phases = []

    def append(db, **kwargs):
        assert (
            db.scalar(
                select(FileManagerFile.extraction_status).where(
                    FileManagerFile.id == c.spec.file_id
                )
            )
            == "ready"
        )
        phases.append("file_flushed")
        result = original(db, **kwargs)
        assert db.scalar(
            select(OfficialProjectionOutbox.event_id).where(
                OfficialProjectionOutbox.event_id == str(c.spec.event_id)
            )
        ) == str(c.spec.event_id)
        phases.append("intent_flushed")
        return result

    monkeypatch.setattr(commands, "append_projection_intent", append)
    with Session(c.engine) as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity,0))"),
            {"identity": "official.projection.event:" + str(c.spec.event_id)},
        )
        pid = blocker.scalar(text("SELECT pg_backend_pid()"))
        future = pool.submit(
            invoke, c, commands.apply_file_extraction_result, computed_result=computed
        )
        try:
            wait_for_blocker(c.world, pid)
            assert phases == ["file_flushed"]
            with c.world.connect() as core:
                if change == "session":
                    core.execute(
                        "UPDATE auth_sessions SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",
                        [c.spec.execution_ref],
                    )
                else:
                    core.execute(
                        "UPDATE company_app_controls SET enabled=false WHERE app_id='files'"
                    )
        finally:
            blocker.rollback()
        with pytest.raises(FileExtractionRefused) as error:
            future.result(timeout=8)
    assert error.value.reason == (
        "current_execution_denied" if change == "session" else "current_actor_or_app_denied"
    )
    assert phases == ["file_flushed", "intent_flushed"]
    state = current(c)
    assert (state.state, state.file_status, state.checksum, state.digest, len(state.events)) == (
        "input_bound",
        "pending",
        None,
        None,
        1,
    )
    assert c.reads == [c.spec.file_id]
