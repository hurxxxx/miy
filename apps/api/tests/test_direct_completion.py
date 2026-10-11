from __future__ import annotations

import json
from dataclasses import replace

import httpx2 as httpx
import pytest

from miy_api.core import llm
from miy_api.domains.ai import audit
from miy_api.domains.ai.gateway import (
    AiGatewayPolicyViolation,
    complete_gateway_chat,
    complete_gateway_chat_text,
)
from miy_api.domains.ai.registry import get_ai_capability_registry
from test_ai_gateway import _FakePolicyDb as _FakePolicyDb, _request as _request


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
        "chatbot",
        runtime_adapter_id="direct_completion",
        output_schema=SCHEMA,
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
    with pytest.raises(AiGatewayPolicyViolation, match="unsupported_operation"):
        complete_gateway_chat(
            _request("chatbot", runtime_adapter_id="direct_completion", **{"stream": True}),
            _FakePolicyDb("local"),
        )
    assert len(requests) == len(records) == 1
