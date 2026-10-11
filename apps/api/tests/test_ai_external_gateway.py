from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.core.settings import Settings
from miy_api.domains.ai import external_gateway
from miy_api.domains.ai.external_gateway import (
    AiExternalCapabilityPolicyViolation,
    AiExternalCapabilityRequest,
    execute_external_capability,
)


def _audit_record_without_detected_values(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "detected_values"}


class _FakeSecurityDb:
    def __init__(self, *, enforcement_enabled: bool) -> None:
        self._enforcement_enabled = enforcement_enabled

    def get(self, model: object, *_args, **_kwargs):
        if getattr(model, "__tablename__", "") == "ai_security_data_protection_settings":
            return SimpleNamespace(enforcement_enabled=self._enforcement_enabled)
        return None


def test_execute_external_capability_records_success_without_raw_input(monkeypatch) -> None:
    records: list[dict] = []
    monkeypatch.setattr(
        external_gateway, "log_ai_external_call", lambda **kwargs: records.append(kwargs)
    )
    result = execute_external_capability(
        AiExternalCapabilityRequest(
            source="test.external",
            actor_user_id="user-1",
            principal_id="user-1",
            task_kind="document_summary",
            capability="document_summary",
            provider="openai",
            input_texts=["public launch plan"],
            entity_id="generation-1",
        ),
        lambda execution: execution.sanitized_text(fallback="fallback"),
        settings=Settings(),
        usage={"input_tokens": 3, "output_tokens": 5},
        metadata={"model": "test-model"},
    )
    assert result == "public launch plan"
    assert len(records) == 1
    assert records[0]["status"] == "ok"
    assert records[0]["provider"] == "openai"
    assert records[0]["policy_reason"] == "allowed"
    assert records[0]["input_text_count"] == 1
    assert records[0]["input_char_count"] == len("public launch plan")
    assert records[0]["usage"] == {"input_tokens": 3, "output_tokens": 5}
    assert records[0]["metadata"] == {"model": "test-model"}
    assert "public launch plan" not in str(records[0])
    invoked = False

    def _invoke(_execution):
        nonlocal invoked
        invoked = True
        return "should not run"

    with pytest.raises(AiExternalCapabilityPolicyViolation) as error:
        execute_external_capability(
            AiExternalCapabilityRequest(
                source="test.external",
                actor_user_id="user-1",
                principal_id="user-1",
                task_kind="document_summary",
                capability="document_summary",
                provider="openai",
                input_texts=["internal deployment evidence"],
                source_kinds=("docs",),
                sensitivity_labels=("internal",),
                content_origin="internal_context",
            ),
            _invoke,
            settings=Settings(),
        )
    assert error.value.reason_code == "internal_context_blocked"
    assert invoked is False
    assert records[1]["status"] == "blocked"
    assert records[1]["policy_reason"] == "internal_context_blocked"
    assert records[1]["content_origin"] == "internal_context"
    assert records[1]["source_kinds"] == ["docs"]
    assert records[1]["sensitivity_labels"] == ["internal"]
    assert "internal deployment evidence" not in str(records[1])
