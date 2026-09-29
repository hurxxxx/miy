from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dev_accounts import auth_headers, dev_login
from mty_api.core.llm_errors import LlmProviderError, LlmRuntimeError
from mty_api.domains.ai.decision_contracts import ChoiceAnswer, DecisionError
from mty_api.domains.ai.gateway import AiGatewayPolicyViolation
from mty_api.domains.ai.registry import get_ai_capability_registry
from mty_api.domains.tetris import ai


def payload():
    details = {"piece": "O", "uses_hold": False, "hold_after": None,
               "next_piece": "I", "next_spawn_blocked": False, "follow_ups": []}
    return {
        "board": [[None] * 10 for _ in range(20)],
        "active": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 0},
        "next": "I", "hold": None, "can_hold": True,
        "score": 0, "lines": 0, "level": 1,
        "candidates": [
            {**details, "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 0, "y": 18},
             "action": "left", "cleared_lines": 0, "holes": 0, "max_height": 2,
             "aggregate_height": 4, "bumpiness": 2, "key_presses": 5},
            {**details, "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 18},
             "action": "drop", "cleared_lines": 0, "holes": 0, "max_height": 2,
             "aggregate_height": 4, "bumpiness": 4, "key_presses": 1},
        ],
    }


def result(action="option_0"):
    return SimpleNamespace(
        response=SimpleNamespace(answers={"action": ChoiceAnswer(choice=action, probabilities={action: 1.0})}),
        latency_ms=321,
        metadata=SimpleNamespace(model="test/model", provider="test"),
    )


def test_tetris_workload_registered():
    workload = get_ai_capability_registry().get_llm_workload("tetris.play")
    assert workload.execution_kind == "decision"
    assert workload.required_capabilities == ("decision",)
    assert workload.allowed_runtime_adapters == ("decision",)


def test_tetris_decision_uses_authenticated_owner_and_fixed_workload(client: TestClient, monkeypatch):
    session = dev_login(client, "administrator")
    calls = []

    def execute(workload, context, db, **kwargs):
        calls.append((workload, context, kwargs))
        return result()

    monkeypatch.setattr(ai, "execute_decision", execute)
    body = payload()
    body["can_hold"] = False
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "action": "left", "latency_ms": 321, "model": "test/model", "provider": "test", "kind": "decision",
        "placement": {"target": body["candidates"][0]["target"], "uses_hold": False},
    }
    workload, context, args = calls[0]
    assert workload == "tetris.play"
    assert context.actor_user_id == session["user"]["id"]
    assert context.app_id == "tetris"
    observation = args["state"]["self"]
    assert observation["active"] == {**body["active"], "shape": ["11", "11"]}
    assert observation["next"] == "I"
    assert observation["hold"] is None
    assert observation["can_hold"] is False
    assert observation["board"] == [".........."] * 20
    assert "model_choice" not in observation
    assert "candidates" not in args["state"]
    assert "candidates" not in observation
    assert args["source_kinds"] == ("game_state",)
    assert "hold" not in args["questions"]["action"].options
    options = args["questions"]["action"].options
    assert set(options) == {"option_0", "option_1"}
    assert "holes=0" in options["option_0"]
    assert "roughness=4" in options["option_1"]


