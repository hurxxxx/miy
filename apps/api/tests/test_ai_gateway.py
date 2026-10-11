from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from miy_api.core.llm import LlmPoolConfig
from miy_api.core.settings import get_settings
from miy_api.domains.ai import gateway as gateway_module
from miy_api.domains.ai import masking as masking_module
from miy_api.domains.ai.gateway import (
    AiGatewayContextPack,
    AiGatewayPolicyViolation,
    AiGatewayRequest,
    LlmWorkloadContext,
    complete_gateway_chat,
    execute_llm,
    resolve_gateway_execution,
)
from miy_api.domains.ai.privacy_filter import PrivacyFilterDetection, PrivacyFilterSpan
from miy_api.domains.ai.registry import (
    get_ai_capability_registry,
)
from miy_api.domains.ai.security_policy import (
    POLICY_MASK_AND_SEND_REASON,
    AiSecurityPolicyDecision,
)


class _FakeSecuritySettings:
    def __init__(self, enabled: bool) -> None:
        self.enforcement_enabled = enabled
        self.enforcement_disabled_reason = ""
        self.custom_block_terms_json: list[str] = []
        self.blocker_actions_json: dict[str, str] = {}
        self.external_app_actions_json: dict[str, dict[str, str]] = {}


class _FakePolicyDb:
    def __init__(self, policy: str | None, *, ai_security_enabled: bool = True) -> None:
        self._policy = policy
        self._ai_security_enabled = ai_security_enabled

    def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        policy = self._policy

        class _Result:
            def scalar_one_or_none(self) -> str | None:
                return policy

        return _Result()

    def get(self, model: object, *_args: Any, **_kwargs: Any) -> Any:
        if getattr(model, "__tablename__", "") == "ai_security_data_protection_settings":
            return _FakeSecuritySettings(self._ai_security_enabled)
        return None

    def scalar(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def scalars(self, *_args: Any, **_kwargs: Any) -> Any:
        class _Result:
            def all(self) -> list[Any]:
                return []

        return _Result()


def _request(task_kind: str, **overrides: Any) -> AiGatewayRequest:
    registry = get_ai_capability_registry()
    workload = registry.get_llm_workload(task_kind)
    if workload is None:
        workload = registry.resolve_llm_workload_for_task(
            app_id="files",
            task_kind=task_kind,
        )
    route = overrides.pop(
        "workload_route",
        "external" if task_kind == "files_grounded_chat" else "local",
    )
    config = LlmPoolConfig(
        pool=route,
        provider="anthropic" if route == "external" else "vllm",
        base_url=("https://api.anthropic.com" if route == "external" else "http://local.test/v1"),
        api_key="test-key",
        default_model="test-model",
        canonical_model="test-model",
        healthcheck_timeout_seconds=1.0,
        long_generation_timeout_seconds=30.0,
    )
    values: dict[str, Any] = {
        "task_kind": task_kind,
        "workload_id": workload.workload_id if workload is not None else None,
        "workload_route": route if workload is not None else None,
        "workload_config": config if workload is not None else None,
        "workload_local_max_output_tokens": 32_768,
        "workload_external_max_output_tokens": 65_536,
        "actor_user_id": "user-1",
        "source": "tests.ai_gateway",
        "app": workload.app_id if workload is not None else "chatbot",
        "requested_model": "test-model" if workload is not None else None,
        "requested_provider": "anthropic" if route == "external" else None,
        "max_tokens": 65_536 if route == "external" else 32_768,
        "messages": [{"role": "user", "content": "hello"}],
    }
    values.update(overrides)
    return AiGatewayRequest(**values)


def test_gateway_unknown_task_kind_does_not_route_external() -> None:
    with pytest.raises(AiGatewayPolicyViolation) as exc_info:
        resolve_gateway_execution(_request("unknown_gateway_task"), _FakePolicyDb("external"))
    assert exc_info.value.reason_code == "unknown_task_kind_local_only"


def test_gateway_context_pack_without_provenance_fails_closed() -> None:
    context_pack = AiGatewayContextPack(
        messages=[{"role": "user", "content": "server-built evidence"}],
        context_strategy="domain_context_pack",
    )

    with pytest.raises(AiGatewayPolicyViolation) as exc_info:
        resolve_gateway_execution(
            _request("files_grounded_chat", context_pack=context_pack),
            _FakePolicyDb("external"),
        )
    assert exc_info.value.reason_code == "external_transfer_blocked"


@pytest.mark.parametrize("environment", ["production"])
def test_gateway_fails_closed_before_provider_in_production_like_environment_when_security_is_off(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    records: list[dict[str, Any]] = []
    invoked = False
    production_settings = get_settings().model_copy(update={"environment": environment})
    monkeypatch.setattr(gateway_module, "get_settings", lambda: production_settings)
    monkeypatch.setattr(
        gateway_module,
        "log_llm_call",
        lambda **kwargs: records.append(kwargs),
    )
    monkeypatch.setattr(
        gateway_module,
        "resolve_ai_security_pipeline_exemption",
        lambda *_args, **_kwargs: pytest.fail(
            "production-like enforcement failures must precede exemptions"
        ),
    )

    def fake_complete_chat(*_args: Any, **kwargs: Any) -> tuple[object, object, object]:
        nonlocal invoked
        invoked = True
        execution = kwargs["resolved_execution"]
        return object(), execution.decision, execution.config

    monkeypatch.setattr(gateway_module, "_complete_chat", fake_complete_chat)

    with pytest.raises(AiGatewayPolicyViolation) as error:
        complete_gateway_chat(
            _request("files_grounded_chat"),
            _FakePolicyDb("external", ai_security_enabled=False),
        )

    assert error.value.reason_code == "ai_security_enforcement_required"
    assert invoked is False
    assert len(records) == 1
    assert records[0]["status"] == "blocked_external"
    assert records[0]["decision_reason"] == "ai_security_enforcement_required"


def test_gateway_mask_and_send_hard_blocks_privacy_filter_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gateway_module,
        "evaluate_ai_security_policy",
        lambda *_args, **_kwargs: AiSecurityPolicyDecision(
            effect="mask_and_send",
            reason_code=POLICY_MASK_AND_SEND_REASON,
        ),
    )
    monkeypatch.setattr(
        masking_module,
        "detect_privacy_filter_spans",
        lambda *_args, **_kwargs: PrivacyFilterDetection(
            status="ok",
            spans=(
                PrivacyFilterSpan(
                    text_index=0,
                    start=8,
                    end=14,
                    label="secret",
                    blocker_type="credential",
                    entity_type="credential",
                ),
            ),
            entity_types=("credential",),
            blocker_types=("credential",),
            enabled=True,
            used=True,
        ),
    )

    with pytest.raises(AiGatewayPolicyViolation) as exc_info:
        resolve_gateway_execution(
            _request(
                "files_grounded_chat",
                messages=[{"role": "user", "content": "Review token fragment"}],
            ),
            _FakePolicyDb("external"),
        )
    assert exc_info.value.reason_code == "external_transfer_blocked"


def test_gateway_policy_block_external_does_not_reroute_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gateway_module,
        "ai_security_data_protection_blocker_actions",
        lambda _db: {
            "sensitive_identifier": "block",
            "internal_url": "block",
            "pii": "mask_and_send",
            "security_document": "block",
        },
    )
    monkeypatch.setattr(
        gateway_module,
        "evaluate_ai_security_policy",
        lambda *_args, **_kwargs: AiSecurityPolicyDecision(
            effect="block_external",
            reason_code="ai_security_policy_block_external",
            rule_id="rule-1",
        ),
    )

    with pytest.raises(AiGatewayPolicyViolation) as exc_info:
        resolve_gateway_execution(
            _request(
                "files_grounded_chat",
                messages=[{"role": "user", "content": "Contact owner@example.com"}],
            ),
            _FakePolicyDb("external"),
        )
    assert exc_info.value.reason_code == "external_transfer_blocked"


