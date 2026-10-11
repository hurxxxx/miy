from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from miy_api.domains.retrieval.files_generation_runner import (
    FilesBackendPairInspection,
    FilesGenerationBaselineMode,
    FilesGenerationError,
    FilesGenerationMaterializationBatch,
    FilesGenerationRunner,
    FilesPhysicalProjectionInventory,
    FilesSourceProjectionSnapshot,
    load_files_source_snapshot,
)
from miy_api.domains.retrieval.evaluation import (
    RetrievalEvaluationReport,
    RetrievalQualityGateArtifact,
    retrieval_embedding_generation_identity,
    retrieval_quality_corpus_sha256,
    retrieval_reranker_generation_identity,
)
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionGeneration,
    RetrievalProjectionGenerationAttestation,
)
from miy_api.domains.rag.runtime import (
    resolve_default_collection_name,
    resolve_partitioned_rag_collection_alias,
)
from miy_api.domains.search.index_gateway import (
    keyword_search_index_alias,
    keyword_search_partitioned_index_alias,
)
from miy_api.domains.source_access.resource_types import (
    FILE_MANAGER_FILE_RESOURCE_TYPE,
)


_EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_RUNNER_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "manage_files_retrieval_generation.py"
)
_PARTITION_ID = "826901c6-58b1-4687-b7e0-d7844a337a01"


def _load_runner_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "test_manage_files_retrieval_generation_script",
        _RUNNER_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def generation_session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        RetrievalPartition.__table__,
        RetrievalProjectionEvent.__table__,
        RetrievalProjectionGeneration.__table__,
        RetrievalProjectionGenerationAttestation.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(
            RetrievalPartition(
                id=_PARTITION_ID,
                source_namespace="files-generation-test",
                candidate_scope_kind="company",
                is_default_ingest=False,
            )
        )
    try:
        yield factory
    finally:
        engine.dispose()


def _settings(*, environment: str = "development") -> SimpleNamespace:
    return SimpleNamespace(
        environment=environment,
        opensearch_url="http://opensearch.invalid",
        opensearch_index_prefix="test",
        keyword_search_backend="opensearch",
        rag_vector_index_provider="qdrant",
        rag_qdrant_url="http://qdrant.invalid",
        rag_qdrant_api_key="secret-never-rendered",
        rag_qdrant_collection_prefix="test-rag",
        rag_embedding_provider="fake",
        rag_rerank_provider="fake",
        rag_local_reranker_model="fake-reranker",
        rag_rerank_candidate_k=20,
        files_retrieval_enabled=False,
    )


def _source_snapshot(
    *,
    count: int = 0,
    unavailable: int = 0,
    event_watermark: int = 0,
    files_event_watermark: int = 0,
) -> FilesSourceProjectionSnapshot:
    identity = _EMPTY_SHA256 if count == 0 else "1" * 64
    return FilesSourceProjectionSnapshot(
        event_watermark=event_watermark,
        files_event_watermark=files_event_watermark,
        resource_count=count,
        identity_sha256=identity,
        artifact_sha256=_EMPTY_SHA256 if count == 0 else "2" * 64,
        unsupported_count=0,
        unavailable_count=unavailable,
    )


def _inventory(
    *, resources: int = 0, records: int | None = None
) -> FilesPhysicalProjectionInventory:
    return FilesPhysicalProjectionInventory(
        resource_count=resources,
        record_count=resources if records is None else records,
        identity_sha256=_EMPTY_SHA256 if resources == 0 else "1" * 64,
        content_sha256=_EMPTY_SHA256 if resources == 0 else "3" * 64,
        config_sha256="4" * 64,
        physical_id="physical-id",
        projection_sha256=_EMPTY_SHA256 if resources == 0 else "5" * 64,
    )


