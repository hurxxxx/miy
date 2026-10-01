"""Management is passive; operations and agents use the native session service."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from conftest import PASSWORD, complete, new_task, notify, send_message
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from codex_console import monitor
from codex_console.app import create_app
from codex_console.config import MonitoredService
from codex_console.models import ResourceLease, ServiceObservation, now


def execute(client, task):
    return client.post(
        f"/api/tasks/{task['id']}/implement",
        json={"text": "Inspect the repository", "operation_id": str(uuid4())},
    )


def child(client, task, *, announce=True):
    thread_id = str(uuid4())
    thread = {
        "id": thread_id,
        "parentThreadId": task["thread_id"],
        "cwd": task["root"],
        "agentNickname": "Inspector",
        "agentRole": "explorer",
        "status": {"type": "active", "activeFlags": []},
        "turns": [{"id": "child-turn", "status": "inProgress", "items": []}],
    }
    client.app.state.runtime.rpc.threads[thread_id] = thread
    if announce:
        client.portal.call(
            client.app.state.runtime.on_message,
            {
                "method": "thread/started",
                "params": {"thread": thread},
            },
        )
    return thread


def test_parallel_readers_capacity_and_writer_exclusion(client):
    tasks = [new_task(client) for _ in range(4)]
    running = [send_message(client, t).json() for t in tasks[:3]]
    assert all(t["status"] == "running" for t in running)
    assert send_message(client, tasks[3]).json()["code"] == "capacity_busy"
    complete(client, running[0])
    assert execute(client, tasks[3]).json()["code"] == "workspace_busy"
    assert send_message(client, tasks[3]).status_code == 200


def test_isolated_writers_and_operations_serialization(client):
    tasks = [
        client.post(
            "/api/tasks",
            json={
                "title": "isolated",
                "isolate": True,
                "context": {"purpose": "deployment"},
            },
        ).json()
        for _ in range(2)
    ]
    assert tasks[0]["root"] != tasks[1]["root"]
    first = execute(client, tasks[0]).json()
    assert first["status"] == "running"
    assert execute(client, tasks[1]).json()["code"] == "operations_busy"
    complete(client, first)
    assert execute(client, tasks[1]).status_code == 200


def test_child_keeps_lease_after_root_completion_and_is_stoppable(client):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task)
    complete(client, task)
    with client.app.state.factory() as db:
        assert db.scalar(select(ResourceLease).where(ResourceLease.task_id == task["id"]))
    assert client.post(f"/api/tasks/{task['id']}/interrupt", json={}).status_code == 200
    assert (
        "turn/interrupt",
        {"threadId": thread["id"], "turnId": "child-turn"},
    ) in client.app.state.runtime.rpc.calls
    notify(
        client,
        task,
        "turn/completed",
        {
            "threadId": thread["id"],
            "turnId": "child-turn",
            "turn": {"id": "child-turn", "status": "interrupted"},
        },
    )
    with client.app.state.factory() as db:
        assert not db.scalar(select(ResourceLease).where(ResourceLease.task_id == task["id"]))


def test_child_approval_discovered_without_started_event_and_routed_by_rpc_id(client):
    task = execute(client, new_task(client)).json()
    thread = child(client, task, announce=False)
    client.portal.call(
        client.app.state.runtime.on_message,
        {
            "id": "child-approval",
            "method": "item/commandExecution/requestApproval",
            "params": {
                "threadId": thread["id"],
                "turnId": "child-turn",
                "itemId": "command",
                "command": "git status",
            },
        },
    )
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert detail["pending_count"] == 1
    assert detail["requests"][0]["payload"]["threadId"] == thread["id"]
    request = detail["requests"][0]
    assert (
        client.post(
            f"/api/tasks/{task['id']}/requests/{request['id']}", json={"decision": "accept"}
        ).status_code
        == 200
    )
    assert ("child-approval", {"decision": "accept"}) in client.app.state.runtime.rpc.responses
    assert client.get(f"/api/tasks/{task['id']}").json()["pending_count"] == 0


def test_foreign_child_cannot_attach_or_request_approval(client):
    task = execute(client, new_task(client)).json()
    thread = child(client, task, announce=False)
    thread["cwd"] = "/unrelated"
    client.portal.call(
        client.app.state.runtime.on_message,
        {
            "id": "foreign",
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": thread["id"], "turnId": "child-turn"},
        },
    )
    assert client.get(f"/api/tasks/{task['id']}").json()["pending_count"] == 0
    assert ("foreign", {"decision": "decline"}) in client.app.state.runtime.rpc.responses


def test_reconcile_discovers_descendants_without_resuming_them(client, monkeypatch):
    task = send_message(client, new_task(client)).json()
    thread = child(client, task, announce=False)
    rpc = client.app.state.runtime.rpc
    original = rpc.call

    async def call(method, params):
        if method == "thread/list":
            return {"data": [thread], "nextCursor": None}
        return await original(method, params)

    monkeypatch.setattr(rpc, "call", call)
    before = len(rpc.calls)
    client.portal.call(client.app.state.runtime.refresh_agents, task["id"])
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert any(
        a["thread_id"] == thread["id"] and a["turn_id"] == "child-turn" for a in detail["agents"]
    )
    assert not any(m == "thread/resume" for m, _ in rpc.calls[before:])


@pytest.mark.parametrize("client_role", ["session"], indirect=True)
def test_management_survives_session_disconnect_without_creating_runtime(
    client, settings, monkeypatch
):
    original = httpx.AsyncClient

    def unavailable(request):
        raise httpx.ConnectError("Test session listener is stopped", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(unavailable), **kwargs),
    )
    task = send_message(client, new_task(client)).json()
    management = create_app(settings, role="management")
    with TestClient(management, base_url=settings.origin) as browser:
        browser.headers["origin"] = settings.origin
        assert browser.post("/api/session", json={"password": PASSWORD}).status_code == 200
        client.portal.call(client.app.state.runtime.on_disconnect)
        assert browser.get("/healthz").status_code == 200
        assert browser.get("/api/overview").json()[0]["status"] == "uncertain"
        assert browser.get("/api/monitor/services").status_code == 200
        assert browser.get(f"/api/tasks/{task['id']}").status_code == 503
        assert not hasattr(management.state, "runtime")


def test_monitor_stale_data_is_unknown(client, settings):
    with client.app.state.factory.begin() as db:
        row = db.get(ServiceObservation, "console-session")
        row.status, row.version, row.checked_at = "healthy", "v1", now() - timedelta(minutes=1)
    result = monitor.snapshot(settings, client.app.state.factory)[0]
    assert result["status"] == "unknown" and result["stale"]
    assert result["version"] == "v1"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/healthz",
        "http://169.254.169.254/",
        "file:///etc/passwd",
        "http://127.0.0.1/?token=secret",
        "http://user:pass@127.0.0.1/",
    ],
)
def test_monitor_rejects_unbounded_targets(url):
    with pytest.raises(ValidationError):
        MonitoredService(id="test", name="test", environment="dev", health_url=url)


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            httpx.Response(302, headers={"location": "http://169.254.169.254/"}),
            ("unavailable", None),
        ),
        (httpx.Response(200, content=b"x" * 16385), ("unknown", None)),
        (httpx.Response(200, json={"version": "v2"}), ("healthy", "v2")),
        (httpx.Response(200, json={"version": "secret with spaces"}), ("healthy", None)),
    ],
)
def test_monitor_redirects_size_and_version_boundaries(response, expected):
    service = MonitoredService(
        id="test", name="test", environment="dev", health_url="http://127.0.0.1/healthz"
    )
    calls = []

    def handler(request):
        calls.append(request.url)
        return response

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        ) as http:
            return await monitor.probe(service, http)

    assert asyncio.run(run()) == expected
    assert len(calls) == 1


def test_official_skill_input_uses_server_discovery(client, monkeypatch):
    task = new_task(client)
    rpc = client.portal.call(client.app.state.runtime.authenticated_rpc)
    original = rpc.call

    async def call(method, params):
        if method == "skills/list":
            return {
                "data": [
                    {
                        "cwd": task["root"],
                        "skills": [{"name": "inspect", "path": "/safe/SKILL.md", "enabled": True}],
                    }
                ]
            }
        return await original(method, params)

    monkeypatch.setattr(rpc, "call", call)
    body = {
        "text": "Inspect",
        "stage": "plan",
        "operation_id": str(uuid4()),
        "skill_names": ["inspect"],
    }
    assert client.post(f"/api/tasks/{task['id']}/messages", json=body).status_code == 200
    inputs = next(p["input"] for m, p in rpc.calls if m == "turn/start")
    assert {"type": "skill", "name": "inspect", "path": "/safe/SKILL.md"} in inputs


def test_child_approval_after_parent_completion_preserves_execution_authority(client):
    task = execute(client, new_task(client)).json()
    thread = child(client, task)
    complete(client, task)
    client.portal.call(
        client.app.state.runtime.on_message,
        {
            "id": "late-child",
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": thread["id"], "turnId": "child-turn", "itemId": "command"},
        },
    )
    current = client.get(f"/api/tasks/{task['id']}").json()
    assert current["status"] == "idle" and current["pending_count"] == 1
    request_id = current["requests"][0]["id"]
    assert (
        client.post(
            f"/api/tasks/{task['id']}/requests/{request_id}", json={"decision": "accept"}
        ).status_code
        == 200
    )


def test_management_migration_preserves_tasks_approvals_and_active_lease(client, legacy_database):
    from importlib.util import module_from_spec, spec_from_file_location

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    from codex_console.cli import ROOT

    task = send_message(client, new_task(client)).json()
    spec = spec_from_file_location(
        "management_migration", ROOT / "migrations/versions/0009_management.py"
    )
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = legacy_database()
    with engine.connect() as connection, connection.begin() as transaction:
        connection.execute(
            text("DROP TABLE console_agents, console_service_observations, console_resource_leases")
        )
        connection.execute(
            text("ALTER TABLE console_tasks DROP COLUMN context, DROP COLUMN pinned")
        )
        connection.execute(text("ALTER TABLE console_requests DROP COLUMN thread_id"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        row = connection.execute(
            text("SELECT title, thread_id, pinned FROM console_tasks WHERE id=:id"),
            {"id": task["id"]},
        ).one()
        assert tuple(row) == (task["title"], task["thread_id"], False)
        lease = connection.execute(
            text("SELECT resource, exclusive FROM console_resource_leases WHERE task_id=:id"),
            {"id": task["id"]},
        ).one()
        assert tuple(lease) == ("workspace:" + task["root"], True)
        transaction.rollback()


def test_restart_marks_completed_parent_with_live_child_uncertain(client):
    from codex_console import store

    task = execute(client, new_task(client)).json()
    child(client, task)
    complete(client, task)
    store.recover_startup(client.app.state.factory)
    current = client.get(f"/api/tasks/{task['id']}").json()
    assert current["status"] == "uncertain"
    assert current["error_code"] == "runtime_restarted"
    assert any(a["parent_thread_id"] and a["status"] == "systemError" for a in current["agents"])
    with client.app.state.factory() as db:
        assert db.scalar(select(ResourceLease).where(ResourceLease.task_id == task["id"]))


def test_stale_root_turn_does_not_replace_agent_projection(client):
    task = send_message(client, new_task(client)).json()
    notify(client, task, "turn/started", {"turnId": "old-turn", "turn": {"id": "old-turn"}})
    current = client.get(f"/api/tasks/{task['id']}").json()
    assert current["agents"][0]["turn_id"] == task["turn_id"]
    assert current["status"] == "running"
