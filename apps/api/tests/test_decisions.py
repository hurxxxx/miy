from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from dev_accounts import dev_login, auth_headers
from mty_api.core.db import get_session_factory
from mty_api.core.llm import LlmPoolConfig
from mty_api.core.llm_errors import LlmProviderError
from mty_api.domains.ai import decisions, decision_adapters, gateway, model_discovery
from mty_api.domains.ai.decision_contracts import (
    ChoiceQuestion,
    ScoreQuestion,
    ProbabilityQuestion,
    DecisionInput,
    DecisionError,
)
from mty_api.domains.ai.gateway import LlmWorkloadContext, execute_llm
from mty_api.domains.ai.registry import get_ai_capability_registry
from mty_api.domains.ai.model_settings_models import (
    AiModelCatalogEntry,
    AiModelProviderConfig,
    AiModelPolicyDefault,
)
from mty_api.domains.ai.model_settings_service import (
    ai_model_registry_digest,
    resolve_ai_model_workload_route,
    AiModelSettingsError,
)
from mty_api.domains.auth.models import User, CompanyAppControl


def request():
    return DecisionInput(
        state={"text": "synthetic shipping delay", "items": [1, True, None]},
        questions={
            "category": ChoiceQuestion(
                instructions="Classify",
                options={"shipping": "delivery issues", "billing": "payment issues"},
            ),
            "severity": ScoreQuestion(
                instructions="Severity", levels=["minor", "major", "critical"]
            ),
            "urgent": ProbabilityQuestion(
                instructions="Urgent?",
                true_description="requires immediate action",
                false_description="can wait",
            ),
        },
    )


def wire():
    return {
        "model": "provider/model-version",
        "id": "synthetic-id",
        "provider": "example",
        "usage": {"input_tokens": 20, "output_tokens": 10, "cost": 0.001},
        "answers": {
            "category": {
                "type": "choice",
                "choice": "shipping",
                "confidence": 0.4,
                "probabilities": {"shipping": 0.7, "billing": 0.3},
            },
            "severity": {
                "type": "score",
                "score": 1.4,
                "confidence": 0.8,
                "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
                "legend": {"0": "minor", "1": "major", "2": "critical"},
            },
            "urgent": {"type": "noul", "noul": 0.7},
        },
    }


def config():
    return LlmPoolConfig(
        pool="external",
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        default_model="configured/model",
        canonical_model="configured/model",
        healthcheck_timeout_seconds=2,
        long_generation_timeout_seconds=30,
    )


def mock_http(monkeypatch, handler):
    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_native_wire_mixed_decisions_and_low_confidence(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        body = json.loads(req.content)
        assert body["questions"]["urgent"]["type"] == "noul"
        assert body["model"] == "configured/model"
        assert "messages" not in body
        return httpx.Response(200, json=wire())

    mock_http(monkeypatch, handler)
    result = decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())
    assert len(seen) == 1
    assert result.answers["category"].confidence == 0.4
    assert result.answers["urgent"].probability == 0.7
    assert result.answers["severity"].score == 1.4
    assert result.usage.cost == 0.001


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x["answers"].pop("urgent"),
        lambda x: x["answers"]["category"].update(choice="other"),
        lambda x: x["answers"]["category"].update(confidence=True),
        lambda x: x["answers"]["category"].update(probabilities={"shipping": 0.7}),
        lambda x: x["answers"]["severity"].update(score=3.0),
        lambda x: x["answers"]["urgent"].update(noul=1.1),
        lambda x: x["answers"]["urgent"].update(noul="0.9"),
        lambda x: x.update(usage={"cost": -1.0}),
    ],
)
def test_malformed_answers_fail_closed(monkeypatch, mutation):
    payload = wire()
    mutation(payload)
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(DecisionError, match="decision_response_invalid"):
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())


@pytest.mark.parametrize("status", [302, 400, 401, 402, 429, 503])
def test_transport_status_has_one_attempt_and_safe_error(monkeypatch, status):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(
            status, text="sensitive-provider-body", headers={"location": "https://other.invalid"}
        )

    mock_http(monkeypatch, handler)
    with pytest.raises(DecisionError, match=f"decision_http_{status}") as error:
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())
    assert len(calls) == 1 and "sensitive" not in str(error.value)


