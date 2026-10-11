from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from miy_api.core.llm import (
    LlmPoolConfig,
    LlmTaskContext,
    PolicyDecision,
    ResolvedLlmExecution,
)
from miy_api.core.llm_adapters import StreamChunk
from miy_api.core.llm_errors import LlmProviderError
from miy_api.core.principal import user_principal
from miy_api.domains.ai import agent as agent_module
from miy_api.domains.ai.events import EnvelopeEncoder
from miy_api.domains.ai.tool_contracts import AgentToolSpec

pytestmark = pytest.mark.anyio


def _ctx() -> LlmTaskContext:
    return LlmTaskContext(
        source="test.agent",
        actor_user_id="user-1",
        principal_kind="user",
        principal_id="user-1",
        task_kind="chatbot",
        app_id="chatbot",
        workload_id="chatbot",
    )


def _execution() -> ResolvedLlmExecution:
    decision = PolicyDecision(
        policy="local_only",
        chosen_pool="local",
        reason="policy_local_only",
    )
    config = LlmPoolConfig(
        pool="local",
        provider="mlx-lm",
        base_url="http://127.0.0.1:8080/v1",
        api_key="mlx",
        default_model="mlx-community/model",
        canonical_model="local/current-moe-test-profile",
        healthcheck_timeout_seconds=5,
        long_generation_timeout_seconds=30,
        enabled=True,
    )
    return ResolvedLlmExecution(
        pool="local",
        decision=decision,
        config=config,
        chosen_model="mlx-community/model",
        resolved_max_tokens=1000,
        resolved_reasoning_effort="none",
    )


def _snapshot_model_meta(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "model": "mlx-community/model",
        "provider": "mlx-lm",
        "policy": "local_only",
        "chosen_pool": "local",
        "max_output_tokens": 1000,
        "reasoning_effort": "none",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "snapshot_values,current_values",
    [
        ({"model": "different-model"}, {}),
        ({}, {"workload_route": "external"}),
        ({}, {"workload_config": None}),
    ],
)
def test_execution_from_snapshot_fails_closed_when_registered_identity_changed(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_values: dict[str, Any],
    current_values: dict[str, Any],
) -> None:
    request_values = {
        "workload_route": "local",
        "workload_config": _execution().config,
        "requested_model": "mlx-community/model",
        "max_tokens": 640,
    }
    request_values.update(current_values)
    monkeypatch.setattr(
        agent_module,
        "build_llm_workload_request",
        lambda *args, **kwargs: SimpleNamespace(**request_values),
    )

    with pytest.raises(
        LlmProviderError,
        match="ai.agent_resume_model_configuration_changed",
    ):
        agent_module._execution_from_snapshot(
            SimpleNamespace(model_meta=_snapshot_model_meta(**snapshot_values)),
            context=_ctx(),
            db=object(),
        )


async def _collect_events(
    monkeypatch: pytest.MonkeyPatch,
    streams: list[list[StreamChunk]],
    *,
    max_turns: int = 4,
    captured_stream_kwargs: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    tool_specs: list[AgentToolSpec] | None = None,
):
    stream_iter = iter(streams)

    async def fake_complete_gateway_chat_stream(gateway_execution: Any, _db: Any):
        if captured_stream_kwargs is not None:
            request = gateway_execution.request
            captured_stream_kwargs.append(
                {
                    "messages": gateway_execution.messages,
                    "temperature": request.temperature,
                    "stream_reasoning": request.stream_reasoning,
                    "tools": request.tools,
                    "tool_choice": request.tool_choice,
                    "parallel_tool_calls": request.parallel_tool_calls,
                    "agent_run_id": request.agent_run_id,
                    "conversation_id": request.conversation_id,
                }
            )
        for chunk in next(stream_iter):
            yield chunk, gateway_execution.decision, gateway_execution.llm_execution.config

    monkeypatch.setattr(
        agent_module,
        "complete_resolved_gateway_chat_stream",
        fake_complete_gateway_chat_stream,
    )

    return [
        event
        async for event in agent_module.run_agent_turn_stream(
            context=_ctx(),
            execution=_execution(),
            db=SimpleNamespace(commit=lambda: None),
            principal=user_principal(
                user_id="user-1",
                source="test.agent",
            ),
            user=SimpleNamespace(id="user-1"),
            messages=messages or [{"role": "user", "content": "hi"}],
            temperature=0.2,
            stream_reasoning=True,
            encoder=EnvelopeEncoder(),
            max_turns=max_turns,
            max_tool_calls=8,
            max_consecutive_tool_errors=3,
            agent_run_id="agent-run-1",
            tool_specs=tool_specs
            or [
                AgentToolSpec(
                    name="pms.search_tasks",
                    description="Search issues",
                    input_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            ],
            bound_conversation=SimpleNamespace(id="conversation-1"),
        )
    ]


async def test_run_agent_turn_stream_blocks_write_success_without_write_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _collect_events(
        monkeypatch,
        [
            [
                StreamChunk(kind="content", text="PMS 이슈가 성공적으로 변경되었습니다."),
                StreamChunk(kind="done", finish_reason="stop"),
            ]
        ],
        messages=[{"role": "user", "content": "PMS 이슈 상태를 in progress로 변경해줘"}],
        tool_specs=[
            AgentToolSpec(
                name="pms.update_task",
                description="Update issue",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        ],
    )

    assert [event.type for event in events] == ["content_delta", "done"]
    assert "write tool 실행 결과가 없습니다" in events[0].data.text
    assert "성공적으로 변경" not in events[0].data.text
    assert events[-1].data.finish_reason == "stop"
