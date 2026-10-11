from __future__ import annotations

from collections.abc import Sequence


from miy_api.domains.rag.contracts import RagVectorSearchHit
from miy_api.domains.retrieval.candidate_ranking import (
    CandidateDocument,
    CandidateRankingRequest,
)


class _SemanticEmbeddingClient:
    provider_name = "test-semantic"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.document_batches: list[list[str]] = []

    def embed_query(
        self,
        text: str,
        timeout_seconds: float | None = None,
    ) -> list[float]:
        del timeout_seconds
        self.queries.append(text)
        return [1.0, 0.0]

    def embed_texts(
        self,
        texts: list[str],
        timeout_seconds: float | None = None,
    ) -> list[list[float]]:
        del timeout_seconds
        self.document_batches.append(texts)
        return [[1.0, 0.0] if "semantic-target" in text else [0.0, 1.0] for text in texts]


class _RecordingRerankClient:
    provider_name = "test-reranker"

    def __init__(self) -> None:
        self.calls = 0
        self.candidate_counts: list[int] = []

    def rerank(
        self,
        *,
        query: str,
        hits: list[RagVectorSearchHit],
        timeout_seconds: float | None = None,
    ) -> list[RagVectorSearchHit]:
        del query, timeout_seconds
        self.calls += 1
        self.candidate_counts.append(len(hits))
        return [
            hit.model_copy(update={"score": float(index)})
            for index, hit in enumerate(reversed(hits), start=1)
        ]


def _request(
    *,
    query: str,
    candidates: Sequence[CandidateDocument],
    top_k: int = 10,
    enable_semantic: bool = False,
    enable_rerank: bool = False,
) -> CandidateRankingRequest:
    return CandidateRankingRequest(
        query=query,
        candidates=candidates,
        top_k=top_k,
        enable_semantic=enable_semantic,
        enable_rerank=enable_rerank,
    )
