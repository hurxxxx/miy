from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from miy_api import evaluate_files_partitioned_quality as quality_cli
from miy_api.domains.auth.models import User
from miy_api.domains.retrieval import files_quality_judgments as quality_judgments

from miy_api.domains.retrieval.contracts import (
    RetrievalHit,
    RetrievalProfile,
    RetrievalQueryResponse,
)
from miy_api.domains.retrieval.evaluation import (
    RetrievalEvaluationReport,
    RetrievalQualityGateArtifact,
)
from miy_api.domains.retrieval.files_generation_runner import (
    FilesBackendPairInspection,
    FilesPhysicalProjectionInventory,
    FilesSourceProjectionSnapshot,
)
from miy_api.domains.retrieval.files_quality_evaluator import (
    FilesQualityEvaluationError,
    evaluate_files_partitioned_quality,
)


@pytest.fixture(autouse=True)
def _allow_admitted_evaluation_user(monkeypatch):
    def admitted(_db, *, user_id, app_id):
        assert user_id == "user-sensitive" and app_id == "files"
        return True

    monkeypatch.setattr(quality_judgments, "can_use_app", admitted)


class _Session:
    def __init__(self, active_file_ids: set[str] | None = None) -> None:
        self.user = SimpleNamespace(
            id="user-sensitive",
            status="active",
            login_blocked=False,
        )
        self.active_file_ids = active_file_ids or {
            "file-sensitive",
            "file-forbidden-sensitive",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, model, identity):
        if model is User and identity == self.user.id:
            return self.user
        return None

    def scalars(self, _query):
        return sorted(self.active_file_ids)


class _JudgmentPolicy:
    def __init__(self, allowed_ids: set[str] | None = None) -> None:
        self.allowed_ids = {"file-sensitive"} if allowed_ids is None else allowed_ids
        self.rag_modes: list[bool] = []

    def authorize_many_resources(self, resources, *, rag: bool = False):
        self.rag_modes.append(rag)
        return {identity for identity in resources if identity[1] in self.allowed_ids}


class _Backends:
    def __init__(self, inspection: FilesBackendPairInspection) -> None:
        self.inspection = inspection
        self.inspected_specs = []

    def inspect_pair(self, spec):
        self.inspected_specs.append(spec)
        return self.inspection


def _corpus_bytes() -> bytes:
    return json.dumps(
        {
            "artifact_version": 1,
            "corpus_id": "files-judged-v1",
            "cases": [
                {
                    "query_id": f"query-{index}",
                    "user_id": "user-sensitive",
                    "query": f"sensitive query body {index}",
                    "relevant_resource_ids": ["file-sensitive"],
                    "forbidden_resource_ids": ["file-forbidden-sensitive"],
                    "source_kinds": ["files"],
                }
                for index in range(60)
            ],
        },
        ensure_ascii=False,
    ).encode()


def _settings():
    return SimpleNamespace(
        opensearch_index_prefix="miy-search",
        rag_qdrant_collection_prefix="miy-rag",
        rag_embedding_provider="inference_gateway",
        rag_local_embedding_model="example/embedding-model",
        rag_local_embedding_revision="revision-a",
        rag_local_embedding_device="cuda",
        rag_local_embedding_dtype="bfloat16",
        rag_local_embedding_batch_size=16,
        rag_local_embedding_max_seq_length=1024,
        rag_local_embedding_normalize=True,
        rag_local_embedding_query_prompt_name="query",
        rag_local_embedding_query_prefix="",
        rag_local_embedding_trust_remote_code=False,
        rag_rerank_provider="inference_gateway",
        inference_gateway_base_url="http://127.0.0.1:18080/v1",
        rag_local_reranker_model="example/reranker",
        rag_local_reranker_revision="reranker-revision-a",
        rag_local_reranker_device="cuda",
        rag_local_reranker_dtype="bfloat16",
        rag_local_reranker_batch_size=16,
        rag_local_reranker_max_length=512,
        rag_local_reranker_trust_remote_code=False,
        rag_rerank_candidate_k=80,
    )


def _source_snapshot() -> FilesSourceProjectionSnapshot:
    return FilesSourceProjectionSnapshot(
        event_watermark=7,
        files_event_watermark=7,
        resource_count=1,
        identity_sha256="1" * 64,
        artifact_sha256="8" * 64,
        acl_envelope_sha256="9" * 64,
        unsupported_count=0,
        unavailable_count=0,
    )


