from __future__ import annotations

from miy_api.domains.ai.tool_contracts import AgentToolSpec


def _tool_spec(name: str) -> AgentToolSpec:
    return AgentToolSpec(
        name=name,
        description="test tool",
        input_schema={"type": "object", "properties": {}},
    )
