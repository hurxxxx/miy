from copy import deepcopy

import pytest
from conftest import complete, new_task, notify, send_message
from sqlalchemy import select

from codex_console import store
from codex_console.errors import ConsoleError
from codex_console.models import AsyncQuestion, Operation

ITEM = {
    "id": "async-call",
    "type": "agentMessage",
    "phase": "final_answer",
    "delivery": "async",
    "text": "Allow the version exception?",
    "questions": [{"title": "Allow the version exception?", "options": ["Allow", "Keep policy"]}],
}
BODY = {"answers": {"0": ["Keep policy"]}}


def detail(client, task):
    return client.get(f"/api/tasks/{task['id']}").json()


def question(client, task):
    notify(client, task, "item/completed", {"item": deepcopy(ITEM)})
    result = detail(client, task)
    assert result["pending_count"] == 1
    return result["async_questions"][0]


def answer(client, task, q, body=BODY):
    return client.post(f"/api/tasks/{task['id']}/questions/{q['id']}", json=body)


@pytest.mark.parametrize("stage", ["plan", "implement"])
def test_question_survives_completion_and_continues_in_original_mode(client, stage):
    task = send_message(client, new_task(client), stage).json()
    q = question(client, task)
    assert detail(client, task)["results"] == []
    assert detail(client, task)["summary"]["pending_kinds"] == ["question"]
    complete(client, task)
    result = detail(client, task)
    assert result["async_questions"][0]["state"] == "pending"
    item = next(i for i in result["items"] if i["id"] == ITEM["id"])
    assert item["delivery"] == "async" and item["questions"] == ITEM["questions"]
    response = answer(client, task, q)
    assert response.status_code == 200, response.text
    assert response.json()["async_questions"][0]["state"] == "answered"
    assert response.json()["pending_count"] == 0
    calls = client.app.state.runtime.rpc.calls
    sent = [params for method, params in calls if method == "turn/start"][-1]
    assert sent["collaborationMode"]["mode"] == ("plan" if stage == "plan" else "default")
    assert sent["approvalPolicy"] == ("never" if stage == "plan" else "on-request")
    assert "Keep policy" in sent["input"][0]["text"]
    before = len(calls)
    assert answer(client, task, q).status_code == 200
    assert len(calls) == before
    assert answer(client, task, q, {"answers": {"0": ["Allow"]}}).status_code == 409


def test_running_answer_steers_and_does_not_create_a_turn(client):
    task = send_message(client, new_task(client), "implement").json()
    q = question(client, task)
    rpc = client.app.state.runtime.rpc
    before = sum(method == "turn/start" for method, _ in rpc.calls)
    assert answer(client, task, q).status_code == 200
    sent = [p for m, p in rpc.calls if m == "turn/steer"][-1]
    assert sent["threadId"] == task["thread_id"] and sent["expectedTurnId"] == task["turn_id"]
    assert sum(method == "turn/start" for method, _ in rpc.calls) == before
    history = client.get(f"/api/tasks/{task['id']}/history?category=requests").json()["items"]
    assert {r["event"] for r in history} >= {"question.pending", "question.answered"}
    assert all("Keep policy" not in str(r) for r in history)


def test_uncertain_delivery_never_resends_and_history_confirms_receipt(client, monkeypatch):
    task = send_message(client, new_task(client)).json()
    q = question(client, task)
    rpc = client.app.state.runtime.rpc
    original = rpc.call
    count = 0

    async def fail(method, params):
        nonlocal count
        if method == "turn/steer":
            count += 1
            raise ConsoleError("codex_request_uncertain", 503)
        return await original(method, params)

    monkeypatch.setattr(rpc, "call", fail)
    assert answer(client, task, q).status_code == 503
    assert detail(client, task)["async_questions"][0]["state"] == "uncertain"
    assert answer(client, task, q).status_code == 409
    assert count == 1
    with client.app.state.factory.begin() as db:
        saved = store.require_task(db, task["id"])
        store.reconcile_history(
            db,
            saved,
            [
                {
                    "id": task["turn_id"],
                    "items": [
                        ITEM,
                        {
                            "id": "answer-message",
                            "type": "userMessage",
                            "clientId": q["id"],
                            "content": [{"type": "text", "text": "User reply"}],
                        },
                    ],
                }
            ],
        )
    assert detail(client, task)["async_questions"][0]["state"] == "answered"
    assert detail(client, task)["pending_count"] == 0


def test_refresh_restores_unconfirmed_question_without_reopening_dismissed(client):
    task = send_message(client, new_task(client)).json()
    complete(client, task)
    rpc = client.app.state.runtime.rpc
    rpc.threads[task["thread_id"]]["turns"] = [{"id": task["turn_id"], "items": [ITEM]}]
    path = f"/api/tasks/{task['id']}/questions/refresh"
    refreshed = client.post(path, json={})
    assert refreshed.status_code == 200, refreshed.text
    q = refreshed.json()["async_questions"][0]
    assert q["state"] == "unconfirmed"
    assert answer(client, task, q, {"action": "dismiss"}).status_code == 200
    assert client.post(path, json={}).json()["async_questions"][0]["state"] == "dismissed"
    assert detail(client, task)["pending_count"] == 0
    assert answer(client, task, q).status_code == 409


def test_proven_unsent_answer_can_retry_after_turn_finishes(client, monkeypatch):
    from codex_console import attachments

    task = send_message(client, new_task(client)).json()
    q = question(client, task)
    original = attachments.prepare

    def fail(*args):
        raise ConsoleError("execution_failed", 503)

    monkeypatch.setattr(attachments, "prepare", fail)
    assert answer(client, task, q).status_code == 503
    assert detail(client, task)["async_questions"][0]["state"] == "pending"
    with client.app.state.factory() as db:
        assert db.get(Operation, q["id"]).state == "failed"
    complete(client, task)
    monkeypatch.setattr(attachments, "prepare", original)
    response = answer(client, task, q)
    assert response.status_code == 200, response.text
    assert response.json()["async_questions"][0]["state"] == "answered"


@pytest.mark.parametrize(
    "body",
    [
        {"answers": {}},
        {"answers": {"0": []}},
        {"answers": {"0": [""]}},
        {"answers": {"wrong": ["Allow"]}},
    ],
)
def test_requires_complete_answers(client, body):
    task = send_message(client, new_task(client)).json()
    q = question(client, task)
    assert answer(client, task, q, body).status_code == 422
    assert detail(client, task)["async_questions"][0]["state"] == "pending"


def test_question_identity_is_task_scoped_and_replayed_events_are_idempotent(client):
    task = send_message(client, new_task(client)).json()
    q = question(client, task)
    question(client, task)
    other = new_task(client)
    assert answer(client, other, q).status_code == 409
    assert len(detail(client, task)["async_questions"]) == 1
    with client.app.state.factory() as db:
        assert len(list(db.scalars(select(AsyncQuestion)))) == 1
        assert db.get(Operation, q["id"]) is None
