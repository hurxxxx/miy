"""Native observations are evidence, never execution authority."""

from copy import copy, deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import complete, new_task, notify, send_message
from sqlalchemy import MetaData, select, text
from test_management import child

from codex_console import store
from codex_console.auth import COOKIE
from codex_console.cli import migrate
from codex_console.errors import ConsoleError
from codex_console.models import Agent, ResourceLease, Task, database, now
from codex_console.runtime import Runtime


def refresh(client, task):
    client.portal.call(client.app.state.runtime.refresh_agents, task["id"])


def agent(client, task, thread_id=None):
    rows = client.get(f"/api/tasks/{task['id']}/agents").json()
    return next(row for row in rows if row["thread_id"] == (thread_id or task["thread_id"]))


def test_quiet_root_is_checked_without_history_resume_or_execution_changes(client):
    task = send_message(client, new_task(client)).json()
    rpc = client.app.state.runtime.rpc
    rpc.threads[task["thread_id"]]["status"] = {"type": "active", "activeFlags": []}
    before = client.get(f"/api/tasks/{task['id']}").json()
    rpc.calls.clear()
    refresh(client, task)
    observed = agent(client, task)["observation"]
    assert observed["thread_status"] == "active"
    assert observed["freshness"] == "fresh" and observed["error_code"] is None
    assert observed["last_turn"]["id"] == task["turn_id"]
    assert observed["last_turn"]["status"] == "inProgress"
    assert ("thread/read", {"threadId": task["thread_id"], "includeTurns": False}) in rpc.calls
    assert {method for method, _ in rpc.calls} <= {"thread/read", "thread/list"}
    after = client.get(f"/api/tasks/{task['id']}").json()
    assert (after["status"], after["updated_at"], after["turn_id"]) == (
        before["status"],
        before["updated_at"],
        before["turn_id"],
    )
    with client.app.state.factory() as db:
        assert db.scalar(select(ResourceLease).where(ResourceLease.task_id == task["id"]))


def test_child_list_success_cannot_erase_direct_read_failure(client, monkeypatch):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task)
    refresh(client, task)
    checked = agent(client, task, thread["id"])["observation"]["thread_checked_at"]
    rpc = client.app.state.runtime.rpc
    original = rpc.call

    async def call(method, params):
        if method == "thread/list":
            return {"data": [thread], "nextCursor": None}
        if method == "thread/read" and params["threadId"] == thread["id"]:
            raise ConsoleError("raw-private-native-failure")
        return await original(method, params)

    monkeypatch.setattr(rpc, "call", call)
    for _ in range(2):
        with pytest.raises(ConsoleError):
            refresh(client, task)
        observation = agent(client, task, thread["id"])["observation"]
        assert observation["thread_checked_at"] == checked
        assert observation["error_code"] == "read_failed"
        assert observation["freshness"] == "unavailable"
        assert "raw-private" not in str(observation)
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"


def test_last_completed_turn_survives_not_loaded_and_disconnect(client):
    task = send_message(client, new_task(client)).json()
    complete(client, task)
    rpc = client.app.state.runtime.rpc
    rpc.threads[task["thread_id"]]["status"] = {"type": "notLoaded"}
    refresh(client, task)
    row = agent(client, task)
    assert row["status"] == "completed"
    assert row["observation"]["thread_status"] == "notLoaded"
    assert row["observation"]["last_turn"]["status"] == "completed"
    client.portal.call(client.app.state.runtime.on_disconnect)
    observed = agent(client, task)["observation"]
    assert observed["freshness"] == "unavailable"
    assert observed["thread_status"] == "notLoaded"
    assert observed["last_turn"] == row["observation"]["last_turn"]
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "idle"