def _loaded_source_snapshot(
    *,
    metadata_version: int = 1,
    access_scope_kind: str = "company",
    source_title: str | None = None,
    extracted_at: datetime = datetime(2026, 1, 1, tzinfo=UTC),
) -> FilesSourceProjectionSnapshot:
    external = source_title is not None
    row = SimpleNamespace(
        id="file-1",
        extraction_status="ready",
        extraction_content_checksum="a" * 64,
        extraction_text="stable source text",
        extraction_blocks=[
            {
                "document_id": "file-1",
                "block_id": "file-1:text:1",
                "locator_kind": "document",
                "locator_label": "Document",
                "section_path": "Body",
                "block_kind": "text",
                "text": "stable source text",
                "rows": [],
            }
        ],
        extraction_metadata={"parser_version": "test-v1"},
        extracted_at=extracted_at,
        file_partition_id=_PARTITION_ID,
        projection_version=1,
        head_partition_id=_PARTITION_ID,
        desired_state="active",
        content_checksum="a" * 64,
        filename="source.txt",
        content_type="text/plain",
        size_bytes=18,
        visibility="company",
        folder_id=None,
        corpus_id="corpus-1",
        owner_id="user-1",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner_display_name="Owner",
        owner_full_name="Owner Name",
        corpus_partition_id=_PARTITION_ID,
        corpus_access_scope_kind=access_scope_kind,
        corpus_metadata_version=metadata_version,
        corpus_source_managed=external,
        corpus_authorization_mode="explicit_grants" if external else "cohort",
        source_metadata_source_kind="external_repository" if external else None,
        source_metadata_source_updated_at=(datetime(2026, 1, 2, tzinfo=UTC) if external else None),
        source_metadata_title=source_title,
        source_metadata_author="Source Author" if external else None,
        source_metadata_authored_at=(datetime(2025, 12, 1, tzinfo=UTC) if external else None),
        source_metadata_department="Engineering" if external else None,
        source_metadata_document_type="report" if external else None,
        source_metadata_acl_resolved=True if external else None,
        partition_source_namespace="files",
        partition_candidate_scope_kind=access_scope_kind,
        partition_candidate_user_id=None,
        partition_state="active",
        partition_metadata_version=metadata_version,
        partition_is_default_ingest=False,
    )

    class Result:
        def __iter__(self):
            return iter((row,))

    class Db:
        def execute(self, _statement: object) -> Result:
            return Result()

        def scalar(self, _statement: object) -> int:
            return 0

    return load_files_source_snapshot(Db())  # type: ignore[arg-type]


