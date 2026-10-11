from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from miy_api.domains.files import conversation_scope
from miy_api.domains.files.chat_retrieval import (
    FileChatEvidenceResult,
    FileSearchUnavailable,
)
from miy_api.domains.files.conversation_scope import (
    FilesConversationScopeAdapter,
)


def _scope_inputs() -> dict:
    return {
        "db": SimpleNamespace(),
        "principal": SimpleNamespace(
            kind="user",
            principal_id="user-1",
        ),
        "user": SimpleNamespace(id="user-1", locale="ko-KR"),
        "scope_resource_id": "company",
        "conversation": SimpleNamespace(id="conversation-1"),
    }


def test_files_conversation_scope_fails_closed_when_retrieval_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unavailable(_db, **_kwargs):
        raise FileSearchUnavailable("active_pair_missing")

    monkeypatch.setattr(
        conversation_scope,
        "query_file_chat_evidence",
        _unavailable,
    )

    context = FilesConversationScopeAdapter().turn_context(
        **_scope_inputs(),
        messages=[{"role": "user", "content": "문서에서 찾아줘"}],
    )

    assert (
        context.direct_response
        == "문서 검색을 현재 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    )
    assert context.prompt is None
    assert context.artifacts == ()


def test_files_follow_up_uses_registered_query_rewrite_workload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_llm: dict[str, object] = {}
    captured_retrieval: dict[str, object] = {}

    def _execute(workload_id, context, _db, **kwargs):
        captured_llm["workload_id"] = workload_id
        captured_llm["context"] = context
        captured_llm.update(kwargs)
        return SimpleNamespace(
            completion=SimpleNamespace(
                structured_output=json.loads('{"query":"접근 권한 관리 기준의 적용 대상"}')
            )
        )

    def _query(_db, **kwargs):
        captured_retrieval.update(kwargs)
        return FileChatEvidenceResult(items=())

    monkeypatch.setattr(conversation_scope, "execute_llm", _execute)
    monkeypatch.setattr(conversation_scope, "query_file_chat_evidence", _query)

    context = FilesConversationScopeAdapter().turn_context(
        **_scope_inputs(),
        messages=[
            {"role": "user", "content": "접근 권한 관리 기준은?"},
            {"role": "assistant", "content": "현재 문서 근거를 요약했습니다."},
            {"role": "user", "content": "그 적용 대상은?"},
        ],
    )

    assert context.direct_response is not None
    assert captured_llm["workload_id"] == "files.rag_query_rewrite"
    workload_context = captured_llm["context"]
    assert workload_context.app_id == "files"
    assert workload_context.principal_kind == "user"
    assert captured_llm["temperature"] == 0
    assert captured_llm["reasoning_effort"] == "none"
    assert captured_llm["conversation_id"] == "conversation-1"
    assert "max_tokens" not in captured_llm
    context_pack = captured_llm["context_pack"]
    assert context_pack.context_strategy == "files_rag_query_rewrite"
    assert context_pack.source_kinds == ("files",)
    assert context_pack.sensitivity_labels == ("internal",)
    assert captured_retrieval["query"] == "접근 권한 관리 기준의 적용 대상"