def test_execute_llm_uses_registered_admin_route_without_caller_model_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    workload = get_ai_capability_registry().resolve_llm_workload("chatbot")
    monkeypatch.setattr(
        gateway_module,
        "resolve_llm_workload_route",
        lambda *_args, **_kwargs: SimpleNamespace(
            workload=workload,
            runtime_adapter_id=workload.default_runtime_adapter,
            route="external",
            provider_id="anthropic",
            adapter_provider="anthropic",
            requires_credentials=True,
            endpoint_url="https://api.anthropic.com",
            api_key=SimpleNamespace(get_secret_value=lambda: "database-key"),
            model_key="claude-sonnet-4-6",
            local_max_output_tokens=32_768,
            external_max_output_tokens=65_536,
            max_output_tokens=65_536,
        ),
    )

    def fake_complete(request, db):
        captured["request"] = request
        captured["db"] = db
        return (
            SimpleNamespace(text="ok"),
            SimpleNamespace(
                provider=request.workload_config.provider,
                model=request.workload_config.default_model,
                chosen_pool=request.workload_config.pool,
            ),
            request.workload_config,
        )

    monkeypatch.setattr(gateway_module, "require_workload_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway_module, "complete_gateway_chat_text", fake_complete)
    db = object()
    result = execute_llm(
        "chatbot",
        LlmWorkloadContext(
            source="tests.registered_workload",
            actor_user_id="user-1",
            app_id="chatbot",
        ),
        db,  # type: ignore[arg-type]
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=100_000,
    )

    request = captured["request"]
    assert captured["db"] is db
    assert request.workload_id == "chatbot"
    assert request.pool_hint is None
    assert request.requested_provider == "anthropic"
    assert request.requested_model == "claude-sonnet-4-6"
    assert request.max_tokens == 65_536
    assert request.workload_config.api_key == "database-key"
    assert request.workload_config.base_url == "https://api.anthropic.com"
    assert request.workload_config.provider == "anthropic"
    assert result.metadata.model == "claude-sonnet-4-6"
