from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dev_accounts import auth_headers, dev_login
from open_work_hub_api.core.llm_errors import LlmProviderError
from open_work_hub_api.domains.ai.decision_contracts import ChoiceAnswer, DecisionError
from open_work_hub_api.domains.ai.gateway import AiGatewayPolicyViolation
from open_work_hub_api.domains.ai.registry import get_ai_capability_registry
from open_work_hub_api.domains.tetris import ai


def payload():
    details = {"piece": "O", "uses_hold": False, "hold_after": None,
               "next_piece": "I", "next_spawn_blocked": False, "follow_ups": []}
    return {
        "board": [[None] * 10 for _ in range(20)],
        "active": {"kind": "O", "shape": [[1, 1], [1, 1]], "x": 4, "y": 0},
        "next": "I", "hold": None, "can_hold": True,
        "score": 0, "lines": 0, "level": 1,
        "candidates": [
            {**details, "action": "left", "cleared_lines": 0, "holes": 0, "max_height": 2,
             "aggregate_height": 4, "bumpiness": 2, "key_presses": 5},
            {**details, "action": "drop", "cleared_lines": 0, "holes": 0, "max_height": 2,
             "aggregate_height": 4, "bumpiness": 4, "key_presses": 1},
        ],
    }


def result(action="option_0"):
    return SimpleNamespace(
        response=SimpleNamespace(answers={"action": ChoiceAnswer(choice=action, probabilities={action: 1.0})}),
        latency_ms=321,
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
    assert response.json() == {"action": "left", "latency_ms": 321}
    workload, context, args = calls[0]
    assert workload == "tetris.play"
    assert context.actor_user_id == session["user"]["id"]
    assert context.app_id == "tetris"
    assert args["state"]["active_piece"] == body["active"]["kind"]
    assert args["state"]["next_piece"] == "I"
    assert args["state"]["hold_piece"] is None
    assert args["state"]["can_hold"] is False
    assert "board" not in args["state"]
    assert "candidates" not in args["state"]
    assert args["source_kinds"] == ("game_state",)
    assert "hold" not in args["questions"]["action"].options
    options = args["questions"]["action"].options
    assert set(options) == {"option_0", "option_1"}
    assert "covered holes" in options["option_0"]
    assert "surface roughness 4" in options["option_1"]


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
    lambda body: body["candidates"][0].update(action="teleport"),
    lambda body: body["candidates"][0].update(instructions="untrusted"),
    lambda body: body["candidates"][0].update(piece="T"),
    lambda body: body["candidates"][0].update(hold_after="T"),
    lambda body: body["candidates"][0].update(next_piece="T"),
    lambda body: body["candidates"][0].update(next_spawn_blocked=None),
    lambda body: body["candidates"][0].update(uses_hold=True),
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


@pytest.mark.parametrize("error, status", [
    (DecisionError("decision_timeout"), 502),
    (DecisionError("decision_response_invalid"), 502),
    (LlmProviderError("private provider configuration"), 502),
    (AiGatewayPolicyViolation(reason_code="blocked", task_kind="tetris_play"), 403),
])
def test_tetris_decision_errors_are_localized_and_sanitized(client, monkeypatch, error, status):
    session = dev_login(client, "administrator")
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(ai, "execute_decision", fail)
    response = client.post("/api/v1/tetris/decision", json=payload(),
                           headers={**auth_headers(session["token"]), "Accept-Language": "en-US"})
    assert response.status_code == status
    assert response.json()["detail"] == (
        "AI security policy blocked the decision." if status == 403 else "AI decision failed."
    )
    assert "private provider" not in response.text


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
    first.update(action="hold", uses_hold=True, piece="T", hold_after="O")
    first["follow_ups"] = [{
        "piece": "O", "uses_hold": True, "hold_after": "I", "cleared_lines": 2,
        "holes": 0, "max_height": 2, "aggregate_height": 4, "bumpiness": 4, "key_presses": 3,
    }]
    response = client.post("/api/v1/tetris/decision", headers=auth_headers(session["token"]), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["action"] == "hold"
    assert calls[0]["state"]["hold_piece"] == "T"
    assert calls[0]["state"]["can_hold"] is True
    description = calls[0]["questions"]["action"].options["option_0"]
    assert "Place T using hold; reserve afterward: O" in description
    assert "Next active piece: I" in description
    assert "Place O using hold; reserve afterward: I" in description
    assert "Total lines over both placements: 2" in description


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
    headers = auth_headers(session["token"])
    response = client.post("/api/v1/tetris/decision", headers=headers, json=body)
    assert response.status_code == 200
    assert "following piece is unknown" in calls[0]["questions"]["action"].options["option_0"]
    first["follow_ups"] = [{
        "piece": "T", "uses_hold": False, "hold_after": "O", "cleared_lines": 0,
        "holes": 0, "max_height": 2, "aggregate_height": 4, "bumpiness": 4, "key_presses": 3,
    }]
    assert client.post("/api/v1/tetris/decision", headers=headers, json=body).status_code == 422
    assert len(calls) == 1