@pytest.mark.parametrize("mutate", [
    lambda body: body.update(board=[]),
    lambda body: body["board"][0].append(None),
    lambda body: body["active"].update(x=10),
    lambda body: body["active"].update(shape=[[1, 1, 1], [1, 0, 0]]),
    lambda body: body["active"].update(shape=[[1, 1], [1, 0]]),
    lambda body: body["board"][0].__setitem__(4, "I"),
    lambda body: body.update(model="untrusted"),
    lambda body: body.update(instructions="untrusted"),
    lambda body: body.update(next=["I", "J"]),
    lambda body: body.update(score=-1),
    lambda body: body.update(candidates=[]),
    lambda body: body.update(candidates=body["candidates"] * 17),
    lambda body: body["candidates"][0].update(holes=-1),
    lambda body: body["candidates"][0].update(key_presses=65),
    lambda body: body["candidates"][0].update(wells=[{"column": 10, "depth": 4, "ready_rows": 4, "filled_cells": 36}]),
    lambda body: body["candidates"][0].update(wells=[{"column": 0, "depth": 0, "ready_rows": 0, "filled_cells": 0}]),
    lambda body: body["candidates"][0].update(wells=[{"column": 0, "depth": 2, "ready_rows": 3, "filled_cells": 27}]),
    lambda body: body["candidates"][0].update(wells=[{"column": 0, "depth": 4, "ready_rows": 4, "filled_cells": 35}]),
    lambda body: body["candidates"][0].update(wells=[{"column": 0, "depth": 4, "ready_rows": 4, "filled_cells": 36}] * 2),
    lambda body: body["candidates"][0].update(action="teleport"),
    lambda body: body["candidates"][0].update(instructions="untrusted"),
    lambda body: body["candidates"][0].update(piece="T"),
    lambda body: body["candidates"][0].update(hold_after="T"),
    lambda body: body["candidates"][0].update(next_piece="T"),
    lambda body: body["candidates"][0].update(next_spawn_blocked=None),
    lambda body: body["candidates"][0].update(uses_hold=True),
    lambda body: body["candidates"][0].pop("target"),
    lambda body: body["candidates"][0]["target"].update(kind="T"),
    lambda body: body["candidates"][0]["target"].update(x=9),
    lambda body: body["candidates"][0]["target"].update(y=19),
])
def test_invalid_game_never_calls_model(client, monkeypatch, mutate):
    session = dev_login(client, "administrator")
    monkeypatch.setattr(ai, "execute_decision", lambda *a, **kw: pytest.fail("must not call model"))
    body = payload()
    mutate(body)
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 422


def test_tetris_decision_requires_current_app_admission(client, monkeypatch):
    monkeypatch.setattr(ai, "execute_decision", lambda *a, **kw: pytest.fail("must not call model"))
    assert client.post("/api/v1/tetris/decision", json=payload()).status_code == 401
    session = dev_login(client, "administrator")
    headers = auth_headers(session["token"])
    response = client.put("/api/v1/admin/apps/tetris/access-policy", headers=headers,
                          json={"enabled": False, "audience": "all", "user_ids": [], "group_ids": []})
    assert response.status_code == 200
    assert client.post("/api/v1/tetris/decision", headers=headers, json=payload()).status_code == 403


@pytest.mark.parametrize("kind", ["decision", "generation"])
@pytest.mark.parametrize("error, status", [
    (DecisionError("decision_timeout"), 502),
    (DecisionError("decision_response_invalid"), 502),
    (LlmProviderError("private provider configuration"), 502),
    (LlmRuntimeError("private runtime timeout details"), 502),
    (AiGatewayPolicyViolation(reason_code="blocked", task_kind="tetris_play"), 403),
])
def test_tetris_decision_errors_are_localized_and_sanitized(client, monkeypatch, error, status, kind):
    session = dev_login(client, "administrator")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(ai, "execute_decision" if kind == "decision" else "execute_llm", fail)
    body = {**payload(), "model_choice": {"kind": kind, "model_id": "test"}}
    response = client.post("/api/v1/tetris/decision", json=body,
                           headers={**auth_headers(session["token"]), "Accept-Language": "en-US"})
    assert response.status_code == status
    assert response.json()["detail"] == (
        "AI security policy blocked the decision." if status == 403 else "AI decision failed."
    )
    assert "private provider" not in response.text
    assert "private runtime" not in response.text


def test_tetris_rejects_unavailable_hold_choice(client, monkeypatch):
    session = dev_login(client, "administrator")
    monkeypatch.setattr(ai, "execute_decision", lambda *a, **kw: result("hold"))
    body = payload()
    body["can_hold"] = False
    assert client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body).status_code == 502


def test_single_candidate_still_requires_a_model_choice(client, monkeypatch):
    session = dev_login(client, "administrator")
    calls = []
    def choose(*args, **kwargs):
        calls.append(kwargs)
        return result("wait")
    monkeypatch.setattr(ai, "execute_decision", choose)
    body = payload()
    body["candidates"] = body["candidates"][:1]
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 200
    assert response.json()["action"] == "wait"
    assert response.json()["placement"] is None
    assert set(calls[0]["questions"]["action"].options) == {"option_0", "wait"}


def test_candidate_hold_must_be_available(client, monkeypatch):
    session = dev_login(client, "administrator")
    monkeypatch.setattr(ai, "execute_decision", lambda *a, **kw: pytest.fail("must not call model"))
    body = payload()
    body["can_hold"] = False
    body["candidates"][0]["action"] = "hold"
    assert client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body).status_code == 422


