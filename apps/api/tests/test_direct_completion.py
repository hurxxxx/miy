from __future__ import annotations

import json
from dataclasses import replace

import httpx2 as httpx
import pytest

from miy_api.core import llm
from miy_api.core.llm_errors import LlmProviderError
from miy_api.domains.ai import audit
from miy_api.domains.ai.gateway import AiGatewayPolicyViolation, complete_gateway_chat, complete_gateway_chat_text
from miy_api.domains.ai.registry import AiCapabilityRegistry, get_ai_capability_registry
from test_ai_gateway import _FakePolicyDb, _request


SCHEMA = {
    "type": "object",
    "properties": {"choice": {"enum": ["left", "right"]}},
    "required": ["choice"],
    "additionalProperties": False,
}


@pytest.fixture
def direct_gateway(monkeypatch):
    registry = get_ai_capability_registry()
    workload = registry.resolve_llm_workload("chatbot")
    monkeypatch.setitem(
        registry.llm_workloads,
        "chatbot",
        replace(workload, allowed_runtime_adapters=("chat_completion", "direct_completion")),
    )
    records, requests = [], []
    monkeypatch.setattr(audit, "log_llm_call", lambda **kwargs: records.append(kwargs))
    request = _request(
        "chatbot", runtime_adapter_id="direct_completion", output_schema=SCHEMA,
        reasoning_effort="low",
    )
    # Exercise the real official SDK, JSON payload and redirect/retry settings.
    request = replace(
        request, workload_config=replace(request.workload_config, provider="openrouter")
    )

    def run(response, *, text_result=False, **overrides):
        def handle(incoming):
            requests.append(incoming)
            if isinstance(response, Exception):
                raise response
            return response

        factory = llm.DefaultHttpxClient
        client = factory(transport=httpx.MockTransport(handle), follow_redirects=False)
        monkeypatch.setattr(llm, "DefaultHttpxClient", lambda **kwargs: client)
        try:
            complete = complete_gateway_chat_text if text_result else complete_gateway_chat
            return complete(replace(request, **overrides), _FakePolicyDb("local"))
        finally:
            assert client.is_closed

    return run, records, requests


