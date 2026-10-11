from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from miy_api.core.llm import LlmPoolConfig
from miy_api.domains.ai import masking as masking_module
from miy_api.domains.ai.models import (
    AiSecurityDataProtectionSettings,
)
from miy_api.domains.ai.privacy_filter import PrivacyFilterDetection
from miy_api.domains.ai.security_policy import (
    DATA_PROTECTION_SETTINGS_ID,
)
from miy_api.domains.auth.security import new_id


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _external_test_llm_config() -> LlmPoolConfig:
    return LlmPoolConfig(
        pool="external",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="test-key",
        default_model="claude-test",
        canonical_model="claude-test",
        healthcheck_timeout_seconds=1.0,
        long_generation_timeout_seconds=30.0,
    )


def _bootstrap_admin_session(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "full_name": "miy Admin",
            "email": "admin@miy.local",
            "password": "supersecret123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch_privacy_filter_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        masking_module,
        "detect_privacy_filter_spans",
        lambda *_args, **_kwargs: PrivacyFilterDetection(
            status="ok",
            enabled=True,
            used=True,
        ),
    )


def _audit_record_without_detected_values(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "detected_values"}


def _enable_ai_security_enforcement(
    client: TestClient,
    headers: dict[str, str],
) -> dict:
    response = client.patch(
        "/api/v1/admin/ai-security/enforcement",
        headers=headers,
        json={"enforcement_enabled": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _put_ai_security_data_protection(
    client: TestClient,
    headers: dict[str, str],
    *,
    external_app_actions: dict[str, dict[str, str]] | None = None,
    blocker_actions: dict[str, str] | None = None,
) -> dict:
    _enable_ai_security_enforcement(client, headers)
    response = client.put(
        "/api/v1/admin/ai-security/data-protection",
        headers=headers,
        json={
            "custom_block_terms": [],
            "blocker_actions": blocker_actions or {},
            "external_app_actions": external_app_actions or {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _simulate_ai_security(
    client: TestClient,
    headers: dict[str, str],
    **payload,
) -> dict:
    response = client.post(
        "/api/v1/admin/ai-security/simulate",
        headers=headers,
        json={
            "app_id": "chatbot",
            "task_kind": "web_search",
            "capability": "web_search",
            "provider": "anthropic",
            "content_origin": "user_prompt",
            **payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_or_create_data_protection_settings(db) -> AiSecurityDataProtectionSettings:
    settings = db.get(AiSecurityDataProtectionSettings, DATA_PROTECTION_SETTINGS_ID)
    if settings is not None:
        return settings
    settings = AiSecurityDataProtectionSettings(
        id=DATA_PROTECTION_SETTINGS_ID,
        enforcement_enabled=True,
        custom_block_terms_json=[],
    )
    db.add(settings)
    return settings


def test_admin_ai_security_policy_crud_simulation_and_audit_payload(
    client: TestClient,
) -> None:
    admin = _bootstrap_admin_session(client)
    headers = _auth_headers(admin["token"])

    term = f"Falcon-{new_id()}"
    summary_response = client.get("/api/v1/admin/ai-security/summary", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    assert summary["data_protection"]["enforcement_enabled"] is False
    assert "task_policies" not in summary
    assert "task_policy_apps" not in summary
    assert client.get("/api/v1/admin/ai-security/task-policies", headers=headers).status_code == 404
    external_candidate_ids = {item["app_id"] for item in summary["external_app_candidates"]}
    assert not external_candidate_ids
    assert summary["condition_options"]["apps"]
    assert "chatbot" in {
        option["value"] for option in summary["condition_options"]["external_apps"]
    }
    assert any(option["value"] == "llm" for option in summary["condition_options"]["capabilities"])
    assert any(
        option["value"] == "anthropic" for option in summary["condition_options"]["providers"]
    )
    assert any(
        option["value"] == "internal_context"
        for option in summary["condition_options"]["content_origins"]
    )
    _enable_ai_security_enforcement(client, headers)

    data_response = client.put(
        "/api/v1/admin/ai-security/data-protection",
        headers=headers,
        json={
            "custom_block_terms": [term, term],
            "blocker_actions": {
                "credential": "mask_and_send",
                "pii": "mask_and_send",
            },
            "external_app_actions": {
                "chatbot": {
                    "credential": "mask_and_send",
                    "pii": "mask_and_send",
                },
            },
        },
    )
    assert data_response.status_code == 200, data_response.text
    data_protection = data_response.json()
    assert data_protection["custom_block_terms"] == [term]
    assert data_protection["blocker_actions"]["pii"] == "mask_and_send"
    assert "credential" not in data_protection["blocker_actions"]
    assert data_protection["external_app_actions"]["chatbot"]["pii"] == "mask_and_send"
    assert "credential" not in data_protection["external_app_actions"]["chatbot"]

    rule_response = client.post(
        "/api/v1/admin/ai-security/rules",
        headers=headers,
        json={
            "name": "Company web search deny",
            "description": "deny external search for this company",
            "enabled": True,
            "task_kind": "web_search",
            "capability": "web_search",
            "provider": "anthropic",
            "effect": "block_external",
            "custom_block_terms": [],
        },
    )
    assert rule_response.status_code == 201, rule_response.text
    rule = rule_response.json()
    assert "workspace_id" not in rule
    assert rule["effect"] == "block_external"
    assert rule["task_kinds"] == ["web_search"]

    exception_response = client.post(
        "/api/v1/admin/ai-security/exceptions",
        headers=headers,
        json={
            "name": "Approved internal context export",
            "description": "approved scoped exception",
            "enabled": True,
            "task_kind": "mail_reply_draft",
            "capability": "llm",
            "allowed_blocker_types": ["internal_context"],
            "reason": "Approved for a short-lived external summarization workflow.",
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        },
    )
    assert exception_response.status_code == 201, exception_response.text
    exception = exception_response.json()
    assert exception["allowed_blocker_types"] == ["internal_context"]
    assert exception["task_kinds"] == ["mail_reply_draft"]

    exception_simulation_response = client.post(
        "/api/v1/admin/ai-security/simulate",
        headers=headers,
        json={
            "task_kind": "mail_reply_draft",
            "capability": "llm",
            "content_origin": "internal_context",
            "sample_text": "internal context without hard blockers",
        },
    )
    assert exception_simulation_response.status_code == 200
    exception_simulation = exception_simulation_response.json()
    assert exception_simulation["route_action"] == "external_exception"
    assert exception_simulation["external_transfer_exception_id"] == exception["id"]
    assert exception_simulation["hard_blocker_types"] == []
    hard_block = client.post(
        "/api/v1/admin/ai-security/simulate",
        headers=headers,
        json={
            "task_kind": "mail_reply_draft",
            "capability": "llm",
            "content_origin": "internal_context",
            "sample_text": "internal api_key=sk-secretsecretsecretsecret evidence",
        },
    )
    assert hard_block.status_code == 200
    assert hard_block.json()["route_action"] == "blocked"
    assert "credential" in hard_block.json()["hard_blocker_types"]

    simulation_response = client.post(
        "/api/v1/admin/ai-security/simulate",
        headers=headers,
        json={
            "task_kind": "web_search",
            "capability": "web_search",
            "provider": "anthropic",
            "content_origin": "user_prompt",
            "sample_text": "public question",
        },
    )
    assert simulation_response.status_code == 200, simulation_response.text
    simulation = simulation_response.json()
    assert simulation["route_action"] == "blocked"
    assert simulation["rule_id"] == rule["id"]

    term_simulation_response = client.post(
        "/api/v1/admin/ai-security/simulate",
        headers=headers,
        json={
            "task_kind": "web_search",
            "capability": "web_search",
            "provider": "anthropic",
            "content_origin": "user_prompt",
            "sample_text": f"Please summarize {term}",
        },
    )
    assert term_simulation_response.status_code == 200, term_simulation_response.text
    term_simulation = term_simulation_response.json()
    assert term_simulation["route_action"] == "blocked"
    assert term_simulation["custom_block_term_count"] == 1
    assert "custom_block_term" in term_simulation["blocked_entity_types"]

    audit_response = client.get(
        "/api/v1/admin/audit-logs?q=ai_security&limit=20",
        headers=headers,
    )
    assert audit_response.status_code == 200, audit_response.text
    audit_payload = str([item["payload"] for item in audit_response.json()["items"]])
    assert "custom_block_term_count" in audit_payload
    assert term not in audit_payload