def test_evaluator_fails_closed_if_principal_acl_universe_changes_mid_run() -> None:
    opensearch = FilesPhysicalProjectionInventory(
        resource_count=1,
        record_count=1,
        identity_sha256="1" * 64,
        content_sha256="2" * 64,
        config_sha256="3" * 64,
        physical_id="opensearch-uuid",
    )
    qdrant = FilesPhysicalProjectionInventory(
        resource_count=1,
        record_count=1,
        identity_sha256="1" * 64,
        content_sha256="4" * 64,
        config_sha256="5" * 64,
        physical_id="miy-rag-example-embedding-model-v1-release_20260723",
    )
    policies = iter(
        (
            _JudgmentPolicy({"file-sensitive"}),
            _JudgmentPolicy({"file-sensitive", "file-newly-visible"}),
        )
    )

    def query_retrieval(_db, **kwargs):
        request = kwargs["request"]
        return RetrievalQueryResponse(
            query=request.query,
            strategy=request.strategy,
            hits=[
                RetrievalHit(
                    source="keyword",
                    resource_type="file_manager_file",
                    resource_id="file-sensitive",
                    citation="/files/file-sensitive",
                )
            ],
            profile=RetrievalProfile(strategy=request.strategy),
            latency_ms=10,
        )

    with pytest.raises(
        FilesQualityEvaluationError,
        match="quality_acl_changed_during_evaluation",
    ):
        evaluate_files_partitioned_quality(
            corpus_bytes=_corpus_bytes(),
            generation_key="release_20260723",
            settings=_settings(),
            session_factory=lambda: _Session(
                {
                    "file-sensitive",
                    "file-forbidden-sensitive",
                    "file-newly-visible",
                }
            ),
            backends=_Backends(FilesBackendPairInspection(opensearch=opensearch, qdrant=qdrant)),
            keyword_client_factory=lambda *_args: object(),
            rag_query_service_factory=lambda *_args: object(),
            source_acl_policy_factory=lambda *_args: next(policies),
            source_snapshot_loader=lambda _db: _source_snapshot(),
            retrieval_query=query_retrieval,
        )


def _passing_artifact() -> RetrievalQualityGateArtifact:
    report = RetrievalEvaluationReport(
        query_count=60,
        recall_at_k=1.0,
        mrr_at_k=1.0,
        ndcg_at_k=1.0,
        p95_latency_ms=10,
        acl_violation_count=0,
        citation_failure_count=0,
    )
    return RetrievalQualityGateArtifact(
        artifact_version=3,
        corpus_id="sensitive-corpus-id",
        corpus_sha256="1" * 64,
        index_generation="release_20260723",
        keyword_index_uuid="opensearch-uuid",
        keyword_index_config_sha256="2" * 64,
        keyword_index_sha256="3" * 64,
        qdrant_physical_id="qdrant-physical",
        qdrant_config_sha256="4" * 64,
        qdrant_content_sha256="5" * 64,
        embedding_model_identity="example/embedding-model",
        embedding_config_sha256="6" * 64,
        reranker_model_identity="inference_gateway:example/reranker",
        reranker_config_sha256="7" * 64,
        source_files_event_watermark=0,
        source_resource_count=1,
        source_identity_sha256="8" * 64,
        source_artifact_sha256="9" * 64,
        source_acl_envelope_sha256="a" * 64,
        judgment_acl_sha256="b" * 64,
        bm25=report,
        dense=report,
        hybrid=report,
    )


def test_cli_writes_artifact_atomically_without_overwriting_or_echoing_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus_path = tmp_path / "corpus.json"
    output_path = tmp_path / "quality.json"
    corpus_path.write_bytes(_corpus_bytes())
    closed: list[bool] = []

    class Backends:
        def __init__(self, _settings) -> None:
            pass

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(quality_cli, "get_settings", _settings)
    monkeypatch.setattr(quality_cli, "FilesPhysicalGenerationBackends", Backends)
    monkeypatch.setattr(
        quality_cli,
        "evaluate_files_partitioned_quality",
        lambda **_kwargs: _passing_artifact(),
    )

    result = quality_cli.main(
        [
            "--corpus",
            str(corpus_path),
            "--generation",
            "release_20260723",
            "--output",
            str(output_path),
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert closed == [True]
    assert output_path.exists()
    assert os.stat(output_path).st_mode & 0o777 == 0o600
    assert json.loads(output_path.read_text())["artifact_version"] == 3
    assert "sensitive query" not in output.out + output.err
    assert "user-sensitive" not in output.out + output.err
    assert "file-sensitive" not in output.out + output.err
    original = output_path.read_bytes()

    second = quality_cli.main(
        [
            "--corpus",
            str(corpus_path),
            "--generation",
            "release_20260723",
            "--output",
            str(output_path),
        ]
    )

    second_output = capsys.readouterr()
    assert second == 1
    assert output_path.read_bytes() == original
    assert second_output.err.strip() == "status=failed reason=artifact_output_exists"
