from types import SimpleNamespace

import pytest

from dev_accounts import auth_headers, dev_login
from miy_api.domains.ai.decision_contracts import ChoiceAnswer


def payload():
    details = {
        "piece": "O",
        "uses_hold": False,
        "hold_after": None,
        "next_piece": "I",
        "next_spawn_blocked": False,
        "follow_ups": [],
    }
    return {
        "board": [[None] * 10 for _ in range(20)],
        "active": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 0},
        "next": "I",
        "hold": None,
        "can_hold": True,
        "score": 0,
        "lines": 0,
        "level": 1,
        "candidates": [
            {
                **details,
                "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 0, "y": 18},
                "action": "left",
                "cleared_lines": 0,
                "holes": 0,
                "max_height": 2,
                "aggregate_height": 4,
                "bumpiness": 2,
                "key_presses": 5,
            },
            {
                **details,
                "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 18},
                "action": "drop",
                "cleared_lines": 0,
                "holes": 0,
                "max_height": 2,
                "aggregate_height": 4,
                "bumpiness": 4,
                "key_presses": 1,
            },
        ],
    }


def result(action="option_0"):
    return SimpleNamespace(
        response=SimpleNamespace(
            answers={"action": ChoiceAnswer(choice=action, probabilities={action: 1.0})}
        ),
        latency_ms=321,
        metadata=SimpleNamespace(model="test/model", provider="test"),
    )


@pytest.fixture
def selectable_models(client, monkeypatch):
    from miy_api.core.settings import get_settings

    monkeypatch.setenv("MIY_AI_ALLOWED_EXTERNAL_PROVIDERS", "openrouter")
    monkeypatch.setenv("MIY_LLM_EXTERNAL_ALLOWED_PROVIDERS", "openrouter")
    get_settings.cache_clear()
    from miy_api.core.db import get_session_factory
    from miy_api.domains.ai.model_settings_models import (
        AiModelProviderConfig,
        AiModelCatalogEntry,
        AiModelPolicyDefault,
    )

    session = dev_login(client, "administrator")
    with get_session_factory()() as db:
        db.add(
            AiModelProviderConfig(
                provider_id="arena-test",
                provider_kind="openrouter",
                display_name="Arena",
                route_mode="external",
                credential_kind="none",
                endpoint_url="https://openrouter.ai/api/v1",
                enabled=True,
            )
        )
        db.flush()
        for model_id, caps in (
            ("arena-decision", ["decision"]),
            ("arena-chat", ["chat", "non_reasoning", "tool_calling"]),
            ("arena-plain", ["chat", "non_reasoning"]),
            ("arena-thinking", ["chat", "tool_calling"]),
        ):
            db.add(
                AiModelCatalogEntry(
                    id=model_id,
                    provider_id="arena-test",
                    model_key=f"test/{model_id}",
                    display_name=model_id,
                    capabilities_json=caps,
                    enabled=True,
                )
            )
        db.flush()
        for family, model_id in (("decision", "arena-decision"), ("generation", "arena-chat")):
            db.merge(
                AiModelPolicyDefault(
                    model_family=family,
                    app_id="tetris",
                    route_mode="external",
                    provider_id="arena-test",
                    model_id=model_id,
                )
            )
        db.commit()
    yield session
    get_settings.cache_clear()


def test_model_selection_cannot_bypass_workload_route_or_capabilities(client, selectable_models):
    from miy_api.core.db import get_session_factory
    from miy_api.domains.ai.model_settings_service import (
        resolve_ai_model_workload_route,
        AiModelSettingsError,
    )
    from miy_api.domains.ai.model_settings_models import AiModelProviderConfig, AiModelCatalogEntry

    with get_session_factory()() as db:
        selected = resolve_ai_model_workload_route(
            db, workload_id="tetris.play.generation", selected_model_id="arena-chat"
        )
        assert selected.model_key == "test/arena-chat"
        assert selected.model_source == "selection"
        from miy_api.core.settings import get_settings

        blocked = get_settings().model_copy(update={"ai_allowed_external_providers": "openai"})
        with pytest.raises(AiModelSettingsError, match="selected_model_unavailable"):
            resolve_ai_model_workload_route(
                db,
                workload_id="tetris.play.generation",
                selected_model_id="arena-chat",
                settings=blocked,
            )
        with pytest.raises(AiModelSettingsError, match="selection_not_allowed"):
            resolve_ai_model_workload_route(
                db, workload_id="chatbot", app_id="chatbot", selected_model_id="arena-chat"
            )
        for workload, model in (
            ("tetris.play", "arena-chat"),
            ("tetris.play.generation", "arena-decision"),
        ):
            with pytest.raises(AiModelSettingsError, match="capability_mismatch"):
                resolve_ai_model_workload_route(db, workload_id=workload, selected_model_id=model)
        db.get(AiModelCatalogEntry, "arena-chat").enabled = False
        db.flush()
        with pytest.raises(AiModelSettingsError):
            resolve_ai_model_workload_route(
                db, workload_id="tetris.play.generation", selected_model_id="arena-chat"
            )
        db.get(AiModelCatalogEntry, "arena-chat").enabled = True
        db.get(AiModelProviderConfig, "arena-test").route_mode = "local"
        db.flush()
        with pytest.raises(AiModelSettingsError, match="route_provider_mismatch"):
            resolve_ai_model_workload_route(
                db, workload_id="tetris.play.generation", selected_model_id="arena-chat"
            )


