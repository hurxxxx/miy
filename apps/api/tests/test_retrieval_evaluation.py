from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.domains.retrieval.evaluation import (
    RetrievalEvaluationCase,
    RetrievalQualityGateArtifact,
    evaluate_hybrid_quality_gate,
    evaluate_retrieval_cases,
    validate_quality_gate_artifact,
    retrieval_quality_corpus_sha256,
)


def _cases(*, first_rank: int, count: int = 60, latency_ms: int = 1200):
    cases = []
    for index in range(count):
        irrelevant = [f"irrelevant-{index}-{rank}" for rank in range(first_rank - 1)]
        cases.append(
            RetrievalEvaluationCase(
                query_id=f"query-{index}",
                relevant_resource_ids=[f"relevant-{index}"],
                ranked_resource_ids=[*irrelevant, f"relevant-{index}"],
                latency_ms=latency_ms,
            )
        )
    return cases


def test_files_quality_artifact_v3_requires_exact_vector_generation_identity() -> None:
    report = {
        "query_count": 60,
        "recall_at_k": 1.0,
        "mrr_at_k": 1.0,
        "ndcg_at_k": 1.0,
        "p95_latency_ms": 10,
        "acl_violation_count": 0,
        "citation_failure_count": 0,
    }

    with pytest.raises(ValueError, match="qdrant_physical_id"):
        RetrievalQualityGateArtifact(
            artifact_version=3,
            corpus_id="files-v3",
            corpus_sha256="a" * 64,
            index_generation="release_20260723",
            keyword_index_uuid="opensearch-uuid",
            keyword_index_config_sha256="b" * 64,
            keyword_index_sha256="c" * 64,
            bm25=report,
            dense=report,
            hybrid=report,
        )

    artifact = RetrievalQualityGateArtifact(
        artifact_version=3,
        corpus_id="files-v3",
        corpus_sha256="a" * 64,
        index_generation="release_20260723",
        keyword_index_uuid="opensearch-uuid",
        keyword_index_config_sha256="b" * 64,
        keyword_index_sha256="c" * 64,
        qdrant_physical_id="files-v1-release_20260723",
        qdrant_config_sha256="d" * 64,
        qdrant_content_sha256="e" * 64,
        embedding_model_identity="dragonkue/model@revision",
        embedding_config_sha256="f" * 64,
        reranker_model_identity="inference_gateway:example/reranker",
        reranker_config_sha256="1" * 64,
        source_files_event_watermark=7,
        source_resource_count=10,
        source_identity_sha256="2" * 64,
        source_artifact_sha256="3" * 64,
        source_acl_envelope_sha256="4" * 64,
        judgment_acl_sha256="5" * 64,
        bm25=report,
        dense=report,
        hybrid=report,
    )

    assert artifact.artifact_version == 3


def _reranker_settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "rag_rerank_provider": "inference_gateway",
        "rag_local_reranker_model": "example/reranker",
        "rag_local_reranker_revision": "revision-a",
        "rag_local_reranker_device": "cuda",
        "rag_local_reranker_dtype": "bfloat16",
        "rag_local_reranker_batch_size": 16,
        "rag_local_reranker_max_length": 512,
        "rag_local_reranker_trust_remote_code": False,
        "rag_rerank_candidate_k": 80,
        "inference_gateway_base_url": "https://gateway.example/internal",
        "inference_gateway_api_key": "gateway-secret-a",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_quality_gate_rejects_acl_or_citation_failures_in_each_strategy() -> None:
    safe = evaluate_retrieval_cases(_cases(first_rank=1))
    unsafe_keyword = safe.model_copy(update={"acl_violation_count": 1, "p95_latency_ms": 6_000})
    unsafe_dense = safe.model_copy(update={"citation_failure_count": 1})

    result = evaluate_hybrid_quality_gate(
        hybrid=safe,
        bm25=unsafe_keyword,
        dense=unsafe_dense,
    )

    assert result.passed is False
    assert set(result.reasons) >= {
        "acl_violations",
        "citation_failures",
        "p95_latency_ms>5000",
    }


def test_quality_artifact_is_bound_to_exact_corpus_bytes() -> None:
    bm25 = evaluate_retrieval_cases(_cases(first_rank=3))
    dense = evaluate_retrieval_cases(_cases(first_rank=2))
    hybrid = evaluate_retrieval_cases(_cases(first_rank=1))
    corpus_bytes = b'{"artifact_version":1,"corpus_id":"files-rag-v1","cases":[]}'
    artifact = RetrievalQualityGateArtifact(
        artifact_version=2,
        corpus_id="files-rag-v1",
        corpus_sha256=retrieval_quality_corpus_sha256(corpus_bytes),
        index_generation="release_20260721",
        keyword_index_uuid="uuid-1",
        keyword_index_config_sha256="c" * 64,
        keyword_index_sha256="b" * 64,
        hybrid=hybrid,
        bm25=bm25,
        dense=dense,
    )

    result = validate_quality_gate_artifact(
        artifact,
        expected_index_generation="release_20260721",
        expected_corpus_id="files-rag-v1",
        expected_corpus_sha256=retrieval_quality_corpus_sha256(corpus_bytes + b"\n"),
    )

    assert result.passed is False
    assert result.reasons == ("corpus_sha256_mismatch",)