def test_model_sees_hold_tradeoff_and_two_placement_forecast(client, monkeypatch):
    session = dev_login(client, "administrator")
    calls = []
    def choose(*args, **kwargs):
        calls.append(kwargs)
        return result()
    monkeypatch.setattr(ai, "execute_decision", choose)
    body = payload()
    body["hold"] = "T"
    for candidate in body["candidates"]:
        candidate["hold_after"] = "T"
    first = body["candidates"][0]
    first.update(action="hold", uses_hold=True, piece="T", hold_after="O", cleared_lines=2)
    first["target"] = {"kind": "T", "shape": [[0, 1, 0], [1, 1, 1], [0, 0, 0]], "x": 0, "y": 18}
    first["follow_ups"] = [{
        "piece": "O", "uses_hold": True, "hold_after": "I", "cleared_lines": 2,
        "target": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 18},
        "holes": 0, "max_height": 2, "aggregate_height": 4, "bumpiness": 4, "key_presses": 3,
    }]
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "hold"
    assert response.json()["placement"] == {"target": first["target"], "uses_hold": True}
    assert calls[0]["state"]["self"]["hold"] == "T"
    assert calls[0]["state"]["self"]["can_hold"] is True
    description = calls[0]["questions"]["action"].options["option_0"]
    assert "now: piece=T hold=1 reserve=O" in description
    assert "next=I spawn_blocked=0" in description
    assert "then: piece=O hold=1 reserve=I" in description
    assert "total_clear=4" in description
    assert "total_attack=2" in description


@pytest.mark.parametrize("duel", [False, True])
def test_both_model_kinds_receive_identical_rules_strategy_and_candidates(client, monkeypatch, duel):
    import json
    observed = {}

    def decision(*args, **kwargs):
        observed["decision"] = {"state": kwargs["state"], "options": kwargs["questions"]["action"].options}
        return result()

    def generation(*args, **kwargs):
        observed["generation"] = json.loads(kwargs["context_pack"].messages[1]["content"])
        return SimpleNamespace(
            completion=SimpleNamespace(structured_output={"choice": "option_0"}),
            metadata=SimpleNamespace(model="test/model", provider="test"),
        )

    monkeypatch.setattr(ai, "execute_decision", decision)
    monkeypatch.setattr(ai, "execute_llm", generation)
    session = dev_login(client, "administrator")
    for kind in ("decision", "generation"):
        body = {**payload(), "model_choice": {"kind": kind, "model_id": "test-model"}}
        body["candidates"][0]["wells"] = [{"column": 9, "depth": 3, "ready_rows": 2, "filled_cells": 23}]
        if duel:
            body["opponent"] = {key: value for key, value in payload().items() if key != "candidates"}
        response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
        assert response.status_code == 200
        assert response.json()["placement"] == {"target": body["candidates"][0]["target"], "uses_hold": False}

    assert observed["decision"] == observed["generation"]
    assert "wells=9:3:2:23" in observed["decision"]["options"]["option_0"]
    state = observed["decision"]["state"]
    assert state["rules"] and state["strategy"]
    assert ("attack_rules" in state) is duel
    assert ("opponent" in state) is duel


@pytest.mark.parametrize("candidate_count", [26, 27, 32])
def test_all_models_share_the_native_choice_limit(client, monkeypatch, candidate_count):
    import json

    observed = {}

    def decision(*args, **kwargs):
        observed["decision"] = {"state": kwargs["state"], "options": kwargs["questions"]["action"].options}
        return result("option_25")

    def generation(*args, **kwargs):
        observed["generation"] = json.loads(kwargs["context_pack"].messages[1]["content"])
        assert kwargs["output_schema"]["properties"]["choice"]["enum"] == list(observed["generation"]["options"])
        return SimpleNamespace(
            completion=SimpleNamespace(structured_output={"choice": "option_25"}),
            metadata=SimpleNamespace(model="test/model", provider="test"),
        )

    monkeypatch.setattr(ai, "execute_decision", decision)
    monkeypatch.setattr(ai, "execute_llm", generation)
    session = dev_login(client, "administrator")
    body = payload()
    original = body["candidates"]
    body["candidates"] = [
        {**original[index % 2], "key_presses": index + 1}
        for index in range(candidate_count)
    ]
    for kind in ("decision", "generation"):
        body["model_choice"] = {"kind": kind, "model_id": "test-model"}
        response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
        assert response.status_code == 200, response.text
        assert response.json()["action"] == body["candidates"][25]["action"]

    assert observed["decision"] == observed["generation"]
    options = observed["decision"]["options"]
    assert list(options) == [f"option_{index}" for index in range(26)]
    for index, description in enumerate(options.values()):
        assert f"keys={index + 1}\n" in description