@pytest.mark.parametrize("kind", ["generation"])
def test_selected_model_reaches_common_execution_and_audit_without_changing_defaults(
    client,
    selectable_models,
    monkeypatch,
    kind,
):
    from miy_api.core.db import get_session_factory
    from miy_api.domains.ai import audit as ai_audit, decisions, gateway
    from miy_api.domains.ai.decision_contracts import DecisionResponse
    from miy_api.domains.ai.model_settings_models import AiModelCatalogEntry, AiModelPolicyDefault
    from miy_api.core.llm_execution_adapters import OpenAICompatibleLlmExecutionAdapter

    selected_id = f"selected-{kind}"
    selected_key = f"test/{selected_id}"
    with get_session_factory()() as db:
        db.add(
            AiModelCatalogEntry(
                id=selected_id,
                provider_id="arena-test",
                model_key=selected_key,
                display_name=selected_id,
                enabled=True,
                capabilities_json=["decision"] if kind == "decision" else ["chat", "non_reasoning"],
            )
        )
        db.commit()
        default_before = db.get(AiModelPolicyDefault, (kind, "tetris", "external")).model_id
    executed, audit = [], []

    def native(config, request):
        executed.append((config.default_model, config.connection_id))
        return DecisionResponse(
            model=config.default_model,
            answers={
                "action": ChoiceAnswer(
                    choice="option_1",
                    probabilities={"option_0": 0.0, "option_1": 1.0},
                )
            },
        )

    def generate(self, config, payload, **kwargs):
        # A different selected model must retain the workload's reasoning policy.
        assert payload["extra_body"]["reasoning"] == {"effort": "none"}
        executed.append((payload["model"], config.connection_id))
        assert payload["response_format"]["json_schema"]["schema"]["properties"]["choice"][
            "enum"
        ] == ["option_0", "option_1"]
        return {
            "model": payload["model"],
            "choices": [{"message": {"content": '{"choice":"option_1"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    # Mock only the remote runtime, keeping resolution, admission, policy and audit paths real.
    monkeypatch.setattr(
        decisions, "get_decision_adapter", lambda _: SimpleNamespace(execute=native)
    )
    monkeypatch.setattr(OpenAICompatibleLlmExecutionAdapter, "complete", generate)
    monkeypatch.setattr(decisions, "log_llm_call", lambda **kwargs: audit.append(kwargs))
    monkeypatch.setattr(gateway, "log_llm_call", lambda **kwargs: audit.append(kwargs))
    monkeypatch.setattr(ai_audit, "log_llm_call", lambda **kwargs: audit.append(kwargs))
    body = {**payload(), "model_choice": {"kind": kind, "model_id": selected_id}}
    headers = auth_headers(selectable_models["token"])
    response = client.post("/api/v1/tetris/decision", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["model"] == selected_key
    assert response.json()["action"] == "drop"
    assert executed == [(selected_key, "arena-test")]
    assert len(audit) == 1
    assert audit[0]["requested_model"] == selected_key
    assert audit[0]["actor_user_id"] == selectable_models["user"]["id"]
    if kind == "generation":
        assert audit[0]["runtime_adapter_id"] == "direct_completion"
    with get_session_factory()() as db:
        assert db.get(AiModelPolicyDefault, (kind, "tetris", "external")).model_id == default_before
        db.get(AiModelCatalogEntry, selected_id).enabled = False
        db.commit()
    assert client.post("/api/v1/tetris/decision", headers=headers, json=body).status_code == 502
    assert len(executed) == 1
