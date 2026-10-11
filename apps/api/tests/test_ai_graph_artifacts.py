from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest
from company_admission_fixture import company_authority_tables, seed_company_app_access
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from miy_api.core.db import Base
from miy_api.domains.ai_artifacts.contracts import (
    AiArtifactCreate,
    AiArtifactIndexGenerationCreate,
    AiArtifactQueryCreate,
    AiArtifactSourceCreate,
    AiIndexGenerationCreate,
)
from miy_api.domains.ai_artifacts.models import (
    AiArtifact,
    AiArtifactIndexGeneration,
    AiArtifactQuery,
    AiArtifactSource,
    AiIndexGeneration,
)
from miy_api.domains.ai_artifacts.repository import (
    AiArtifactImmutableError,
    AiArtifactNotFoundError,
    AiArtifactRepository,
    AiIndexGenerationRepository,
)
from miy_api.domains.ai_artifacts.router import _query_source_response
from miy_api.domains.ai_graph.contracts import (
    AiGraphNodeResult,
    AiGraphNodeSpec,
    AiGraphRunRequest,
    AiGraphSpec,
)
from miy_api.domains.ai_graph.dispatch import stage_graph_dispatch
from miy_api.domains.ai_graph.execution_registry import (
    execute_registered_ai_graph,
    register_ai_graph_executor,
    reset_ai_graph_executors,
)
from miy_api.domains.ai_graph.models import (
    AiGraphDispatchOutbox,
    AiGraphRun,
    AiGraphRunInput,
    AiGraphRunNodeProgress,
)
from miy_api.domains.ai_graph.repository import (
    AiGraphDispatchRepository,
    AiGraphExecutionLeaseLostError,
    AiGraphRunRepository,
)
from miy_api.domains.ai_graph.router import _artifact_ids_by_run
from miy_api.domains.ai_graph.runtime import (
    AiGraphRuntimeContext,
    compile_graph,
    run_graph,
)
from miy_api.domains.auth.models import AuditLog, User
from miy_api.domains.conversations.models import Conversation, ConversationTurn


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=company_authority_tables())
    for table in (
        Conversation.__table__,
        ConversationTurn.__table__,
        AiGraphRun.__table__,
        AiGraphRunInput.__table__,
        AiGraphRunNodeProgress.__table__,
        AiGraphDispatchOutbox.__table__,
        AiIndexGeneration.__table__,
        AiArtifact.__table__,
        AiArtifactSource.__table__,
        AiArtifactQuery.__table__,
        AiArtifactIndexGeneration.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_company_app_access(db)
        for user_id in ("user-1", "user-2"):
            db.add(
                User(
                    id=user_id,
                    login_id=user_id,
                    email=f"{user_id}@example.test",
                    full_name=user_id,
                    password_hash="fixture",
                )
            )
        db.commit()
    return factory


@pytest.fixture(autouse=True)
def allow_runtime_graph_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "miy_api.domains.ai_graph.runtime.enforce_graph_run_app_policy",
        lambda *_args, **_kwargs: True,
    )


async def _allow_policy() -> None:
    return None


def _linear_spec() -> AiGraphSpec:
    return AiGraphSpec(
        graph_id="test.report",
        graph_version="1",
        nodes=(
            AiGraphNodeSpec(node_id="collect", purpose="Collect evidence"),
            AiGraphNodeSpec(
                node_id="write",
                purpose="Write report",
                depends_on=("collect",),
            ),
        ),
    )


def _run_request(*, inputs: dict | None = None) -> AiGraphRunRequest:
    return AiGraphRunRequest(
        requested_by_user_id="user-1",
        app_id="docs",
        graph=_linear_spec(),
        inputs=inputs or {"question": "접속 오류를 보고해줘"},
        conversation_id="conversation-1",
    )


def _artifact_create(
    *,
    artifact_type: str = "report",
    content_text: str | None = "# 보고서",
    payload: dict | None = None,
) -> AiArtifactCreate:
    return AiArtifactCreate(
        owner_user_id="user-1",
        app_id="docs",
        artifact_type=artifact_type,
        title="접속 오류 분석",
        content_text=content_text,
        payload=payload,
        conversation_id="conversation-1",
    )


