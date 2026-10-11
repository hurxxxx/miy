from __future__ import annotations

from miy_api.domains.ai.runtime.agent_definitions import (
    resolve_agent_definitions,
)


def test_allowed_scope_cannot_widen_enabled_entitlements() -> None:
    resolved = resolve_agent_definitions(
        enabled_app_ids=["chatbot", "meeting"],
        allowed_app_ids=["meeting", "pms"],
    )

    assert "domain.meeting" in resolved.agent_ids
    assert "domain.pms" not in resolved.agent_ids
    assert "pms" not in resolved.runtime_registry.domains