def test_empty_hold_cannot_forecast_an_unseen_piece(client, monkeypatch):
    session = dev_login(client, "administrator")
    calls = []
    def choose(*args, **kwargs):
        calls.append(kwargs)
        return result()
    monkeypatch.setattr(ai, "execute_decision", choose)
    body = payload()
    first = body["candidates"][0]
    first.update(action="hold", uses_hold=True, piece="I", hold_after="O", next_piece=None,
                 next_spawn_blocked=None)
    first["target"] = {"kind": "I", "shape": [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]], "x": 0, "y": 18}
    headers = auth_headers(session["token"])
    response = client.post("/api/v1/tetris/decision", headers=headers, json=body)
    assert response.status_code == 200
    description = calls[0]["questions"]["action"].options["option_0"]
    assert "next=unknown spawn_blocked=unknown" in description
    assert "then:" not in description
    first["follow_ups"] = [{
        "piece": "T", "uses_hold": False, "hold_after": "O", "cleared_lines": 0,
        "target": {"kind": "T", "shape": [[0, 1, 0], [1, 1, 1], [0, 0, 0]], "x": 0, "y": 18},
        "holes": 0, "max_height": 2, "aggregate_height": 4, "bumpiness": 4, "key_presses": 3,
    }]
    assert client.post("/api/v1/tetris/decision", headers=headers, json=body).status_code == 422
    assert len(calls) == 1


@pytest.fixture
def selectable_models(client, monkeypatch):
    from mty_api.core.settings import get_settings
    monkeypatch.setenv("MTY_AI_ALLOWED_EXTERNAL_PROVIDERS", "openrouter")
    get_settings.cache_clear()
    from mty_api.core.db import get_session_factory
    from mty_api.domains.ai.model_settings_models import AiModelProviderConfig, AiModelCatalogEntry, AiModelPolicyDefault
    session = dev_login(client, "administrator")
    with get_session_factory()() as db:
        db.add(AiModelProviderConfig(
            provider_id="arena-test", provider_kind="openrouter", display_name="Arena",
            route_mode="external", credential_kind="none", endpoint_url="https://openrouter.ai/api/v1", enabled=True,
        ))
        db.flush()
        for model_id, caps in (
            ("arena-decision", ["decision"]),
            ("arena-chat", ["chat", "non_reasoning", "tool_calling"]),
            ("arena-plain", ["chat", "non_reasoning"]),
            ("arena-thinking", ["chat", "tool_calling"]),
        ):
            db.add(AiModelCatalogEntry(id=model_id, provider_id="arena-test", model_key=f"test/{model_id}", display_name=model_id, capabilities_json=caps, enabled=True))
        db.flush()
        for family, model_id in (("decision", "arena-decision"), ("generation", "arena-chat")):
            db.merge(AiModelPolicyDefault(model_family=family, app_id="tetris", route_mode="external", provider_id="arena-test", model_id=model_id))
        db.commit()
    return session


def test_models_catalog_is_safe_dynamic_and_admitted(client, selectable_models):
    from mty_api.core.db import get_session_factory
    from mty_api.domains.ai.model_settings_models import AiModelCatalogEntry
    assert client.get("/api/v1/tetris/models").status_code == 401
    headers = auth_headers(selectable_models["token"])
    response = client.get("/api/v1/tetris/models", headers=headers)
    assert response.status_code == 200
    models = response.json()["models"]
    assert {(item["model_id"], item["kind"]) for item in models} == {
        ("arena-decision", "decision"), ("arena-chat", "generation"), ("arena-plain", "generation"),
    }
    assert {item["model_id"] for item in models if item["is_default"]} == {"arena-decision", "arena-chat"}
    assert all(set(item) == {"model_id", "kind", "name", "model_key", "provider", "is_default"} for item in models)
    with get_session_factory()() as db:
        db.get(AiModelCatalogEntry, "arena-chat").enabled = False
        db.commit()
    assert len(client.get("/api/v1/tetris/models", headers=headers).json()["models"]) == 2
    client.put("/api/v1/admin/apps/tetris/access-policy", headers=headers,
               json={"enabled": False, "audience": "all", "user_ids": [], "group_ids": []})
    assert client.get("/api/v1/tetris/models", headers=headers).status_code == 403


