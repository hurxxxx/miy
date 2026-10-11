from __future__ import annotations

from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.ai.model_settings_service import (
    resolve_ai_model_workload_route,
)
from dev_accounts import auth_headers, dev_login


def _admin_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(dev_login(client)["token"])


def test_admin_ai_model_settings_provider_catalog_and_route_lifecycle(
    client: TestClient,
) -> None:
    headers = _admin_headers(client)
    initial = client.get(
        "/api/v1/admin/ai-model-settings",
        headers=headers,
    ).json()
    digest = initial["registry_digest"]
    local = next(item for item in initial["providers"] if item["provider_id"] == "local")

    create_model = client.post(
        "/api/v1/admin/ai-model-settings/models",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "provider_id": "local",
            "model_key": "qwen-local",
            "display_name": "Qwen Local",
            "capabilities": ["chat", "tool_calling"],
            "enabled": True,
        },
    )
    assert create_model.status_code == 201, create_model.text
    snapshot = create_model.json()
    local_model = next(
        item
        for item in snapshot["models"]
        if item["provider_id"] == "local" and item["model_key"] == "qwen-local"
    )
    local = next(item for item in snapshot["providers"] if item["provider_id"] == "local")

    update_provider = client.put(
        "/api/v1/admin/ai-model-settings/providers/local",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "expected_version": local["version"],
            "enabled": True,
            "endpoint_url": "http://127.0.0.1:8001/v1",
            "default_model_id": local_model["id"],
        },
    )
    assert update_provider.status_code == 200, update_provider.text

    inherited_default = next(
        (
            item
            for item in update_provider.json()["defaults"]
            if item["app_id"] == "" and item["route_mode"] == "local"
        ),
        None,
    )
    set_default = client.put(
        "/api/v1/admin/ai-model-settings/defaults/local",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "expected_version": inherited_default["version"] if inherited_default else 0,
            "provider_id": "local",
        },
    )
    assert set_default.status_code == 200, set_default.text

    route_payload = {
        "expected_registry_digest": digest,
        "expected_version": None,
        "route_mode": "local",
        "provider_id": "local",
        "model_ids": {"default": local_model["id"]},
        "local_max_output_tokens": 24_576,
        "external_max_output_tokens": 49_152,
    }
    route = client.put(
        "/api/v1/admin/ai-model-settings/workloads/chatbot/route",
        headers=headers,
        json=route_payload,
    )
    assert route.status_code == 200, route.text
    workload = next(item for item in route.json()["workloads"] if item["workload_id"] == "chatbot")
    assert workload["override"]["route_mode"] == "local"
    assert workload["override"]["model_ids"] == {"default": local_model["id"]}
    assert workload["override"]["local_max_output_tokens"] == 24_576
    assert workload["override"]["external_max_output_tokens"] == 49_152
    assert workload["local_max_output_tokens"] == 24_576
    assert workload["external_max_output_tokens"] == 49_152

    stale = client.put(
        "/api/v1/admin/ai-model-settings/workloads/chatbot/route",
        headers=headers,
        json=route_payload,
    )
    assert stale.status_code == 409

    reset = client.delete(
        "/api/v1/admin/ai-model-settings/workloads/chatbot/route",
        headers=headers,
        params={
            "expected_registry_digest": digest,
            "expected_version": workload["override"]["version"],
        },
    )
    assert reset.status_code == 200, reset.text
    reset_workload = next(
        item for item in reset.json()["workloads"] if item["workload_id"] == "chatbot"
    )
    assert reset_workload["override"] is None
    assert reset_workload["effective_route"] == reset_workload["default_route"]
    assert reset_workload["local_max_output_tokens"] == 32_768
    assert reset_workload["external_max_output_tokens"] == 65_536


def test_admin_ai_model_settings_external_route_and_secret_redaction(
    client: TestClient,
) -> None:
    headers = _admin_headers(client)
    initial = client.get(
        "/api/v1/admin/ai-model-settings",
        headers=headers,
    ).json()
    digest = initial["registry_digest"]
    anthropic = next(item for item in initial["providers"] if item["provider_id"] == "anthropic")
    model_response = client.post(
        "/api/v1/admin/ai-model-settings/models",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "provider_id": "anthropic",
            "model_key": "administrator-selected-model",
            "display_name": "Administrator selected model",
            "capabilities": ["chat", "tool_calling", "vision"],
            "enabled": True,
        },
    )
    assert model_response.status_code == 201, model_response.text
    sonnet = next(
        item
        for item in model_response.json()["models"]
        if item["provider_id"] == "anthropic"
        and item["model_key"] == "administrator-selected-model"
    )
    anthropic = next(
        item for item in model_response.json()["providers"] if item["provider_id"] == "anthropic"
    )

    provider_response = client.put(
        "/api/v1/admin/ai-model-settings/providers/anthropic",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "expected_version": anthropic["version"],
            "enabled": True,
            "endpoint_url": None,
            "default_model_id": sonnet["id"],
            "api_key": "test-anthropic-secret",
        },
    )
    assert provider_response.status_code == 200, provider_response.text
    response_text = provider_response.text
    assert "test-anthropic-secret" not in response_text
    updated_anthropic = next(
        item for item in provider_response.json()["providers"] if item["provider_id"] == "anthropic"
    )
    assert updated_anthropic["has_api_key"] is True

    route = client.put(
        "/api/v1/admin/ai-model-settings/workloads/chatbot/route",
        headers=headers,
        json={
            "expected_registry_digest": digest,
            "expected_version": None,
            "route_mode": "external",
            "provider_id": "anthropic",
            "model_ids": {"default": sonnet["id"]},
            "local_max_output_tokens": None,
            "external_max_output_tokens": 61_440,
        },
    )
    assert route.status_code == 200, route.text
    workload = next(item for item in route.json()["workloads"] if item["workload_id"] == "chatbot")
    assert workload["effective_route"] == "external"
    assert workload["override"]["provider_id"] == "anthropic"
    assert workload["ready"] is True
    assert workload["resolved_routes"][0]["provider_id"] == "anthropic"
    assert workload["resolved_routes"][0]["model_key"] == "administrator-selected-model"
    assert workload["resolved_routes"][0]["max_output_tokens"] == 61_440

    with get_session_factory()() as db:
        resolved = resolve_ai_model_workload_route(db, workload_id="chatbot")
    assert resolved.route == "external"
    assert resolved.provider_id == "anthropic"
    assert resolved.model_key == "administrator-selected-model"
    assert resolved.route_source == "override"
    assert resolved.max_output_tokens == 61_440
    assert resolved.config_source in {"database", "database_with_legacy_env"}
    assert resolved.api_key is not None
    assert resolved.api_key.get_secret_value() == "test-anthropic-secret"
    assert "test-anthropic-secret" not in repr(resolved)


def test_admin_ai_model_settings_rejects_stale_registry_digest(client: TestClient) -> None:
    headers = _admin_headers(client)
    initial = client.get(
        "/api/v1/admin/ai-model-settings",
        headers=headers,
    ).json()
    local = next(item for item in initial["providers"] if item["provider_id"] == "local")

    response = client.put(
        "/api/v1/admin/ai-model-settings/providers/local",
        headers=headers,
        json={
            "expected_registry_digest": "0" * 64,
            "expected_version": local["version"],
            "enabled": True,
            "endpoint_url": "http://127.0.0.1:8001/v1",
            "default_model_id": None,
        },
    )

    assert response.status_code == 409
    assert response.headers["X-MIY-Error-Code"] == "admin.ai_model_registry_changed"