def test_response_limits_timeout_and_unknown_cost(monkeypatch):
    with pytest.raises(ValidationError):
        DecisionInput(state="x" * 262_144, questions=request().questions)
    payload = wire()
    payload.pop("usage")
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    assert (
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request()).usage.cost
        is None
    )


def test_response_size_limit(monkeypatch):
    mock_http(monkeypatch, lambda req: httpx.Response(200, content=b"x" * 262_145))
    with pytest.raises(DecisionError, match="decision_response_too_large"):
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())


def test_timeout_no_retry(monkeypatch):
    def handler(req):
        raise httpx.ReadTimeout("secret response")

    mock_http(monkeypatch, handler)
    with pytest.raises(DecisionError, match="decision_timeout"):
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())


@pytest.fixture
def decision_setup(client):
    session = dev_login(client)
    registry = get_ai_capability_registry()
    registry.register_llm_workload(
        workload_id="test_decision",
        task_kind="test_decision",
        owner_domain="chatbot",
        app_id="chatbot",
        description="Synthetic test",
        execution_kind="decision",
        default_route="external",
        allowed_routes=("external",),
        required_capabilities=("decision",),
        default_runtime_adapter="decision",
        allowed_runtime_adapters=("decision",),
    )
    with get_session_factory()() as db:
        user_id = db.scalar(select(User.id).where(User.email == "admin@mty.local"))
        db.add(
            AiModelProviderConfig(
                provider_id="decision-test",
                provider_kind="openrouter",
                display_name="test",
                route_mode="external",
                credential_kind="none",
                endpoint_url="https://openrouter.ai/api/v1",
                enabled=True,
                version=1,
            )
        )
        db.flush()
        db.add(
            AiModelCatalogEntry(
                id="decision-model",
                provider_id="decision-test",
                model_key="configured/model",
                display_name="test",
                capabilities_json=["decision"],
                enabled=True,
                version=1,
            )
        )
        db.flush()
        db.add(
            AiModelPolicyDefault(
                model_family="decision",
                app_id="",
                route_mode="external",
                provider_id="decision-test",
                model_id="decision-model",
            )
        )
        db.commit()
    yield (
        LlmWorkloadContext(source="tests.decision", actor_user_id=user_id, app_id="chatbot"),
        session,
    )
    registry.llm_workloads.pop("test_decision", None)
    registry.llm_tasks.pop("test_decision", None)


def test_facade_routes_audits_once_and_preserves_generation(client, decision_setup, monkeypatch):
    context, _ = decision_setup
    audit = []
    monkeypatch.setattr(decisions, "log_llm_call", lambda **kwargs: audit.append(kwargs))
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=wire()))
    with get_session_factory()() as db:
        result = decisions.execute_decision("test_decision", context, db, **request().model_dump())
        assert result.metadata.model == "provider/model-version"
        with pytest.raises(LlmProviderError, match="execute_decision"):
            execute_llm(
                "test_decision", context, db, messages=[{"role": "user", "content": "test"}]
            )
    assert len(audit) == 1
    assert audit[0]["execution_kind"] == "decision"
    assert audit[0]["connection_id"] == "decision-test"
    assert audit[0]["requested_model"] == "configured/model"
    assert "synthetic shipping" not in json.dumps(audit)


@pytest.mark.parametrize("change", ["missing", "blocked", "disabled_app"])
def test_execution_owner_and_current_app_admission(client, decision_setup, monkeypatch, change):
    context, _ = decision_setup
    calls = []
    mock_http(monkeypatch, lambda req: calls.append(req))
    with get_session_factory()() as db:
        if change == "missing":
            context = replace(context, actor_user_id=None)
        elif change == "blocked":
            db.get(User, context.actor_user_id).login_blocked = True
            db.flush()
        else:
            control = db.get(CompanyAppControl, "chatbot")
            control.enabled = False
            db.flush()
        with pytest.raises(LlmProviderError, match="access"):
            decisions.execute_decision("test_decision", context, db, **request().model_dump())
    assert calls == []