def test_legacy_rows_unknown_and_elapsed_observation_does_not_fail_execution(client):
    task = send_message(client, new_task(client)).json()
    with client.app.state.factory.begin() as db:
        db.get(Agent, task["thread_id"]).observation = None
    assert agent(client, task)["observation"] is None
    refresh(client, task)
    with client.app.state.factory.begin() as db:
        row = db.get(Agent, task["thread_id"])
        row.observation = {
            **row.observation,
            "thread_checked_at": (now() - timedelta(seconds=31)).isoformat(),
        }
    assert agent(client, task)["observation"]["freshness"] == "stale"
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"


def test_late_metadata_response_from_replaced_rpc_is_ignored(client, monkeypatch):
    task = send_message(client, new_task(client)).json()
    runtime = client.app.state.runtime
    refresh(client, task)
    previous = deepcopy(agent(client, task)["observation"])
    rpc = runtime.rpc
    original = rpc.call

    async def call(method, params):
        response = await original(method, params)
        if method == "thread/read":
            rpc.generation = "replacement-generation"
            response = {"thread": {**response["thread"], "status": {"type": "notLoaded"}}}
        return response

    monkeypatch.setattr(rpc, "call", call)
    refresh(client, task)
    assert agent(client, task)["observation"] == previous
    with client.app.state.factory() as db:
        assert db.get(Task, task["id"]).runtime_generation != rpc.generation


def test_startup_invalidates_completed_observation_without_changing_result(client):
    task = send_message(client, new_task(client)).json()
    complete(client, task)
    refresh(client, task)
    before = client.get(f"/api/tasks/{task['id']}").json()
    store.recover_startup(client.app.state.factory)
    after = client.get(f"/api/tasks/{task['id']}").json()
    assert after["agents"][0]["observation"]["freshness"] == "unavailable"
    assert after["agents"][0]["observation"]["last_turn"]["status"] == "completed"
    assert after["updated_at"] == before["updated_at"]


@pytest.mark.parametrize("payload", [None, [], {"thread": None}, {"thread": []}])
def test_malformed_root_metadata_records_failure_without_disrupting_execution(
    client, monkeypatch, payload
):
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    previous = agent(client, task)["observation"]
    rpc = client.app.state.runtime.rpc
    original = rpc.call

    async def call(method, params):
        if method == "thread/read":
            return payload
        return await original(method, params)

    monkeypatch.setattr(rpc, "call", call)
    refresh(client, task)
    observed = agent(client, task)["observation"]
    assert observed["error_code"] == "read_failed"
    assert observed["thread_checked_at"] == previous["thread_checked_at"]
    assert observed["last_turn"] == previous["last_turn"]
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"status": {"type": "new-unknown-state"}}, "read_failed"),
        ({"id": "foreign-thread"}, "identity_mismatch"),
        ({"cwd": "/foreign-root"}, "identity_mismatch"),
        ({"parentThreadId": "foreign-parent"}, "identity_mismatch"),
        ({"sessionId": "foreign-session"}, "identity_mismatch"),
    ],
)
def test_invalid_root_observation_cannot_replace_last_good_status(client, change, error):
    task = send_message(client, new_task(client)).json()
    rpc = client.app.state.runtime.rpc
    rpc.threads[task["thread_id"]]["sessionId"] = "owned-session"
    with client.app.state.factory.begin() as db:
        db.get(Agent, task["thread_id"]).session_id = "owned-session"
    refresh(client, task)
    previous = agent(client, task)["observation"]
    rpc.threads[task["thread_id"]].update(change)
    refresh(client, task)
    observed = agent(client, task)["observation"]
    assert observed["error_code"] == error
    assert observed["thread_checked_at"] == previous["thread_checked_at"]
    assert observed["last_turn"] == previous["last_turn"]


