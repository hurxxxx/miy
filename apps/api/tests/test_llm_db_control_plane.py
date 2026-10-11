from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.ai.model_credentials import encrypt_api_key
from miy_api.domains.ai.model_settings_models import (
    AiModelCatalogEntry,
    AiModelPolicyDefault,
    AiModelProviderConfig,
    AiModelRouteOverride,
)
from miy_api.domains.ai.model_settings_service import (
    AiModelSettingsError,
    get_ai_model_settings_snapshot,
    resolve_ai_model_workload_route,
)

_WORKLOAD_ID = "chatbot"
_DB_ENDPOINT = "https://db-anthropic.example.test"
_DB_MODEL_ID = "anthropic-database-selected-model"
_DB_MODEL_KEY = "database-selected-model"
_DB_SECRET = "test-db-anthropic-secret"


def _configure_conflicting_external_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIY_LLM_ANTHROPIC_API_KEY", "test-env-anthropic-secret")
    monkeypatch.setenv("MIY_LLM_ANTHROPIC_BASE_URL", "https://env.example.test")
    monkeypatch.setenv("MIY_LLM_ANTHROPIC_DEFAULT_MODEL", "env-only-model")
    monkeypatch.setenv("MIY_LLM_ANTHROPIC_CANONICAL_MODEL", "env-only-model")
    get_settings.cache_clear()


def _enable_database_anthropic_provider(db) -> str:
    provider = db.get(AiModelProviderConfig, "anthropic")
    if provider is None:
        provider = AiModelProviderConfig(
            provider_id="anthropic",
            enabled=False,
            version=1,
        )
        db.add(provider)
        db.flush()
    model = db.get(AiModelCatalogEntry, _DB_MODEL_ID)
    if model is None:
        model = AiModelCatalogEntry(
            id=_DB_MODEL_ID,
            provider_id="anthropic",
            model_key=_DB_MODEL_KEY,
            display_name="Database selected model",
            capabilities_json=["chat", "tool_calling", "vision"],
            source="manual",
            discovery_status="active",
            enabled=True,
            version=1,
        )
        db.add(model)

    ciphertext = encrypt_api_key(_DB_SECRET)
    provider.enabled = True
    provider.endpoint_url = _DB_ENDPOINT
    provider.api_key_ciphertext = ciphertext
    provider.default_model_id = model.id
    db.merge(
        AiModelPolicyDefault(
            model_family="generation",
            app_id="",
            route_mode="external",
            provider_id="anthropic",
            version=1,
        )
    )
    db.commit()
    return ciphertext


def test_enabled_database_provider_is_the_redacted_external_route_source(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with get_session_factory()() as db:
        db.add(
            AiModelRouteOverride(
                id="test-external-route",
                app_id="chatbot",
                workload_id="chatbot",
                route_mode="external",
            )
        )
        db.commit()
    _configure_conflicting_external_env(monkeypatch)

    with get_session_factory()() as db:
        ciphertext = _enable_database_anthropic_provider(db)

        resolved = resolve_ai_model_workload_route(db, workload_id=_WORKLOAD_ID)
        snapshot = get_ai_model_settings_snapshot(db)

    assert resolved.route == "external"
    assert resolved.provider_id == "anthropic"
    assert resolved.endpoint_url == _DB_ENDPOINT
    assert resolved.model_key == _DB_MODEL_KEY
    assert resolved.model_entry_id == _DB_MODEL_ID
    assert resolved.config_source == "database"
    assert resolved.api_key is not None
    assert resolved.api_key.get_secret_value() == _DB_SECRET
    assert _DB_SECRET not in repr(resolved)
    assert "test-env-anthropic-secret" not in repr(resolved)
    assert "env-only-model" not in repr(resolved)

    serialized = snapshot.model_dump()
    anthropic = next(item for item in serialized["providers"] if item["provider_id"] == "anthropic")
    assert anthropic["has_api_key"] is True
    assert set(anthropic).isdisjoint({"api_key", "api_key_ciphertext"})
    serialized_json = snapshot.model_dump_json()
    assert _DB_SECRET not in serialized_json
    assert ciphertext not in serialized_json

    # The same saved route must stop resolving when its connection is disabled
    # and remain closed after deletion, even with conflicting legacy settings.
    with get_session_factory()() as db:
        provider = db.get(AiModelProviderConfig, "anthropic")
        provider.enabled = False
        db.commit()
        with pytest.raises(AiModelSettingsError) as disabled:
            resolve_ai_model_workload_route(db, workload_id=_WORKLOAD_ID)
        assert disabled.value.code == "admin.ai_model_provider_not_ready"
        # Remove this flow's policy first: its provider FK intentionally restricts
        # connection deletion while a saved policy still selects the connection.
        db.delete(db.get(AiModelPolicyDefault, ("generation", "", "external")))
        db.flush()
        db.execute(
            delete(AiModelCatalogEntry).where(AiModelCatalogEntry.provider_id == "anthropic")
        )
        db.delete(provider)
        db.commit()
        with pytest.raises(AiModelSettingsError) as missing:
            resolve_ai_model_workload_route(db, workload_id=_WORKLOAD_ID)
        assert missing.value.code == "admin.ai_model_provider_required"
        assert "test-env-anthropic-secret" not in repr(missing.value)
        assert "env-only-model" not in repr(missing.value)