def _quality_corpus_bytes() -> bytes:
    return json.dumps(
        {
            "artifact_version": 1,
            "corpus_id": "files-generation-quality-v1",
            "cases": [
                {
                    "query_id": f"query-{index}",
                    "user_id": "user-1",
                    "query": f"quality query {index}",
                    "relevant_resource_ids": ["file-1"],
                    "forbidden_resource_ids": ["file-forbidden"],
                    "source_kinds": ["files"],
                }
                for index in range(60)
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _passing_v3_quality_artifact(
    *,
    settings: SimpleNamespace,
    corpus_bytes: bytes,
) -> RetrievalQualityGateArtifact:
    embedding_identity = retrieval_embedding_generation_identity(settings)
    reranker_identity = retrieval_reranker_generation_identity(settings)
    baseline = RetrievalEvaluationReport(
        query_count=60,
        recall_at_k=0.5,
        mrr_at_k=0.5,
        ndcg_at_k=0.5,
        p95_latency_ms=100,
        acl_violation_count=0,
        citation_failure_count=0,
    )
    hybrid = baseline.model_copy(update={"recall_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0})
    return RetrievalQualityGateArtifact(
        artifact_version=3,
        corpus_id="files-generation-quality-v1",
        corpus_sha256=retrieval_quality_corpus_sha256(corpus_bytes),
        index_generation="v3-quality",
        keyword_index_uuid="physical-id",
        keyword_index_config_sha256="4" * 64,
        keyword_index_sha256="3" * 64,
        qdrant_physical_id="physical-id",
        qdrant_config_sha256="4" * 64,
        qdrant_content_sha256="3" * 64,
        embedding_model_identity=embedding_identity.model_identity,
        embedding_config_sha256=embedding_identity.config_sha256,
        reranker_model_identity=reranker_identity.model_identity,
        reranker_config_sha256=reranker_identity.config_sha256,
        source_files_event_watermark=0,
        source_resource_count=1,
        source_identity_sha256="1" * 64,
        source_artifact_sha256="2" * 64,
        source_acl_envelope_sha256=_EMPTY_SHA256,
        judgment_acl_sha256="6" * 64,
        hybrid=hybrid,
        bm25=baseline,
        dense=baseline,
    )


class _FakeBackends:
    def __init__(self) -> None:
        self.opensearch: FilesPhysicalProjectionInventory | None = None
        self.qdrant: FilesPhysicalProjectionInventory | None = None
        self.prepare_calls = 0
        self.aliases: dict[str, str] = {}
        self.alias_operations: list[tuple[str, str, str | None]] = []
        self.fail_alias_backend: str | None = None
        self.fail_after_move = False
        self.fail_remove_backend: str | None = None

    def inspect_pair(self, spec) -> FilesBackendPairInspection:
        del spec
        return FilesBackendPairInspection(
            opensearch=self.opensearch,
            qdrant=self.qdrant,
        )

    def prepare_empty_pair(self, spec) -> None:
        del spec
        self.prepare_calls += 1
        self.opensearch = _inventory()
        self.qdrant = _inventory(records=0)

    def alias_target(self, *, backend: str, alias_name: str) -> str | None:
        del backend
        return self.aliases.get(alias_name)

    def set_alias(self, *, backend: str, alias_name: str, physical_name: str) -> None:
        self.alias_operations.append((backend, alias_name, physical_name))
        if self.fail_alias_backend == backend and not self.fail_after_move:
            raise RuntimeError("secret backend failure")
        self.aliases[alias_name] = physical_name
        if self.fail_alias_backend == backend and self.fail_after_move:
            raise RuntimeError("secret backend failure after move")

    def remove_alias(self, *, backend: str, alias_name: str) -> None:
        self.alias_operations.append((backend, alias_name, None))
        if self.fail_remove_backend == backend:
            raise RuntimeError("secret alias restore failure")
        self.aliases.pop(alias_name, None)


class _FakeMaterializer:
    def __init__(
        self,
        *,
        backends: _FakeBackends,
        target_resources: int,
        complete: bool = True,
        caught_up: bool = True,
    ) -> None:
        self.backends = backends
        self.target_resources = target_resources
        self.complete = complete
        self.caught_up = caught_up
        self.calls = 0

    def materialize_batch(self, **kwargs) -> FilesGenerationMaterializationBatch:
        self.calls += 1
        through = int(kwargs["through_event_sequence"])
        after = int(kwargs["after_event_sequence"])
        if self.complete:
            self.backends.opensearch = _inventory(resources=self.target_resources)
            self.backends.qdrant = _inventory(
                resources=self.target_resources,
                records=max(self.target_resources, 1),
            )
        return FilesGenerationMaterializationBatch(
            target_event_sequence=through,
            next_event_sequence=through if self.complete else after + 1,
            scanned_events=1,
            keyword_succeeded=1,
            vector_succeeded=1,
            complete=self.complete,
            caught_up=self.caught_up,
            keyword_remaining=0,
            vector_remaining=0,
        )

    def inspect_reconciliation(self, *, through_event_sequence: int) -> object:
        return SimpleNamespace(
            target_event_sequence=through_event_sequence,
            current_event_sequence=through_event_sequence,
            keyword_remaining=0,
            vector_remaining=0,
            caught_up=True,
        )


def _runner(
    factory: sessionmaker[Session],
    backends: _FakeBackends,
    *,
    snapshot: FilesSourceProjectionSnapshot | None = None,
    materializer: _FakeMaterializer | None = None,
    source_snapshot_loader: Callable[[Session], FilesSourceProjectionSnapshot] | None = None,
) -> FilesGenerationRunner:
    return FilesGenerationRunner(
        session_factory=factory,
        settings=_settings(),  # type: ignore[arg-type]
        backends=backends,
        source_snapshot_loader=(
            source_snapshot_loader or (lambda _db: snapshot or _source_snapshot())
        ),
        materializer=materializer,
    )


def _append_projection_event(
    factory: sessionmaker[Session],
    *,
    resource_type: str,
    resource_id: str,
) -> int:
    with factory.begin() as db:
        event_sequence = (
            int(db.scalar(select(func.max(RetrievalProjectionEvent.event_sequence))) or 0) + 1
        )
        db.add(
            RetrievalProjectionEvent(
                event_sequence=event_sequence,
                resource_type=resource_type,
                resource_id=resource_id,
                projection_version=1,
                retrieval_partition_id=_PARTITION_ID,
                change_kind="delete",
                desired_state="deleted",
            )
        )
    return event_sequence


def _scoped_empty_source_snapshot(db: Session) -> FilesSourceProjectionSnapshot:
    return _source_snapshot(
        event_watermark=int(
            db.scalar(select(func.max(RetrievalProjectionEvent.event_sequence))) or 0
        ),
        files_event_watermark=int(
            db.scalar(
                select(func.max(RetrievalProjectionEvent.event_sequence)).where(
                    RetrievalProjectionEvent.resource_type == FILE_MANAGER_FILE_RESOURCE_TYPE
                )
            )
            or 0
        ),
    )


def _ready_empty_pair(
    factory: sessionmaker[Session],
    backends: _FakeBackends,
    *,
    generation_key: str,
) -> FilesGenerationRunner:
    runner = _runner(factory, backends)
    runner.prepare(
        generation_key=generation_key,
        baseline_mode=FilesGenerationBaselineMode.EMPTY,
    )
    runner.validate(
        generation_key=generation_key,
        writes_quiesced=True,
        reconciliation_watermark=0,
        allow_empty_non_production=True,
    )
    return runner


def test_initial_cutover_uses_dedicated_aliases_and_leaves_legacy_aliases_untouched(
    generation_session_factory: sessionmaker[Session],
) -> None:
    backends = _FakeBackends()
    settings = _settings()
    legacy_opensearch_alias = keyword_search_index_alias(settings.opensearch_index_prefix)
    legacy_qdrant_alias = resolve_default_collection_name(settings)  # type: ignore[arg-type]
    backends.aliases[legacy_opensearch_alias] = "legacy-opensearch-v2"
    backends.aliases[legacy_qdrant_alias] = "legacy-qdrant"
    runner = _ready_empty_pair(
        generation_session_factory,
        backends,
        generation_key="first-active",
    )

    result = runner.cutover(
        generation_key="first-active",
        writes_quiesced=True,
        rollback_window=timedelta(days=7),
    )

    assert result.state == "active"
    assert backends.aliases[legacy_opensearch_alias] == "legacy-opensearch-v2"
    assert backends.aliases[legacy_qdrant_alias] == "legacy-qdrant"
    switched_aliases = {alias for _backend, alias, target in backends.alias_operations if target}
    assert legacy_opensearch_alias not in switched_aliases
    assert legacy_qdrant_alias not in switched_aliases


def test_alias_precondition_mismatch_never_overwrites_unknown_external_alias(
    generation_session_factory: sessionmaker[Session],
) -> None:
    backends = _FakeBackends()
    runner = _ready_empty_pair(
        generation_session_factory,
        backends,
        generation_key="unknown-alias",
    )
    settings = _settings()
    opensearch_alias = keyword_search_partitioned_index_alias(settings.opensearch_index_prefix)
    qdrant_alias = resolve_partitioned_rag_collection_alias(settings)  # type: ignore[arg-type]
    backends.aliases[opensearch_alias] = "operator-owned-foreign-target"

    with pytest.raises(FilesGenerationError) as caught:
        runner.cutover(
            generation_key="unknown-alias",
            writes_quiesced=True,
            rollback_window=timedelta(days=7),
        )

    assert caught.value.code == "alias_precondition_mismatch"
    assert backends.aliases == {opensearch_alias: "operator-owned-foreign-target"}
    assert qdrant_alias not in backends.aliases
    assert backends.alias_operations == []
    with generation_session_factory() as db:
        rows = tuple(db.scalars(select(RetrievalProjectionGeneration)).all())
    assert {row.state for row in rows} == {"compensation_required"}


def test_new_files_event_during_alias_switch_restores_aliases_and_compensates_pair(
    generation_session_factory: sessionmaker[Session],
) -> None:
    files_watermark = _append_projection_event(
        generation_session_factory,
        resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
        resource_id="file-before-cutover",
    )

    class EventInjectingBackends(_FakeBackends):
        injected = False

        def set_alias(
            self,
            *,
            backend: str,
            alias_name: str,
            physical_name: str,
        ) -> None:
            super().set_alias(
                backend=backend,
                alias_name=alias_name,
                physical_name=physical_name,
            )
            if not self.injected:
                self.injected = True
                _append_projection_event(
                    generation_session_factory,
                    resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
                    resource_id="file-during-cutover",
                )

    backends = EventInjectingBackends()
    runner = _runner(
        generation_session_factory,
        backends,
        source_snapshot_loader=_scoped_empty_source_snapshot,
    )
    runner.prepare(
        generation_key="files-cutover-race",
        baseline_mode=FilesGenerationBaselineMode.EMPTY,
    )
    runner.validate(
        generation_key="files-cutover-race",
        writes_quiesced=True,
        reconciliation_watermark=files_watermark,
        allow_empty_non_production=True,
    )

    with pytest.raises(FilesGenerationError) as caught:
        runner.cutover(
            generation_key="files-cutover-race",
            writes_quiesced=True,
            rollback_window=timedelta(days=7),
        )

    assert caught.value.code == "database_cutover_failed"
    assert backends.aliases == {}
    with generation_session_factory() as db:
        rows = tuple(db.scalars(select(RetrievalProjectionGeneration)).all())
    assert {row.state for row in rows} == {"failed"}


@pytest.mark.parametrize("fail_after_move", [True])
def test_partial_alias_failure_restores_both_aliases_and_compensates_database_pair(
    generation_session_factory: sessionmaker[Session],
    fail_after_move: bool,
) -> None:
    backends = _FakeBackends()
    runner = _ready_empty_pair(
        generation_session_factory,
        backends,
        generation_key="partial-alias",
    )
    backends.fail_alias_backend = "qdrant"
    backends.fail_after_move = fail_after_move

    with pytest.raises(FilesGenerationError) as caught:
        runner.cutover(
            generation_key="partial-alias",
            writes_quiesced=True,
            rollback_window=timedelta(days=7),
        )

    assert caught.value.code == "alias_cutover_failed"
    assert "secret" not in str(caught.value)
    assert backends.aliases == {}
    with generation_session_factory() as db:
        rows = tuple(db.scalars(select(RetrievalProjectionGeneration)).all())
    assert {row.state for row in rows} == {"failed"}
    assert {row.failure_reason for row in rows} == {"external_alias_switch_failed"}