def test_llm_uses_structured_choice_and_same_observation(client, selectable_models, monkeypatch):
    seen = []
    def generate(workload, context, db, **kwargs):
        seen.append((workload, context, kwargs))
        return SimpleNamespace(completion=SimpleNamespace(structured_output={"choice": "option_1"}), metadata=SimpleNamespace(model="test/arena-chat", provider="openrouter"))
    monkeypatch.setattr(ai, "execute_llm", generate)
    body = payload()
    body["model_choice"] = {"kind": "generation", "model_id": "arena-chat"}
    body["opponent"] = {key: value for key, value in payload().items() if key != "candidates"}
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(selectable_models["token"]), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "drop"
    assert response.json()["kind"] == "generation"
    workload, context, kwargs = seen[0]
    assert workload == "tetris.play.generation"
    assert context.actor_user_id == selectable_models["user"]["id"]
    assert kwargs["selected_model_id"] == "arena-chat"
    assert kwargs["output_schema"]["properties"]["choice"]["enum"] == ["option_0", "option_1"]
    assert kwargs["output_schema"]["additionalProperties"] is False
    import json
    observation = json.loads(kwargs["context_pack"].messages[1]["content"])
    assert observation["state"]["opponent"] == {
        **body["opponent"], "board": [".........."] * 20,
        "active": {**body["opponent"]["active"], "shape": ["11", "11"]},
    }
    assert observation["state"]["opponent"] == observation["state"]["self"]
    assert "1/2/3" in observation["state"]["attack_rules"]
    assert "non_reasoning" in get_ai_capability_registry().get_llm_workload(workload).required_capabilities
    assert kwargs["timeout_seconds"] == 30
    assert kwargs["max_tokens"] == 1024


@pytest.mark.parametrize("model_id", ["arena-chat", "arena-plain"])
def test_selected_models_cannot_reenable_reasoning(client, selectable_models, model_id):
    from mty_api.core.db import get_session_factory
    from mty_api.domains.ai.gateway import LlmWorkloadContext, build_llm_workload_request

    with get_session_factory()() as db:
        request = build_llm_workload_request(
            ai.GENERATION_WORKLOAD_ID,
            LlmWorkloadContext(source="test.non_reasoning", actor_user_id=selectable_models["user"]["id"], app_id="tetris"),
            db,
            selected_model_id=model_id,
            reasoning_effort="high",
            extra_body={"reasoning": {"enabled": True}},
        )
    assert request.reasoning_effort == "none"
    assert request.extra_body is None
    assert request.requested_model == f"test/{model_id}"


def test_reasoning_required_model_is_rejected_before_inference(client, selectable_models, monkeypatch):
    from mty_api.core import llm
    monkeypatch.setattr(llm, "complete_direct_chat", lambda *a, **kw: pytest.fail("must not call model"))
    body = {**payload(), "model_choice": {"kind": "generation", "model_id": "arena-thinking"}}
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(selectable_models["token"]), json=body)
    assert response.status_code == 502


@pytest.mark.parametrize("value", [None, {}, {"choice": "teleport"}, {"choice": 1}, {"choice": "option_0", "extra": True}, '{"choice":"option_0"}'])
def test_llm_rejects_invalid_structured_results(client, monkeypatch, value):
    session = dev_login(client, "administrator")
    monkeypatch.setattr(ai, "execute_llm", lambda *a, **kw: SimpleNamespace(completion=SimpleNamespace(structured_output=value)))
    body = payload()
    body["model_choice"] = {"kind": "generation", "model_id": "test"}
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 502


@pytest.mark.parametrize("reason, status, code", [
    ("rate_limited", 429, "tetris.ai_rate_limited"),
    ("output_limit", 502, "tetris.ai_output_limit"),
    ("timeout", 504, "tetris.ai_timeout"),
])
def test_llm_exposes_only_safe_localized_failure_reason(client, monkeypatch, reason, status, code):
    session = dev_login(client, "administrator")
    def fail(*args, **kwargs):
        raise LlmProviderError("private provider body", reason_code=reason)
    monkeypatch.setattr(ai, "execute_llm", fail)
    body = {**payload(), "model_choice": {"kind": "generation", "model_id": "test"}}
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "private" not in response.text


