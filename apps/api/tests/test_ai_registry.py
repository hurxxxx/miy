from __future__ import annotations

import pytest

from miy_api.core.settings import get_settings
from miy_api.domains.ai.registry import (
    AiCapabilityRegistry,
    reset_ai_capability_registry,
)


def _reset_settings_and_registry() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    reset_ai_capability_registry()


def test_llm_workload_registration_fails_closed_and_rejects_duplicate_app_task() -> None:
    registry = AiCapabilityRegistry()
    registry.register_llm_workload(
        workload_id="example.summarize",
        task_kind="example_summary",
        owner_domain="example",
        app_id="example",
        description="Example summary",
    )

    with pytest.raises(LookupError, match="Unknown LLM workload"):
        registry.resolve_llm_workload("example.unknown")

    with pytest.raises(ValueError, match="Duplicate LLM workload app/task"):
        registry.register_llm_workload(
            workload_id="example.summarize-again",
            task_kind="example_summary",
            owner_domain="example",
            app_id="example",
            description="Duplicate example summary",
        )
