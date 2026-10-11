from __future__ import annotations

import pytest

from miy_api.domains.ai.registry import (
    AiCapabilityRegistry,
)


def test_registry_rejects_write_tool_without_approval_gate() -> None:
    registry = AiCapabilityRegistry()
    registry.register_discoverability_predicate(
        predicate_id="custom.enabled",
        predicate=lambda principal, entitlements: True,
    )

    with pytest.raises(ValueError, match="must set approval_required=True"):
        registry.register_tool(
            name="custom.write_without_approval",
            description="Unsafe write item",
            owner_domain="custom",
            mode="write",
            handler=lambda db, principal, user, arguments: {"ok": True},
            discoverability_predicate_id="custom.enabled",
            owner_app_id="chatbot",
        )