def test_native_status_event_retains_failed_read_until_verified_direct_success(client):
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    with client.app.state.factory.begin() as db:
        row = db.get(Agent, task["thread_id"])
        row.observation = {**row.observation, "error_code": "read_failed"}
    notify(client, task, "thread/status/changed", {"status": {"type": "notLoaded"}})
    observed = agent(client, task)["observation"]
    assert observed["thread_status"] == "notLoaded"
    assert observed["freshness"] == "unavailable" and observed["error_code"] == "read_failed"
    refresh(client, task)
    assert agent(client, task)["observation"]["error_code"] is None


def test_old_generation_event_and_disconnect_cannot_overwrite_reconnected_observation(client):
    task = send_message(client, new_task(client)).json()
    runtime = client.app.state.runtime
    rpc = runtime.rpc
    old_generation = rpc.generation
    rpc.generation = "new-generation"
    refresh(client, task)
    previous = agent(client, task)["observation"]

    async def late():
        await runtime.on_message(
            {
                "method": "thread/status/changed",
                "params": {"threadId": task["thread_id"], "status": {"type": "systemError"}},
            },
            generation=old_generation,
        )
        await runtime.on_disconnect(generation=old_generation)

    client.portal.call(late)
    assert agent(client, task)["observation"] == previous


def test_reconnect_marks_previous_generation_unavailable_before_new_native_query(client):
    task = send_message(client, new_task(client)).json()
    complete(client, task)
    refresh(client, task)
    runtime = client.app.state.runtime
    runtime.rpc.connected = False
    rpc = client.portal.call(runtime.connect)
    assert rpc.calls == []
    assert agent(client, task)["observation"]["freshness"] == "unavailable"


@pytest.mark.parametrize("phase", ["thread/list", "child/read"])
def test_connection_replaced_during_discovery_cannot_persist_stale_child(
    client, monkeypatch, phase
):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task)
    refresh(client, task)
    runtime = client.app.state.runtime
    rpc = runtime.rpc
    original = rpc.call
    before = agent(client, task, thread["id"])

    async def call(method, params):
        if method == "thread/list":
            if phase == method:
                rpc.generation = "new-generation"
            return {"data": [{**thread, "status": {"type": "systemError"}}], "nextCursor": None}
        result = await original(method, params)
        if phase == "child/read" and params.get("threadId") == thread["id"]:
            rpc.generation = "new-generation"
            return {"thread": {**thread, "status": {"type": "notLoaded"}}}
        return result

    monkeypatch.setattr(rpc, "call", call)
    refresh(client, task)
    after = agent(client, task, thread["id"])
    assert after["observation"] == before["observation"]
    if phase == "thread/list":
        assert after == before


def test_observation_disconnect_scope_does_not_cross_executor_or_remote_runtime(client):
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    runtime = client.app.state.runtime
    with client.app.state.factory.begin() as db:
        evidence = deepcopy(db.get(Agent, task["thread_id"]).observation)
        for name, executor, context in (
            ("template", "templates", None),
            ("remote", "session", {"source_binding": {"app_id": "sample"}}),
        ):
            db.add(Task(id=name, title=name, root=task["root"], executor=executor, context=context))
            db.flush()
            db.add(Agent(thread_id=name, task_id=name, observation=evidence))
    runtime.invalidate_observations()
    with client.app.state.factory() as db:
        assert db.get(Agent, task["thread_id"]).observation["error_code"] == "unavailable"
        assert db.get(Agent, "template").observation["error_code"] is None
        assert db.get(Agent, "remote").observation["error_code"] is None
    remote = Runtime(runtime.settings, runtime.factory, remote_task_id="remote")
    remote.invalidate_observations()
    with client.app.state.factory() as db:
        assert db.get(Agent, "remote").observation["error_code"] == "unavailable"
        assert db.get(Agent, "template").observation["error_code"] is None


def test_observation_is_available_without_browser_event_stream_and_session_cookie(client):
    # The periodic native projection is independent of an SSE subscriber. Closing
    # this browser's authentication does not imply native execution disconnection.
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    client.cookies.clear()
    assert client.get(f"/api/tasks/{task['id']}/agents").status_code == 401
    refresh(client, task)
    with client.app.state.factory() as db:
        assert store.agent_list(db, task["id"])[0]["observation"]["freshness"] == "fresh"
        assert db.get(Task, task["id"]).status == "running"


