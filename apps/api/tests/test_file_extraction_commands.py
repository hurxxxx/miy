"""Source command and live-frame runner boundaries on disposable restricted PG."""

from concurrent.futures import ThreadPoolExecutor
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
    seeded_request as seeded_request,
)
from test_file_projection_roles import reader_engine as reader_engine
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    role_template as role_template,
    wait_for_blocker as wait_for_blocker,
    world as world,
)
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files import extraction_runner as runner_module
from miy_api.domains.files.extraction_contracts import (
    FileExtractionCommitUnknown,
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


def test_concurrent_prepare_and_claim_converge_one_acquisition(c):
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: c.runner.prepare(c.spec), range(2)))
        claims = list(pool.map(lambda _: invoke(c, commands.claim_file_extraction), range(2)))
    assert {r.request_id for r in receipts} == {c.spec.request_id}
    assert sum(r.newly_acquired for r in claims) == 1 and c.reads == []


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


@pytest.mark.parametrize(
    "when,phase",
    [("after", "claim"), ("after", "input_bind"), ("before", "apply"), ("after", "apply")],
)
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


@pytest.mark.parametrize("change", ["session"])
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
