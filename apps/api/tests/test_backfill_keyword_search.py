from __future__ import annotations

import json


from miy_api.domains.retrieval.evaluation import (
    RetrievalEvaluationReport,
    RetrievalQualityGateArtifact,
)


class _Session:
    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _quality_corpus_bytes() -> bytes:
    return json.dumps(
        {
            "artifact_version": 1,
            "corpus_id": "files-rag-v1",
            "cases": [
                {
                    "query_id": f"query-{index}",
                    "user_id": "user-valid",
                    "query": f"heater query {index}",
                    "relevant_resource_ids": ["file-valid"],
                }
                for index in range(60)
            ],
        },
        separators=(",", ":"),
    ).encode()


def _passing_quality_artifact(*, corpus_sha256: str) -> RetrievalQualityGateArtifact:
    bm25 = RetrievalEvaluationReport(
        query_count=60,
        recall_at_k=0.8,
        mrr_at_k=0.7,
        ndcg_at_k=0.7,
        p95_latency_ms=1000,
        acl_violation_count=0,
        citation_failure_count=0,
    )
    dense = bm25.model_copy(update={"mrr_at_k": 0.72, "ndcg_at_k": 0.72})
    hybrid = bm25.model_copy(update={"recall_at_k": 0.9, "mrr_at_k": 0.9, "ndcg_at_k": 0.9})
    return RetrievalQualityGateArtifact(
        artifact_version=2,
        corpus_id="files-rag-v1",
        corpus_sha256=corpus_sha256,
        index_generation="release_20260721",
        keyword_index_uuid="uuid-1",
        keyword_index_config_sha256="c" * 64,
        keyword_index_sha256="b" * 64,
        hybrid=hybrid,
        bm25=bm25,
        dense=dense,
    )
