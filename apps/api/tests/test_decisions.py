from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from dev_accounts import dev_login
from miy_api.core.db import get_session_factory
from miy_api.core.llm import LlmPoolConfig
from miy_api.core.llm_errors import LlmProviderError
from miy_api.domains.ai import decisions, decision_adapters, gateway
from miy_api.domains.ai.decision_contracts import (
    ChoiceQuestion,
    ScoreQuestion,
    ProbabilityQuestion,
    DecisionInput,
    DecisionError,
)
from miy_api.domains.ai.gateway import LlmWorkloadContext, execute_llm
from miy_api.domains.ai.registry import get_ai_capability_registry
from miy_api.domains.ai.model_settings_models import (
    AiModelCatalogEntry,
    AiModelProviderConfig,
    AiModelPolicyDefault,
)
from miy_api.domains.auth.models import User, CompanyAppControl


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


@pytest.mark.parametrize("mutation", [lambda x: x["answers"].pop("urgent")])
def test_malformed_answers_fail_closed(monkeypatch, mutation):
    payload = wire()
    mutation(payload)
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(DecisionError, match="decision_response_invalid"):
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())


@pytest.mark.parametrize("status", [302])
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


def test_timeout_no_retry(monkeypatch):
    def handler(req):
        raise httpx.ReadTimeout("secret response")

    mock_http(monkeypatch, handler)
    with pytest.raises(DecisionError, match="decision_timeout"):
        decision_adapters.OpenRouterDecisionAdapter().execute(config(), request())


@pytest.fixture
def decision_setup(client, monkeypatch):
    from miy_api.core.settings import get_settings

    monkeypatch.setenv("MIY_LLM_EXTERNAL_ALLOWED_PROVIDERS", "openrouter")
    monkeypatch.setenv("MIY_AI_ALLOWED_EXTERNAL_PROVIDERS", "openrouter")
    get_settings.cache_clear()
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
        user_id = db.scalar(select(User.id).where(User.email == "admin@miy.local"))
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
    get_settings.cache_clear()


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
    with get_session_factory()() as db:
        db.get(CompanyAppControl, "chatbot").enabled = False
        db.flush()
        with pytest.raises(LlmProviderError, match="access"):
            decisions.execute_decision("test_decision", context, db, **request().model_dump())
    assert len(audit) == 1


@pytest.mark.parametrize("invalid", [False, True])
def test_security_masking_preserves_payload_or_fails_closed(
    client, decision_setup, monkeypatch, invalid
):
    from miy_api.domains.ai.security_policy import AiSecurityPolicyDecision
    from miy_api.domains.ai.masking import ExternalPayloadMaskingResult

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