def test_family_default_api_never_changes_generation_default(client, decision_setup):
    _, session = decision_setup
    with get_session_factory()() as db:
        before = db.get(AiModelProviderConfig, "decision-test").default_model_id
    response = client.put(
        "/api/v1/admin/ai-model-settings/defaults/external",
        headers=auth_headers(session["token"]),
        json={
            "expected_registry_digest": ai_model_registry_digest(),
            "expected_version": 1,
            "model_family": "decision",
            "provider_id": "decision-test",
            "model_id": "decision-model",
        },
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        assert db.get(AiModelProviderConfig, "decision-test").default_model_id == before
        assert (
            resolve_ai_model_workload_route(db, workload_id="test_decision").model_key
            == "configured/model"
        )
        db.delete(db.get(AiModelPolicyDefault, ("decision", "", "external")))
        db.flush()
        with pytest.raises(AiModelSettingsError, match="provider_required"):
            resolve_ai_model_workload_route(db, workload_id="test_decision")


def test_openrouter_discovery_uses_modalities_not_names(monkeypatch):
    calls = []

    def handler(req):
        modality = req.url.params["output_modalities"]
        calls.append(modality)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "example/decision"
                        if modality == "decisions"
                        else "typesafe/jev-router",
                        "architecture": {"output_modalities": [modality]},
                        "supported_parameters": ["tools"],
                    }
                ]
            },
        )

    mock_http(monkeypatch, handler)
    result = model_discovery.discover_provider_models("openrouter", config().base_url, "test", 2)
    assert calls == ["decisions", "text"]
    assert result[0].capabilities == ("decision",)
    assert result[1].capabilities == ("chat", "tool_calling")


def test_masking_shape_rejects_key_number_and_container_changes():
    assert gateway._same_payload_shape({"x": ["text", 1]}, {"x": ["masked", 1]})
    assert not gateway._same_payload_shape({"x": 1}, {"x": "masked"})
    assert not gateway._same_payload_shape({"x": "text"}, {"masked": "text"})
    assert not gateway._same_payload_shape(["text"], [])


@pytest.mark.parametrize("reasoning, supported", [
    ({"mandatory": False}, True), ({"mandatory": True}, False),
    ({}, False), (None, False), ({"mandatory": "false"}, False),
])
def test_discovery_only_proposes_non_reasoning_with_explicit_support(monkeypatch, reasoning, supported):
    def handler(req):
        return httpx.Response(200, json={"data": [] if req.url.params["output_modalities"] == "decisions" else [{
            "id": "example/arbitrary-name", "architecture": {"output_modalities": ["text"]},
            "reasoning": reasoning,
        }]})
    mock_http(monkeypatch, handler)
    result = model_discovery.discover_provider_models("openrouter", config().base_url, "test", 2)
    assert ("non_reasoning" in result[0].capabilities) is supported


def test_security_block_scans_state_and_question_without_provider_call(
    client, decision_setup, monkeypatch
):
    from mty_api.domains.ai.security_policy import AiSecurityPolicyDecision

    context, _ = decision_setup
    scans, audit, calls = [], [], []
    monkeypatch.setattr(gateway, "ai_security_enforcement_enabled", lambda db: True)

    def policy(db, context, texts):
        scans.extend(texts)
        return AiSecurityPolicyDecision(effect="block_external", reason_code="policy_block")

    monkeypatch.setattr(gateway, "evaluate_ai_security_policy", policy)
    monkeypatch.setattr(gateway, "log_llm_call", lambda **kwargs: audit.append(kwargs))
    mock_http(monkeypatch, lambda req: calls.append(req))
    with get_session_factory()() as db, pytest.raises(gateway.AiGatewayPolicyViolation):
        decisions.execute_decision("test_decision", context, db, **request().model_dump())
    assert not calls and len(audit) == 1
    assert "synthetic shipping delay" in scans[0] and "requires immediate action" in scans[0]


