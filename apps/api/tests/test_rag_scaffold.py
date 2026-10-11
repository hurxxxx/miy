from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.core.settings import get_settings
from miy_api.domains.rag.contracts import (
    RagProjection,
    RagQueryRequest,
    RagVectorSearchHit,
)
from miy_api.domains.rag.providers.fake import (
    FakeEmbeddingClient,
    FakeVectorIndexClient,
)
from miy_api.domains.rag.query_service import RagQueryService
from miy_api.domains.rag.service import RagService


def _reset_settings() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


def test_rag_query_reauthorizes_after_retrieval_before_response_projection() -> None:
    vector_index = FakeVectorIndexClient()
    embedding_client = FakeEmbeddingClient()
    RagService(
        vector_index=vector_index,
        embedding_client=embedding_client,
    ).sync_projection(
        RagProjection(
            resource_type="doc",
            resource_id="doc-revoked",
            source_kind="docs",
            text_content="authorization can be revoked during query",
        ),
        collection="rag-final-acl",
    )
    query_service = RagQueryService(
        vector_index=vector_index,
        embedding_client=embedding_client,
    )

    class RevokedBeforeResponse:
        def __init__(self) -> None:
            self.batch_calls = 0

        def __call__(self, hit) -> bool:
            raise AssertionError("batch ACL path should be used")

        def filter_many(self, hits):
            self.batch_calls += 1
            return list(hits) if self.batch_calls == 1 else []

    post_filter = RevokedBeforeResponse()
    response = query_service.query(
        RagQueryRequest(
            collection="rag-final-acl",
            query="authorization revoked",
            top_k=1,
        ),
        post_filter=post_filter,
    )

    assert response.hits == []
    assert post_filter.batch_calls == 2


@pytest.mark.parametrize("transition", ["before_rerank", "during_rerank"])
def test_file_content_hydration_precedes_rerank_and_rechecks_after_it(monkeypatch, transition):
    from miy_api.domains.files.current_content import (
        CurrentFileContent,
        file_candidate_matches_current_content,
    )

    current = {"checksum": "b" * 64 if transition == "before_rerank" else "a" * 64}
    hit = RagVectorSearchHit(
        chunk_id="file-1:1",
        text="synthetic indexed bytes",
        score=1.0,
        projection=RagProjection(
            resource_type="file_manager_file",
            resource_id="file-1",
            source_kind="files",
            metadata={"content_checksum": "a" * 64},
        ),
    )
    rerank_inputs = []
    hydration_calls = []

    def hydrate(hits):
        hydration_calls.append(current["checksum"])
        return [
            candidate
            for candidate in hits
            if file_candidate_matches_current_content(
                CurrentFileContent(current["checksum"], None, "2026-10-07T00:00:00.000000+00:00"),
                candidate_checksum=candidate.projection.metadata.get("content_checksum"),
                candidate_partition_id=candidate.projection.retrieval_partition_id,
                candidate_extracted_at="2026-10-07T00:00:00.000000+00:00",
            )
        ]

    def rerank(*, query, hits, timeout_seconds=None):
        rerank_inputs.extend(candidate.text for candidate in hits)
        current["checksum"] = "b" * 64
        return list(hits)

    service = RagQueryService(
        vector_index=object(),
        embedding_client=SimpleNamespace(embed_query=lambda text, timeout_seconds=None: [1.0]),
        rerank_client=SimpleNamespace(rerank=rerank),
    )
    monkeypatch.setattr(service, "_query_collections", lambda **kwargs: [hit])
    response = service.query(
        RagQueryRequest(collection="synthetic-legacy-files", query="synthetic", top_k=1),
        hit_hydrator=hydrate,
    )
    assert response.hits == []
    assert rerank_inputs == ([] if transition == "before_rerank" else [hit.text])
    assert len(hydration_calls) == 2
