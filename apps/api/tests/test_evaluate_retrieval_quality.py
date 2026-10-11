from __future__ import annotations


from miy_api.domains.retrieval.evaluation import RetrievalQualityCorpusCase


def _corpus_case() -> RetrievalQualityCorpusCase:
    return RetrievalQualityCorpusCase(
        query_id="heater-pressure",
        user_id="user-1",
        query="히터 비상 정지 압력",
        relevant_resource_ids=["file-1"],
        forbidden_resource_ids=["file-private"],
        source_kinds=["files"],
    )
