import json
from datetime import UTC, datetime

import pytest
from conftest import complete, new_task, notify, send_message
from sqlalchemy import select, text

from codex_console import store
from codex_console.cli import migrate
from codex_console.models import Event, Task, database


def history(client, task, **params):
    response = client.get(f"/api/tasks/{task['id']}/history", params=params)
    assert response.status_code == 200
    return response.json()


def test_progress_snapshots_and_command_evidence_survive_completion(client):
    task = new_task(client)
    task = send_message(client, task).json()
    for state in ("inProgress", "completed"):
        notify(
            client,
            task,
            "turn/plan/updated",
            {
                "plan": [{"step": "Review contracts", "status": state}],
                "explanation": "Check compatibility",
            },
        )
    command = {
        "id": "check",
        "type": "commandExecution",
        "command": "python -m unittest",
        "status": "completed",
        "exitCode": 1,
        "aggregatedOutput": "Do not duplicate this output",
    }
    notify(client, task, "item/completed", {"item": command})
    complete(client, task)
    rows = history(client, task)["items"]
    steps = [row["details"]["steps"] for row in rows if row["event"] == "turn/plan/updated"]
    assert [step[0]["status"] for step in steps] == ["completed", "inProgress"]
    event = next(row for row in rows if row["details"] and row["details"].get("item_id") == "check")
    assert event["details"]["exit_code"] == 1 and event["details"]["command"] == command["command"]
    assert "aggregatedOutput" not in event["details"]
    assert "Do not duplicate this output" not in json.dumps(rows)
    assert all(datetime.fromisoformat(row["created_at"]).tzinfo == UTC for row in rows)
    assert len(history(client, task, category="tools")["items"]) == 1


@pytest.mark.parametrize("delivery_fails", [False, True])
def test_response_history_distinguishes_sending_from_confirmed_delivery(
    client, monkeypatch, delivery_fails
):
    task = send_message(client, new_task(client)).json()
    runtime = client.app.state.runtime
    client.portal.call(
        runtime.server_request,
        {
            "id": 81,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": task["thread_id"],
                "turnId": task["turn_id"],
                "questions": [
                    {"id": "scope", "header": "Scope", "question": "Which change?", "options": []}
                ],
            },
        },
    )
    request = client.get(f"/api/tasks/{task['id']}").json()["requests"][0]
    if delivery_fails:
        from codex_console.errors import ConsoleError

        async def fail(*args):
            raise ConsoleError("codex_disconnected")

        monkeypatch.setattr(runtime.rpc, "respond", fail)
    response = client.post(
        f"/api/tasks/{task['id']}/requests/{request['id']}",
        json={"answers": {"scope": ["A private user answer"]}},
    )
    assert response.status_code == (409 if delivery_fails else 200)
    rows = history(client, task, category="requests")["items"]
    events = [row["event"] for row in rows]
    assert "request.answered" in events
    assert ("request.sent" in events) is not delivery_fails
    assert "A private user answer" not in json.dumps(rows)
    assert all(row["details"]["request_kind"] == "question" for row in rows)


def test_history_cursor_is_task_scoped_and_stable_when_new_events_arrive(client):
    first, second = new_task(client), new_task(client)
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, first["id"])
        for index in range(7):
            selected.status = "running" if index < 6 else "idle"
            store.changed(db, selected, "turn.accepted")
        store.changed(db, db.get(Task, second["id"]), "thread.recovered")
        store.changed(db, selected, "item/agentMessage/delta")
    latest = history(client, first, limit=3)
    with client.app.state.factory.begin() as db:
        store.changed(db, db.get(Task, first["id"]), "turn/completed")
    older = history(client, first, before=latest["next_before"], limit=3)
    assert not {row["id"] for row in latest["items"]} & {row["id"] for row in older["items"]}
    assert all(row["id"] < latest["next_before"] for row in older["items"])
    assert not any(row["event"] == "thread.recovered" for row in latest["items"] + older["items"])
    assert not any(
        row["event"] == "item/agentMessage/delta" for row in history(client, first)["items"]
    )
    assert client.get(f"/api/tasks/{first['id']}/history", params={"limit": 101}).status_code == 422
    assert (
        client.get(
            f"/api/tasks/{first['id']}/history", params={"category": "arbitrary"}
        ).status_code
        == 422
    )
    assert client.get("/api/tasks/missing/history").status_code == 404
    client.cookies.clear()
    assert client.get(f"/api/tasks/{first['id']}/history").status_code == 401


def test_upgrade_preserves_existing_events_without_inventing_details(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "history.sqlite3")
    migrate(url, revision="console_sqlite_0009")
    engine, factory = database(url)
    with engine.begin() as db:
        db.execute(
            Task.__table__.insert().values(id="old", title="Existing work", root=str(tmp_path))
        )
        db.execute(
            text(
                "INSERT INTO console_events (task_id, kind, created_at) "
                "VALUES ('old', 'request.sent', '2026-01-01 00:00:00')"
            )
        )
    migrate(url)
    with factory() as db:
        row = db.scalar(select(Event).where(Event.task_id == "old"))
        assert row.kind == "request.sent" and row.details is None
        assert row.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    engine.dispose()


def test_history_bounds_native_detail_without_storing_command_output(client):
    from codex_console import task_history

    data = task_history.native_details(
        "item/completed",
        {
            "item": {
                "id": "long-command",
                "type": "commandExecution",
                "command": "a" * 3000,
                "aggregatedOutput": "private output",
            }
        },
    )
    assert len(data["command"]) == 2000 and data["truncated"] is True
    assert "aggregatedOutput" not in data
    task = new_task(client)
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, task["id"])
        selected.progress = {"steps": [{"step": "x" * 600, "status": "pending"}] * 101}
        store.changed(db, selected, "turn/plan/updated")
    event = history(client, task, category="execution")["items"][0]
    assert event["details"]["truncated"] is True
    assert len(event["details"]["steps"]) == 100


def test_history_keeps_child_progress_without_repeated_root_observations(client):
    from codex_console import agents
    from codex_console.models import Agent

    task = new_task(client)
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, task["id"])
        db.add_all(
            [
                Agent(
                    thread_id="root", task_id=selected.id, name="Root", status="active", flags=[]
                ),
                Agent(
                    thread_id="child",
                    task_id=selected.id,
                    parent_thread_id="root",
                    name="Reviewer",
                    status="active",
                    flags=[],
                ),
            ]
        )
        db.flush()
        params = {"turnId": "turn", "plan": [{"step": "Review contracts", "status": "inProgress"}]}
        agents.project(db, selected, "root", "turn/plan/updated", params)
        agents.project(db, selected, "child", "turn/plan/updated", params)
        agents.project(db, selected, "child", "turn/plan/updated", params)
    rows = history(client, task, category="execution")["items"]
    assert len(rows) == 1 and rows[0]["details"]["agent_name"] == "Reviewer"
    assert rows[0]["details"]["steps"][0]["step"] == "Review contracts"
