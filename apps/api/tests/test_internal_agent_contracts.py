from __future__ import annotations

import pytest
from pydantic import ValidationError

from miy_api.domains.ai.internal_agent_contracts import LocalAgentResult, LocalAgentTask


def _task(**overrides) -> LocalAgentTask:
    payload = {
        "agent_id": "domain.docs",
        "objective": "Summarize internal docs safely.",
        "allowed_tool_names": ["docs.search"],
        "context_boundary": "company_current",
        "expected_output": "redacted summary",
    }
    payload.update(overrides)
    return LocalAgentTask(**payload)


def test_local_agent_result_rejects_raw_internal_data() -> None:
    with pytest.raises(ValidationError, match="payload contains forbidden entity types"):
        LocalAgentResult(
            agent_id="domain.pms",
            status="completed",
            redacted_summary="가상고객A TEST-DX-2400 ORD-TEST-001 계약 리스크가 있습니다.",
            coverage={"covered": ["계약"]},
        )


def test_local_agent_task_recursively_rejects_unsafe_tool_arguments() -> None:
    with pytest.raises(ValidationError, match="payload contains forbidden entity types"):
        LocalAgentTask(
            agent_id="domain.rag",
            objective="Find internal evidence and return only a summary.",
            allowed_tool_names=["retrieval.search"],
            tool_arguments={"filters": {"clauses": [{"raw": "ORD-TEST-001"}]}},
            context_boundary="company_current",
            expected_output="redacted summary with gaps",
        )
