from __future__ import annotations

from pathlib import Path

import pytest

from miy_api.core.settings import Settings
from miy_api.domains.ai.runtime.external_egress import (
    evaluate_external_egress,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_runtime"
SETTING_ALIASES = {
    "ai_external_llm_enabled": "MIY_AI_EXTERNAL_LLM_ENABLED",
    "ai_external_planning_enabled": "MIY_AI_EXTERNAL_PLANNING_ENABLED",
    "ai_external_reasoning_enabled": "MIY_AI_EXTERNAL_REASONING_ENABLED",
    "ai_external_quality_review_enabled": "MIY_AI_EXTERNAL_QUALITY_REVIEW_ENABLED",
    "ai_external_search_enabled": "MIY_AI_EXTERNAL_SEARCH_ENABLED",
    "ai_external_planner_execution_enabled": "MIY_AI_EXTERNAL_PLANNER_EXECUTION_ENABLED",
    "ai_external_planner_execution_adapter": "MIY_AI_EXTERNAL_PLANNER_EXECUTION_ADAPTER",
    "ai_external_search_execution_enabled": "MIY_AI_EXTERNAL_SEARCH_EXECUTION_ENABLED",
    "ai_external_search_execution_adapter": "MIY_AI_EXTERNAL_SEARCH_EXECUTION_ADAPTER",
    "ai_allowed_external_providers": "MIY_AI_ALLOWED_EXTERNAL_PROVIDERS",
    "ai_default_external_search_provider": "MIY_AI_DEFAULT_EXTERNAL_SEARCH_PROVIDER",
}


@pytest.fixture(autouse=True)
def _isolated_policy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for alias in SETTING_ALIASES.values():
        monkeypatch.delenv(alias, raising=False)


def _settings(**overrides):
    aliased_overrides = {SETTING_ALIASES.get(key, key): value for key, value in overrides.items()}
    return Settings(
        _env_file=None,
        postgres_dsn="postgresql+psycopg://miy_test:miy_test@127.0.0.1:5432/miy_test",
        **aliased_overrides,
    )


def test_external_search_respects_user_no_external_search_directive() -> None:
    decision = evaluate_external_egress(
        capability="search",
        provider="openai",
        text="외부 검색 없이 EU CE 인증 기준을 회의록 근거로 정리해줘.",
        settings=_settings(ai_external_search_enabled=True),
    )

    assert decision.allow_external is False
    assert decision.reason == "user_no_external_search"
    assert decision.sanitized_query == ""