def test_closing_browser_sse_iterator_does_not_disconnect_native_observation(client):
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    before = agent(client, task)["observation"]
    endpoint = next(
        route.endpoint
        for route in client.app.routes
        if getattr(route, "path", None) == "/api/tasks/{task_id}/events"
    )

    async def connected():
        return False

    async def open_and_close():
        request = SimpleNamespace(
            headers={}, cookies={COOKIE: client.cookies[COOKIE]}, is_disconnected=connected
        )
        response = await endpoint(request, task["id"], after=0)
        assert "event: changed" in await anext(response.body_iterator)
        await response.body_iterator.aclose()

    client.portal.call(open_and_close)
    assert client.app.state.runtime.rpc.connected
    assert agent(client, task)["observation"] == before
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"


def test_schema_seven_preserves_prior_agents_and_does_not_infer_observations(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "legacy.sqlite3")
    migrate(url, revision="console_sqlite_0006")
    engine, factory = database(url)
    try:
        legacy = MetaData()
        legacy.reflect(engine)
        with factory.begin() as db:
            db.add(Task(id="saved-task", title="Saved", root=str(tmp_path), status="idle"))
            db.flush()
            db.execute(
                legacy.tables["console_agents"]
                .insert()
                .values(
                    thread_id="saved-thread",
                    task_id="saved-task",
                    name="Codex",
                    status="completed",
                    flags=[],
                    turn_id="saved-turn",
                    updated_at=now(),
                )
            )
        migrate(url)
        migrate(url)
        with factory() as db:
            row = db.get(Agent, "saved-thread")
            assert row.status == "completed" and row.turn_id == "saved-turn"
            assert row.observation is None
            assert db.scalar(text("PRAGMA integrity_check")) == "ok"
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("turns", [None, [None], [{}], [{"id": "bad", "status": "unknown"}]])
def test_invalid_child_turn_evidence_preserves_observation_and_execution(client, turns):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task)
    refresh(client, task)
    before = agent(client, task, thread["id"])["observation"]
    thread["turns"] = turns
    with pytest.raises(ConsoleError, match="thread_unavailable"):
        refresh(client, task)
    observed = agent(client, task, thread["id"])["observation"]
    assert observed["error_code"] == "read_failed"
    assert observed["thread_checked_at"] == before["thread_checked_at"]
    assert observed["last_turn"] == before["last_turn"]
    assert agent(client, task, thread["id"])["status"] == "active"


def test_same_generation_different_rpc_object_cannot_publish_a_late_response(client, monkeypatch):
    task = send_message(client, new_task(client)).json()
    refresh(client, task)
    runtime = client.app.state.runtime
    before = agent(client, task)["observation"]
    original = runtime.rpc.call

    async def call(method, params):
        result = await original(method, params)
        if method == "thread/read":
            runtime.rpc = copy(runtime.rpc)
        return result

    monkeypatch.setattr(runtime.rpc, "call", call)
    refresh(client, task)
    assert agent(client, task)["observation"] == before


def test_prior_turn_completion_cannot_replace_the_last_observed_turn(client):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task)
    notify(
        client,
        task,
        "turn/started",
        {
            "threadId": thread["id"],
            "turnId": "current-turn",
            "turn": {"id": "current-turn", "status": "inProgress"},
        },
    )
    before = agent(client, task, thread["id"])["observation"]["last_turn"]
    notify(
        client,
        task,
        "turn/completed",
        {
            "threadId": thread["id"],
            "turnId": "previous-turn",
            "turn": {"id": "previous-turn", "status": "completed"},
        },
    )
    assert agent(client, task, thread["id"])["observation"]["last_turn"] == before