@pytest.mark.parametrize("invalid", [False, True])
def test_security_masking_preserves_payload_or_fails_closed(
    client, decision_setup, monkeypatch, invalid
):
    from mty_api.domains.ai.security_policy import AiSecurityPolicyDecision
    from mty_api.domains.ai.masking import ExternalPayloadMaskingResult

    context, _ = decision_setup
    monkeypatch.setattr(gateway, "ai_security_enforcement_enabled", lambda db: True)
    monkeypatch.setattr(
        gateway,
        "evaluate_ai_security_policy",
        lambda *args: AiSecurityPolicyDecision(effect="mask_and_send"),
    )

    def mask(texts, **kwargs):
        text = texts[0].replace("synthetic shipping delay", "[MASKED]")
        if invalid:
            text = text.replace('"items"', '"renamed"')
        return ExternalPayloadMaskingResult(
            allowed=True,
            reason_code="masked",
            mask_applied=True,
            masked_texts=(text,),
            masked_text_count=1,
        )

    monkeypatch.setattr(gateway, "evaluate_external_payload_masking", mask)
    calls = []

    def handler(req):
        calls.append(req)
        assert json.loads(req.content)["state"] == {"text": "[MASKED]", "items": [1, True, None]}
        return httpx.Response(200, json=wire())

    mock_http(monkeypatch, handler)
    with get_session_factory()() as db:
        if invalid:
            with pytest.raises(LlmProviderError, match="masking"):
                decisions.execute_decision("test_decision", context, db, **request().model_dump())
            assert not calls
        else:
            result = decisions.execute_decision(
                "test_decision", context, db, **request().model_dump()
            )
            assert result.security.mask_applied and len(calls) == 1


def test_decision_probe_checks_inventory_without_inference(client, decision_setup, monkeypatch):
    context, session = decision_setup
    calls = []

    def handler(req):
        calls.append(req)
        assert req.method == "GET"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "configured/model", "architecture": {"output_modalities": ["decisions"]}}
                ]
            },
        )

    mock_http(monkeypatch, handler)
    result = client.post(
        "/api/v1/admin/ai-model-settings/connections/decision-test/probe",
        headers=auth_headers(session["token"]),
        json={
            "model_id": "decision-model",
            "expected_version": 1,
            "expected_registry_digest": ai_model_registry_digest(),
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["ready"] and len(calls) == 2


def test_registered_test_adapter_receives_structured_input(client, decision_setup, monkeypatch):
    from mty_api.domains.ai.decision_contracts import DecisionResponse

    context, _ = decision_setup
    seen = []

    class Adapter:
        def validate_endpoint(self, endpoint):
            assert endpoint == "https://openrouter.ai/api/v1"

        def execute(self, config, payload):
            seen.append(payload)
            return DecisionResponse.model_validate(
                {
                    "model": "synthetic/model",
                    "answers": {"p": {"type": "probability", "probability": 0.4}},
                }
            )

    monkeypatch.setitem(decision_adapters._adapters, "openrouter_decisions", Adapter())
    with get_session_factory()() as db:
        result = decisions.execute_decision(
            "test_decision",
            context,
            db,
            state=["synthetic"],
            questions={
                "p": ProbabilityQuestion(
                    instructions="Evaluate", true_description="yes", false_description="no"
                )
            },
        )
    assert len(seen) == 1 and seen[0].state == ["synthetic"]
    assert result.response.usage.cost is None
    assert result.metadata.execution_kind == "decision"


def test_decision_cannot_send_to_custom_host(monkeypatch):
    calls = []
    mock_http(monkeypatch, lambda req: calls.append(req))
    with pytest.raises(DecisionError, match="decision_endpoint_unsupported"):
        decision_adapters.OpenRouterDecisionAdapter().execute(
            replace(config(), base_url="https://other.invalid/api/v1"), request()
        )
    assert calls == []


def test_registry_rejects_decision_tool_runtime_and_capability_mismatch():
    from mty_api.domains.ai.registry import AiCapabilityRegistry

    for extra in (
        {"required_capabilities": ("chat",)},
        {
            "default_runtime_adapter": "chat_completion",
            "allowed_runtime_adapters": ("chat_completion",),
        },
        {"native_tools": ("write",)},
    ):
        kwargs = dict(
            workload_id="test",
            task_kind="test",
            owner_domain="chatbot",
            app_id="chatbot",
            description="test",
            execution_kind="decision",
            required_capabilities=("decision",),
            default_runtime_adapter="decision",
            allowed_runtime_adapters=("decision",),
        )
        kwargs.update(extra)
        with pytest.raises(ValueError):
            AiCapabilityRegistry().register_llm_workload(**kwargs)
