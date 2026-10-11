"""Genuine Source events and restricted, inactive Files-only Core acceptance."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from test_file_extraction_authority import (
    extraction_prepared as extraction_prepared,
    seeded_request as seeded_request,
)
from test_file_projection_core_roles import file_core_prepared as file_core_prepared
from test_file_projection_roles import reader_engine as reader_engine
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    denied as denied,
    role_template as role_template,
    wait_for_blocker as wait_for_blocker,
    world as world,
)
from miy_api.domains.files import extraction_commands as commands
from miy_api.domains.files.extraction_contracts import (
    FileExtractionComputedResult,
    FileExtractionInput,
    FileExtractionRequestSpec,
)
from miy_api.domains.files.extraction_runner import FileExtractionRunner
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_delivery import (
    SourceProjectionReceipt,
)
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_outbox import append_projection_intent
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.retrieval import files_projection_consumer as consumer
from miy_api.domains.retrieval import official_projection_ingress as ingress
from miy_api.domains.retrieval.files_projection_consumer import (
    FileProjectionConsumptionCommitUnknown,
    run_file_projection_consumer_once,
    run_file_projection_observation,
)
from miy_api.domains.retrieval.models import (
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.search.models import SearchIndexJob

RAW = b"Synthetic text"
SHA = sha256(RAW).hexdigest()


@pytest.fixture
def publications(monkeypatch):
    from miy_api.domains.rag import outbox as rag_outbox
    from miy_api.domains.search import outbox as search_outbox
    from miy_api.domains.files import core_projection, rag_projection, selected_storage

    calls = []

    def trap(*args, **kwargs):
        calls.append("effect")
        raise AssertionError("Core ingress cannot construct or call an effect")

    for module, names in (
        (rag_outbox, ("get_celery_client", "publish_rag_job_publication")),
        (search_outbox, ("get_celery_client", "_publish_job")),
        (rag_projection, ("load_file_rag_projection",)),
        (core_projection, ("load_ready_file_rag_projection",)),
        (selected_storage, ("read_selected_object",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, trap)
    return calls


@pytest.fixture
def c(world, file_core_prepared, monkeypatch, publications):
    from miy_api.domains.files import retrieval_contract

    with Session(world.engine) as db:
        seed_company_app_access(db, app_ids=("files", "pms"))
        db.commit()
    roles = file_core_prepared
    values = seeded_request(world, roles)
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
    source_engine, core_engine = (
        reader_engine(world, roles.source),
        reader_engine(world, roles.core),
    )
    reads = []

    def source_read(file):
        reads.append(file.id)
        return RAW

    monkeypatch.setattr(commands, "_read_source", source_read)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", True)
    monkeypatch.setattr(ingress, "get_settings", lambda: SimpleNamespace(rag_enabled=True))
    result = SimpleNamespace(
        world=world,
        roles=roles,
        source_engine=source_engine,
        core_engine=core_engine,
        source=lambda: Session(source_engine),
        core=lambda: Session(core_engine),
        spec=spec,
        token=uuid4(),
        reads=reads,
        publications=publications,
    )
    result.runner = FileExtractionRunner(result.source)
    yield result
    source_engine.dispose()
    core_engine.dispose()


def events(c):
    with c.source() as db:
        return [
            SourceProjectionReceipt.from_event(row)
            for row in db.scalars(
                select(OfficialProjectionOutbox)
                .where(OfficialProjectionOutbox.resource_id == c.spec.file_id)
                .order_by(OfficialProjectionOutbox.source_revision)
            )
        ]


def counts(c):
    with Session(c.world.engine) as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                OfficialProjectionReceipt,
                RetrievalProjectionEvent,
                SearchIndexJob,
                RagSyncJob,
            )
        )


def extract(c, outcome="ready"):
    if outcome == "ready":
        return c.runner.run(c.spec, claim_token=c.token)
    c.runner.prepare(c.spec)
    common = dict(
        request_id=c.spec.request_id,
        request_digest=c.spec.digest(),
        execution_ref=c.spec.execution_ref,
        claim_token=c.token,
    )
    c.runner._owned("claim", commands.claim_file_extraction, **common)
    bound = c.runner._owned("input_bind", commands.bind_file_extraction_input, **common)
    return c.runner._owned(
        "apply",
        commands.apply_file_extraction_result,
        **common,
        computed_result=FileExtractionComputedResult(outcome, bound.receipt.input_sha256),
    )


def consume(c, source):
    return run_file_projection_consumer_once(
        c.core, event_id=source.event_id, expected_digest=source.payload_digest
    )


def append(c, *, state="active", checksum=None, partition=None):
    with c.source() as db:
        row = append_projection_intent(
            db,
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=c.spec.file_id,
                retrieval_partition_id=partition or c.roles.partition,
                change_kind="delete" if state == "deleted" else "content",
                desired_state=state,
                operation="delete" if state == "deleted" else "upsert",
                content_checksum=checksum,
            ),
            event_id=uuid4(),
        )
        result = SourceProjectionReceipt.from_event(row)
        db.commit()
        return result


@pytest.mark.parametrize("outcome,open_gates", [("ready", True), ("unsupported", True)])
def test_genuine_f2_outcomes_stage_only_ready_or_deleted_jobs(c, monkeypatch, outcome, open_gates):
    from miy_api.domains.files import retrieval_contract

    extract(c, outcome)
    monkeypatch.setattr(retrieval_contract, "FILES_RETRIEVAL_ACTIVE", open_gates)
    all_events = events(c)
    results = [run_file_projection_consumer_once(c.core) for _ in all_events]
    terminal = results[-1]
    work = int(open_gates and outcome in {"ready", "unsupported"})
    assert counts(c) == (len(all_events), 1, work, work)
    assert terminal.source == all_events[-1] and not terminal.provisional
    if len(all_events) == 2:
        assert results[0].status == "superseded" and results[0].core_event_sequence is None
    with c.core() as db:
        head = db.get(RetrievalProjectionHead, ("file_manager_file", c.spec.file_id))
        assert head.desired_state == ("deleted" if outcome == "unsupported" else "active")
        assert head.content_checksum == (SHA if outcome == "ready" else None)
        if work:
            search = db.scalar(select(SearchIndexJob))
            rag = db.scalar(select(RagSyncJob))
            assert (
                search.projection_event_sequence
                == rag.projection_event_sequence
                == terminal.core_event_sequence
            )
            assert (
                search.operation
                == rag.operation
                == ("delete" if outcome == "unsupported" else "upsert")
            )
    assert run_file_projection_consumer_once(c.core) is None
    assert c.reads == [c.spec.file_id] and c.publications == []


def test_two_consumers_converge_one_actual_event_and_job_pair(c):
    extract(c)
    first, source = events(c)
    consume(c, first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(c, source), range(2)))
    assert results[0] == results[1]
    assert counts(c) == (2, 1, 1, 1) and c.publications == []


def test_post_flush_failure_rolls_back_event_jobs_and_receipt(c, monkeypatch):
    extract(c)
    first, latest = events(c)
    consume(c, first)
    original = ingress._stage_file_jobs

    def after_actual_flush(db, *args, **kwargs):
        original(db, *args, **kwargs)
        assert db.scalar(select(func.count()).select_from(SearchIndexJob)) == 1
        raise ProjectionOutboxError("synthetic_after_job_flush")

    monkeypatch.setattr(ingress, "_stage_file_jobs", after_actual_flush)
    with pytest.raises(ProjectionOutboxError, match="synthetic_after_job_flush"):
        consume(c, latest)
    assert counts(c) == (1, 0, 0, 0) and c.publications == []


@pytest.mark.parametrize("after_commit", [False, True])
def test_actual_commit_ack_unknown_preserves_identity_and_observation_only(
    c, after_commit, monkeypatch
):
    extract(c)
    first, source = events(c)
    consume(c, first)

    class FaultSession(Session):
        def commit(self):
            if after_commit:
                super().commit()
            raise StatementError("private commit detail", "private SQL", {"secret": "hidden"}, None)

        def close(self):
            super().close()
            raise RuntimeError("private cleanup detail")

    with pytest.raises(FileProjectionConsumptionCommitUnknown) as caught:
        run_file_projection_consumer_once(
            lambda: FaultSession(c.core_engine),
            event_id=source.event_id,
            expected_digest=source.payload_digest,
        )
    retained = caught.value.consumption
    assert retained.source == source and retained.provisional
    assert "private" not in str(caught.value)
    before = counts(c)

    def no_accept(*args, **kwargs):
        raise AssertionError("observation cannot repeat acceptance")

    monkeypatch.setattr(consumer, "accept_prepared_file_projection_intent", no_accept)
    observed = run_file_projection_observation(
        c.core,
        event_id=source.event_id,
        expected_digest=source.payload_digest,
        expected_consumption=retained,
    )
    assert (observed is not None) == after_commit
    if observed is not None:
        assert observed == replace(retained, provisional=False)
    assert counts(c) == before and c.reads == [c.spec.file_id] and c.publications == []
