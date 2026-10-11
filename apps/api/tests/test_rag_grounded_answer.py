from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.domains.rag import grounded_answer
from miy_api.domains.rag.grounded_answer import LlmGroundedAnswerSynthesizer


def test_llm_grounded_answer_rejects_truncated_completion(monkeypatch) -> None:
    def fake_execute_llm(workload_id, context, db, **kwargs):
        del workload_id, context, db, kwargs
        completion = SimpleNamespace(
            structured_output={
                "statements": [{"text": "복지제도 요약", "citation_indexes": [1]}],
                "unsupported_claims": [],
            },
            text='{"statements":[{"text":"잘린 답변","citation_indexes":[1]}]',
            finish_reason="length",
        )
        return SimpleNamespace(completion=completion)

    monkeypatch.setattr(
        grounded_answer,
        "execute_llm",
        fake_execute_llm,
    )
    synthesizer = _llm_synthesizer()

    with pytest.raises(ValueError, match="did not finish cleanly"):
        synthesizer.synthesize(query="복지제도 정리해줘", hits=[_hit()])


def _llm_synthesizer() -> LlmGroundedAnswerSynthesizer:
    return LlmGroundedAnswerSynthesizer(
        db=object(),
        actor_user_id="user-1",
        principal_kind="user",
        principal_id="user-1",
        source="api.retrieval.query",
    )


def _hit():
    return SimpleNamespace(
        source_kind="docs_native_doc",
        resource_type="docs_native_doc",
        resource_id="doc-1",
        title="복지제도 기준",
        summary="복지제도 기준",
        excerpt="건강검진, 가족수당, 경조비, 장기근속 포상",
        score=0.9,
        citation="[첨부: 복지제도.pdf] [p.1]",
    )