def test_model_selection_cannot_bypass_workload_route_or_capabilities(client, selectable_models):
    from mty_api.core.db import get_session_factory
    from mty_api.domains.ai.model_settings_service import resolve_ai_model_workload_route, AiModelSettingsError
    from mty_api.domains.ai.model_settings_models import AiModelProviderConfig, AiModelCatalogEntry
    with get_session_factory()() as db:
        selected = resolve_ai_model_workload_route(db, workload_id="tetris.play.generation", selected_model_id="arena-chat")
        assert selected.model_key == "test/arena-chat"
        assert selected.model_source == "selection"
        from mty_api.core.settings import get_settings
        blocked = get_settings().model_copy(update={"ai_allowed_external_providers": "openai"})
        with pytest.raises(AiModelSettingsError, match="selected_model_unavailable"):
            resolve_ai_model_workload_route(
                db, workload_id="tetris.play.generation", selected_model_id="arena-chat", settings=blocked,
            )
        with pytest.raises(AiModelSettingsError, match="selection_not_allowed"):
            resolve_ai_model_workload_route(db, workload_id="chatbot", app_id="chatbot", selected_model_id="arena-chat")
        for workload, model in (("tetris.play", "arena-chat"), ("tetris.play.generation", "arena-decision")):
            with pytest.raises(AiModelSettingsError, match="capability_mismatch"):
                resolve_ai_model_workload_route(db, workload_id=workload, selected_model_id=model)
        db.get(AiModelCatalogEntry, "arena-chat").enabled = False
        db.flush()
        with pytest.raises(AiModelSettingsError):
            resolve_ai_model_workload_route(db, workload_id="tetris.play.generation", selected_model_id="arena-chat")
        db.get(AiModelCatalogEntry, "arena-chat").enabled = True
        db.get(AiModelProviderConfig, "arena-test").route_mode = "local"
        db.flush()
        with pytest.raises(AiModelSettingsError, match="route_provider_mismatch"):
            resolve_ai_model_workload_route(db, workload_id="tetris.play.generation", selected_model_id="arena-chat")


@pytest.mark.parametrize("kind", ["decision", "generation"])
def test_selected_model_reaches_common_execution_and_audit_without_changing_defaults(
    client, selectable_models, monkeypatch, kind,
):
    from mty_api.core.db import get_session_factory
    from mty_api.domains.ai import audit as ai_audit, decisions, gateway
    from mty_api.domains.ai.decision_contracts import DecisionResponse
    from mty_api.domains.ai.model_settings_models import AiModelCatalogEntry, AiModelPolicyDefault
    from mty_api.core.llm_execution_adapters import OpenAICompatibleLlmExecutionAdapter

    selected_id = f"selected-{kind}"
    selected_key = f"test/{selected_id}"
    with get_session_factory()() as db:
        db.add(AiModelCatalogEntry(
            id=selected_id, provider_id="arena-test", model_key=selected_key,
            display_name=selected_id, enabled=True,
            capabilities_json=["decision"] if kind == "decision" else ["chat", "non_reasoning"],
        ))
        db.commit()
        default_before = db.get(AiModelPolicyDefault, (kind, "tetris", "external")).model_id
    executed, audit = [], []

    def native(config, request):
        executed.append((config.default_model, config.connection_id))
        return DecisionResponse(model=config.default_model, answers={"action": ChoiceAnswer(
            choice="option_1", probabilities={"option_0": 0.0, "option_1": 1.0},
        )})

    def generate(self, config, payload, **kwargs):
        # A different selected model must retain the workload's reasoning policy.
        assert payload["extra_body"]["reasoning"] == {"effort": "none"}
        executed.append((payload["model"], config.connection_id))
        assert payload["response_format"]["json_schema"]["schema"]["properties"]["choice"]["enum"] == ["option_0", "option_1"]
        return {
            "model": payload["model"],
            "choices": [{"message": {"content": '{"choice":"option_1"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    # Mock only the remote runtime, keeping resolution, admission, policy and audit paths real.
    monkeypatch.setattr(decisions, "get_decision_adapter", lambda _: SimpleNamespace(execute=native))
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