def completion(content='{"choice":"left"}', *, reason="stop", **message):
    return httpx.Response(
        200,
        json={
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "actual-test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content, **message},
                    "finish_reason": reason,
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_direct_sdk_schema_and_single_audited_call(direct_gateway):
    run, records, requests = direct_gateway
    result = run(completion())
    assert result.response["structured_output"] == {"choice": "left"}
    assert len(requests) == len(records) == 1
    wire = json.loads(requests[0].content)
    assert wire["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "workload_result", "strict": True, "schema": SCHEMA},
    }
    assert wire["provider"] == {"require_parameters": True, "allow_fallbacks": False}
    assert wire["reasoning"] == {"effort": "low"}
    assert wire["max_tokens"] == 32768
    assert "tools" not in wire
    assert records[0]["runtime_adapter_id"] == "direct_completion"
    assert records[0]["model"] == "actual-test-model"
    assert records[0]["requested_model"] == "test-model"
    assert records[0]["usage"]["total_tokens"] == 15
    assert records[0]["status"] == "ok"


def test_direct_text_only_completion_uses_same_transport(direct_gateway):
    run, records, requests = direct_gateway
    result = run(completion("plain text"), output_schema=None)
    assert result.response["choices"][0]["message"]["content"] == "plain text"
    assert "response_format" not in json.loads(requests[0].content)
    assert records[0]["status"] == "ok"


def test_non_reasoning_workload_sends_none_and_blocks_manual_override(monkeypatch, direct_gateway):
    registry = get_ai_capability_registry()
    workload = registry.get_llm_workload("chatbot")
    monkeypatch.setitem(registry.llm_workloads, "chatbot", replace(workload, required_capabilities=("chat", "non_reasoning")))
    run, records, requests = direct_gateway
    run(completion(), reasoning_effort="none")
    assert json.loads(requests[0].content)["reasoning"] == {"effort": "none"}
    with pytest.raises(AiGatewayPolicyViolation) as error:
        run(completion(), reasoning_effort="high")
    assert error.value.reason_code == "reasoning_not_allowed"
    assert len(requests) == 1


@pytest.mark.parametrize("response, reason", [
    (httpx.Response(429, json={"error": {"message": "private provider body"}}), "rate_limited"),
    (completion(reason="length"), "output_limit"),
    (httpx.ReadTimeout("private provider body"), "timeout"),
])
def test_high_level_completion_preserves_safe_failure_reason(direct_gateway, response, reason):
    run, records, requests = direct_gateway
    with pytest.raises(LlmProviderError) as error:
        run(response, text_result=True)
    assert error.value.reason_code == reason
    assert "private" not in str(error.value)
    assert len(requests) == len(records) == 1


@pytest.mark.parametrize(
    "response",
    [
        completion("not JSON"),
        completion('{"choice":"invalid"}'),
        completion('{"choice":"left","extra":1}'),
        completion("{}"),
        completion('{"choice":"left","choice":"right"}'),
        completion('{"choice":NaN}'),
        completion(reason="length"),
        completion(refusal="refused"),
        completion(""),
        httpx.Response(429, json={"error": {"message": "sensitive provider echo"}}),
        httpx.Response(500, json={"error": {"message": "sensitive provider echo"}}),
        httpx.Response(307, headers={"location": "https://redirect.invalid/"}),
        httpx.ReadTimeout("sensitive provider echo"),
    ],
)
def test_direct_rejects_invalid_responses_without_retry_fallback_or_raw_audit(
    direct_gateway, response
):
    run, records, requests = direct_gateway
    with pytest.raises(LlmProviderError, match="Direct completion"):
        run(response)
    assert len(requests) == len(records) == 1
    assert records[0]["status"] == "error"
    assert "sensitive" not in records[0]["error"]
    if isinstance(response, httpx.Response) and response.status_code == 200:
        if response.json()["choices"][0]["finish_reason"] == "length":
            assert "output token limit" in records[0]["error"]


def test_unregistered_direct_runtime_is_rejected():
    with pytest.raises(AiGatewayPolicyViolation, match="runtime_adapter_not_allowed"):
        complete_gateway_chat(
            _request("chatbot", runtime_adapter_id="direct_completion"), _FakePolicyDb("local")
        )


@pytest.mark.parametrize("operation", [{"stream": True}, {"tools": []}, {"tool_choice": "auto"}])
def test_direct_disallows_agent_operations(direct_gateway, operation):
    with pytest.raises(AiGatewayPolicyViolation, match="unsupported_operation"):
        complete_gateway_chat(
            _request("chatbot", runtime_adapter_id="direct_completion", **operation),
            _FakePolicyDb("local"),
        )


@pytest.mark.parametrize("extra", [{"execution_kind": "agent"}, {"native_tools": ("web_search",)}])
def test_registration_limits_direct_to_tool_free_chat(extra):
    with pytest.raises(ValueError, match="Direct completion"):
        AiCapabilityRegistry().register_llm_workload(
            workload_id="test.direct",
            task_kind="test_direct",
            owner_domain="test",
            app_id="test",
            description="Test",
            default_runtime_adapter="direct_completion",
            allowed_runtime_adapters=("direct_completion",),
            **extra,
        )


@pytest.mark.parametrize("schema", [{"$ref": "https://schema.invalid/a"}, {"type": "invalid"}])
def test_invalid_schema_never_calls_provider(monkeypatch, direct_gateway, schema):
    run, records, requests = direct_gateway
    # Replace the schema object already held by the admitted request.
    for key, value in schema.items():
        monkeypatch.setitem(SCHEMA, key, value)
    with pytest.raises(LlmProviderError):
        run(completion())
    assert requests == []
    assert len(records) == 1