def test_dispatch_outbox_can_be_claimed_retried_and_acked(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        mismatched = _artifact_create().model_copy(
            update={
                "owner_user_id": "user-2",
                "app_id": "another-app",
                "conversation_id": "conversation-2",
                "visibility": "company",
                "company_admin_read_acknowledged": True,
                "graph_run_id": "already-bound",
            }
        )
        with pytest.raises(
            ValueError, match="app_id, owner_user_id, conversation_id, visibility, graph_run_id"
        ):
            stage_graph_dispatch(db, run_request=_run_request(), pending_artifact=mismatched)
        assert db.query(AiGraphRun).count() == 0
        assert db.query(AiArtifact).count() == 0
        assert db.query(AiGraphDispatchOutbox).count() == 0
        prepared = stage_graph_dispatch(
            db,
            run_request=_run_request(),
            pending_artifact=_artifact_create(
                content_text=None, payload={"request": "접속 오류를 보고해줘"}
            ),
        )
        db.commit()
        assert prepared.outbox.payload_ref == f"ai-graph-input:{prepared.graph_run.id}"
        assert prepared.pending_artifact.status == "pending"
        repository = AiGraphDispatchRepository(db)
        claimed = repository.claim_due(claim_token="publisher-1")
        assert [item.id for item in claimed] == [prepared.outbox.id]
        repository.mark_retry(
            prepared.outbox.id,
            claim_token="publisher-1",
            error_code="broker.unavailable",
            retry_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
        )
        claimed_again = repository.claim_due(claim_token="publisher-2")
        repository.mark_dispatched(
            claimed_again[0].id, claim_token="publisher-2", celery_task_id="celery-1"
        )
        db.commit()
        assert prepared.outbox.status == "dispatched"
        assert prepared.outbox.attempts == 2
        completed = AiArtifactRepository(db).create_completed(
            _artifact_create().model_copy(update={"graph_run_id": prepared.graph_run.id})
        )
        db.commit()
        assert _artifact_ids_by_run(
            db, [prepared.graph_run.id], user_id="user-1", enabled_app_ids=frozenset({"docs"})
        ) == {prepared.graph_run.id: completed.id}


def test_graph_execution_claim_skips_duplicates_and_reclaims_stale_lease(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_factory() as db:
        repository = AiGraphRunRepository(db)
        run = repository.create(_run_request())
        first = repository.claim_execution(
            run.id, claim_token="worker-1", now=now, lease_duration=timedelta(minutes=5)
        )
        repository.renew_execution_lease(
            run.id,
            claim_token="worker-1",
            now=now + timedelta(seconds=30),
            lease_duration=timedelta(minutes=3),
        )
        assert run.execution_lease_expires_at == now + timedelta(minutes=3, seconds=30)
        with pytest.raises(AiGraphExecutionLeaseLostError):
            repository.renew_execution_lease(run.id, claim_token="worker-2")
        duplicate = repository.claim_execution(
            run.id, claim_token="worker-2", now=now + timedelta(minutes=1)
        )
        assert first.acquired is True
        assert first.resume_from_checkpoint is False
        assert duplicate.acquired is False
        assert duplicate.reason == "active_lease"
        reclaimed = repository.claim_execution(
            run.id, claim_token="worker-3", now=now + timedelta(minutes=6)
        )
        assert reclaimed.acquired is True
        assert reclaimed.reason == "stale_lease"
        assert reclaimed.resume_from_checkpoint is True
        assert run.execution_claim_token == "worker-3"
        assert run.execution_attempts == 2
        with pytest.raises(AiGraphExecutionLeaseLostError):
            repository.transition(run.id, "completed", claim_token="worker-1")
        with pytest.raises(AiGraphExecutionLeaseLostError):
            repository.transition(run.id, "failed")
        with pytest.raises(AiGraphExecutionLeaseLostError):
            repository.advance(run.id, node_id="collect")


def test_graph_executor_registry_cancels_before_provider_when_app_is_disabled(
    monkeypatch,
    session_factory: sessionmaker[Session],
) -> None:
    import miy_api.domains.ai_graph.execution_registry as registry_module

    request = _run_request()
    with session_factory() as db:
        run = AiGraphRunRepository(db).create(request)
        db.commit()
        run_id = run.id

    monkeypatch.setattr(
        registry_module,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        "miy_api.domains.ai_graph.execution_policy.can_use_app",
        lambda *_args, **_kwargs: False,
    )
    provider_calls: list[str] = []
    reset_ai_graph_executors()
    try:
        register_ai_graph_executor(
            request.graph.graph_id,
            request.graph.graph_version,
            lambda current_run_id: provider_calls.append(current_run_id) or "executed",
        )

        assert execute_registered_ai_graph(run_id) == "app_disabled"
        assert provider_calls == []
        with session_factory() as db:
            cancelled = db.get(AiGraphRun, run_id)
            assert cancelled is not None
            assert cancelled.status == "cancelled"
            assert cancelled.stage == "registry.policy_gate"
            assert cancelled.error_code == "app_execution_disabled"
    finally:
        reset_ai_graph_executors()


def test_run_graph_resumes_completed_checkpoint_after_stale_lease_without_reexecution(
    session_factory: sessionmaker[Session], monkeypatch
) -> None:
    import miy_api.domains.ai_graph.execution_registry as registry_module

    monkeypatch.setattr(registry_module, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        "miy_api.domains.ai_graph.execution_policy.can_use_app", lambda *_a, **_k: True
    )
    calls: list[str] = []

    async def collect(_state, _context):
        calls.append("collect")
        return AiGraphNodeResult(output={"count": 1})

    async def write(_state, _context):
        calls.append("write")
        return AiGraphNodeResult(output="# report")

    compiled = compile_graph(_linear_spec(), {"collect": collect, "write": write}, InMemorySaver())
    request = _run_request()
    with session_factory() as db:
        repository = AiGraphRunRepository(db)
        run = repository.create(request)
        repository.claim_execution(
            run.id,
            claim_token="crashed-worker",
            now=datetime(2026, 7, 26, 0, 0),
            lease_duration=timedelta(seconds=1),
        )
        run_id = run.id
        db.commit()

    async def seed_checkpoint() -> None:
        await compiled.graph.ainvoke(
            {"inputs": request.inputs, "outputs": {}, "errors": {}, "routes": {}},
            config={"configurable": {"thread_id": run_id, "checkpoint_ns": request.checkpoint_ns}},
            context=AiGraphRuntimeContext(
                run_id=run_id,
                requested_by_user_id=request.requested_by_user_id,
                app_id=request.app_id,
                conversation_id=request.conversation_id,
                progress_callback=lambda _node_id: asyncio.sleep(0),
                policy_callback=_allow_policy,
            ),
        )

    asyncio.run(seed_checkpoint())
    assert calls == ["collect", "write"]
    request_v2 = request.model_copy(
        update={"graph": request.graph.model_copy(update={"graph_version": "2"})}
    )
    with session_factory() as db:
        wrong_version = AiGraphRunRepository(db).create(request_v2)
        wrong_id = wrong_version.id
        db.commit()
    reset_ai_graph_executors()
    try:
        register_ai_graph_executor(
            request.graph.graph_id,
            request.graph.graph_version,
            lambda current_id: asyncio.run(
                run_graph(compiled, request, run_id=current_id, session_factory=session_factory)
            ),
        )
        with pytest.raises(LookupError, match="@2"):
            execute_registered_ai_graph(wrong_id)
        assert calls == ["collect", "write"]
        resumed = execute_registered_ai_graph(run_id)
    finally:
        reset_ai_graph_executors()

    assert resumed.status == "completed"
    assert resumed.outputs == {"collect": {"count": 1}, "write": "# report"}
    assert calls == ["collect", "write"]
    with session_factory() as db:
        run = AiGraphRunRepository(db).require(run_id)
        assert run.execution_attempts == 2
        assert run.status == "completed"


def test_artifact_persists_grid_query_lineage_and_becomes_immutable(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        generation = AiIndexGenerationRepository(db).create_staging(
            AiIndexGenerationCreate(
                app_id="docs",
                generation_key="docs-20260726",
                backend="pgvector",
                source_namespace="docs",
                embedding_provider="local",
                embedding_model="bge-m3",
                embedding_dimensions=1024,
                document_count=20,
                chunk_count=100,
            )
        )
        generation_repository = AiIndexGenerationRepository(db)
        generation_repository.record_validation(
            generation.id, passed=True, validation={"recallAt10": 0.88}
        )
        generation_repository.activate(generation.id)
        repository = AiArtifactRepository(db)
        artifact = repository.create_completed(
            _artifact_create(),
            sources=(
                AiArtifactSourceCreate(
                    source_kind="document",
                    source_ref="issue:42",
                    grid_columns=[
                        {"key": "status", "label": "상태"},
                        {"key": "count", "label": "건수"},
                    ],
                    grid_rows=[{"status": "open", "count": 3}],
                    row_count=1,
                ),
            ),
            queries=(
                AiArtifactQueryCreate(
                    query_kind="sql_family",
                    family_id="issues.by_status",
                    query_spec={"family": "issues.by_status"},
                    statement_text="SELECT status, count(*) FROM issues WHERE region = :region GROUP BY status",
                    typed_params={"region": {"type": "string", "value": "중부"}},
                    execution_status="completed",
                    result_schema=[
                        {"name": "status", "type": "string"},
                        {"name": "count", "type": "integer"},
                    ],
                    result_rows=[{"status": "open", "count": 3}],
                    row_count=1,
                    duration_ms=14,
                    payload_bytes=31,
                    exactness="exact",
                ),
            ),
            index_generations=(AiArtifactIndexGenerationCreate(index_generation_id=generation.id),),
        )
        db.commit()
        loaded = repository.require(artifact.id, eager=True)
        assert re.fullmatch("AIR-\\d{8}-\\d{10}", loaded.artifact_number)
        assert loaded.queries[0].typed_params_json["region"]["value"] == "중부"
        assert loaded.queries[0].result_rows_json == [{"status": "open", "count": 3}]
        assert loaded.sources[0].grid_rows_json == [{"status": "open", "count": 3}]
        assert loaded.index_generations[0].index_generation_id == generation.id
        assert loaded.content_sha256
        query_source = _query_source_response(loaded.queries[0], ordinal=1)
        assert query_source.query_id == loaded.queries[0].id
        assert query_source.source_kind == "sql_query"
        assert query_source.grid_columns[0]["key"] == "status"
        assert query_source.grid_rows == [{"status": "open", "count": 3}]
        with pytest.raises(AiArtifactImmutableError):
            repository.add_source(
                loaded, AiArtifactSourceCreate(source_kind="document", source_ref="issue:99")
            )
        building = repository.create_building(
            _artifact_create(content_text=None).model_copy(update={"conversation_id": None})
        )
        db.commit()
        with pytest.raises(AiArtifactNotFoundError):
            repository.set_completed_visibility(
                loaded.id,
                owner_user_id="another-user",
                visibility="company",
                company_admin_read_acknowledged=True,
            )
        with pytest.raises(AiArtifactNotFoundError):
            repository.set_completed_visibility(
                loaded.id,
                owner_user_id="user-1",
                visibility="company",
                company_admin_read_acknowledged=True,
                expected_app_id="other-app",
            )
        with pytest.raises(AiArtifactNotFoundError):
            repository.set_completed_visibility(
                building.id,
                owner_user_id="user-1",
                visibility="company",
                company_admin_read_acknowledged=True,
            )
        with pytest.raises(AiArtifactNotFoundError):
            repository.set_completed_visibility(
                loaded.id,
                owner_user_id="user-1",
                visibility="company",
                company_admin_read_acknowledged=True,
                expected_artifact_type="analysis",
            )
        with pytest.raises(HTTPException) as denied:
            repository.set_completed_visibility(
                loaded.id, owner_user_id="user-1", visibility="company"
            )
        assert denied.value.status_code == 409
        assert loaded.visibility == "private"
        published, changed = repository.set_completed_visibility(
            loaded.id,
            owner_user_id="user-1",
            visibility="company",
            company_admin_read_acknowledged=True,
        )
        assert changed
        assert published.visibility == "company"
        db.flush()
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == loaded.id, AuditLog.action == "content.publish_to_company"
            )
        )
        assert audit is not None
        assert audit.actor_user_id == "user-1"
        assert audit.payload["company_admin_read_acknowledged"] is True
        with pytest.raises(HTTPException) as denied:
            repository.set_completed_visibility(
                loaded.id, owner_user_id="user-1", visibility="private"
            )
        assert denied.value.status_code == 409
        assert loaded.visibility == "company"


@pytest.mark.parametrize(
    "changed",
    [{"owner_user_id": "other-user"}],
)
def test_artifact_supersession_cannot_cross_owner_app_or_type(session_factory, changed):
    with session_factory() as db:
        repository = AiArtifactRepository(db)
        parent = repository.create_completed(_artifact_create())
        db.commit()
        request = _artifact_create().model_copy(
            update={"supersedes_artifact_id": parent.id, **changed}
        )
        with pytest.raises(ValueError, match="same owner/app/type"):
            repository.create_building(request)
        assert db.query(AiArtifact).count() == 1
