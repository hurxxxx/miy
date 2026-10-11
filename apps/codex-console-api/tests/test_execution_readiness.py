"""Project connection metadata is bounded observation, not native authority."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread, local
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from test_app_sources import app_checkout as app_checkout
from test_app_sources import bind
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from codex_console import execution_readiness, executor_probe
from codex_console.models import AppSourceBinding, Task


@pytest.fixture
def project(client, app_checkout):
    response = client.post(
        "/api/workbench/projects",
        json={
            "app_id": "sample-app",
            "title": "Synthetic app project",
            "summary": "Build one independent app",
            "reuse_decision": "new",
            "reuse_notes": "Existing apps do not meet this synthetic need",
        },
    )
    assert response.status_code == 200
    assert bind(client, app_checkout).status_code == 200
    return response.json()


def endpoint(project):
    return f"/api/workbench/projects/{project['id']}/execution-readiness"


def assert_no_task_or_native_effects(client):
    with client.app.state.factory() as db:
        assert list(db.scalars(select(Task))) == []
    runtime = client.app.state.runtime
    assert runtime.rpc is None
    assert not runtime.app_runtimes


@contextmanager
def metadata_server(root, *, version="0.160.1", cwd=None, pause=None, release=None):
    messages = []

    def handler(socket):
        try:
            message = json.loads(socket.recv())
            messages.append(message["method"])
            assert message["method"] == "initialize"
            if pause:
                pause.set()
                assert release.wait(5)
            socket.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "result": {
                            "environmentInfo": {
                                "executorVersion": version,
                                "cwd": cwd or root.as_uri(),
                                "platformOs": "linux",
                            }
                        },
                    }
                )
            )
            messages.append(json.loads(socket.recv())["method"])
        except ConnectionClosed:
            pass

    with serve(handler, "127.0.0.1", 0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}", messages
        finally:
            server.shutdown()
            thread.join(3)
            assert not thread.is_alive()


def configure(settings, url):
    settings.app_execution_environments[0] = settings.app_execution_environments[0].model_copy(
        update={"exec_server_url": url}
    )


@pytest.mark.parametrize(
    "version,cwd,state,code",
    [
        ("0.160.1", None, "reachable", None),
        ("0.160.0", None, "unsupported", "app_executor_version_mismatch"),
        ("0.160.1", "file:///synthetic-unmatched-source", "changed", "app_executor_changed"),
    ],
)
def test_actual_loopback_metadata_uses_existing_pinned_protocol_without_effects(
    client, settings, app_checkout, project, monkeypatch, version, cwd, state, code
):
    statements = []
    engine = client.app.state.factory.kw["bind"]
    scope = local()
    original_select = execution_readiness._select

    def read_scope(*args):
        scope.active = True
        try:
            return original_select(*args)
        finally:
            scope.active = False

    monkeypatch.setattr(execution_readiness, "_select", read_scope)

    def observe_sql(connection, cursor, statement, *args):
        if getattr(scope, "active", False):
            statements.append(statement.split(None, 1)[0].upper())

    with metadata_server(app_checkout, version=version, cwd=cwd) as (url, messages):
        configure(settings, url)
        event.listen(engine, "before_cursor_execute", observe_sql)
        try:
            response = client.get(endpoint(project))
        finally:
            event.remove(engine, "before_cursor_execute", observe_sql)
    assert response.status_code == 200
    data = response.json()
    assert data["checked_at"].endswith("Z")
    assert data["state"] == state and data["failure_code"] == code
    assert data["source_version"] == 1 and data["app_id"] == project["app_id"]
    assert messages == (["initialize", "initialized"] if state == "reachable" else ["initialize"])
    assert statements and set(statements) <= {"SELECT", "PRAGMA", "BEGIN"}
    assert url not in response.text and "synthetic-executor-token" not in response.text
    assert_no_task_or_native_effects(client)


@pytest.mark.parametrize("change", ["unconfigured", "invalid_source", "denied_source"])
def test_current_source_and_operator_configuration_are_required_before_connect(
    client, settings, app_checkout, project, monkeypatch, change
):
    if change == "unconfigured":
        settings.app_execution_environments.clear()
    elif change == "invalid_source":
        (app_checkout / "app.manifest.json").write_text("malformed")
    else:
        settings.app_source_roots.clear()

    async def no_connect(*args):
        pytest.fail("current invalid selection attempted executor connection")

    monkeypatch.setattr(executor_probe, "preflight", no_connect)
    response = client.get(endpoint(project))
    assert response.status_code == 200
    assert (
        response.json()["state"]
        == {
            "unconfigured": "unconfigured",
            "invalid_source": "unavailable",
            "denied_source": "denied",
        }[change]
    )
    assert_no_task_or_native_effects(client)


@pytest.mark.parametrize("change", ["binding", "environment", "credential", "manifest"])
def test_change_during_actual_metadata_wait_discards_old_success(
    client, settings, app_checkout, project, change
):
    pause, release = Event(), Event()
    with metadata_server(app_checkout, pause=pause, release=release) as (url, messages):
        configure(settings, url)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.get, endpoint(project))
            try:
                assert pause.wait(3)
                if change == "binding":
                    with client.app.state.factory.begin() as db:
                        db.get(AppSourceBinding, "sample-app").version += 1
                elif change == "manifest":
                    path = app_checkout / "app.manifest.json"
                    value = json.loads(path.read_text())
                    value["display"]["name"] = "Changed synthetic display"
                    path.write_text(json.dumps(value))
                else:
                    fields = (
                        {"key": "changed-environment"}
                        if change == "environment"
                        else {"auth_bearer_token": "synthetic-new-capability-" + "y" * 32}
                    )
                    # Validate SecretStr and configuration as an operator would.
                    original = settings.app_execution_environments[0]
                    value = original.model_dump()
                    value.update(fields)
                    settings.app_execution_environments[0] = type(original).model_validate(value)
            finally:
                release.set()
            response = future.result(timeout=6)
    assert response.status_code == 200
    assert response.json()["state"] == "changed"
    assert response.json()["failure_code"] == "app_executor_changed"
    assert messages == ["initialize", "initialized"]
    assert_no_task_or_native_effects(client)


def test_peer_and_transport_details_never_become_public_status(client, project, monkeypatch):
    async def fail(environment):
        raise OSError("synthetic-private-endpoint/raw-peer/token-detail")

    monkeypatch.setattr(executor_probe, "preflight", fail)
    response = client.get(endpoint(project))
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"
    assert response.json()["failure_code"] == "app_executor_unavailable"
    assert "synthetic-private" not in response.text
    assert_no_task_or_native_effects(client)


def test_configured_but_actual_closed_endpoint_is_unavailable_without_creating_task(
    client, settings, app_checkout, project
):
    with metadata_server(app_checkout) as (url, messages):
        configure(settings, url)
    # The configured endpoint has been closed; no shared service is contacted.
    assert (
        client.get("/api/workbench/catalog").json()["items"][0]["execution_status"] == "configured"
    )
    response = client.get(endpoint(project))
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"
    assert messages == []
    assert_no_task_or_native_effects(client)


def test_metadata_reply_does_not_replace_current_task_session_authority(
    client, settings, app_checkout, project
):
    pause, release = Event(), Event()
    with metadata_server(app_checkout, pause=pause, release=release) as (url, messages):
        configure(settings, url)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.get, endpoint(project))
            try:
                assert pause.wait(3)
                assert client.delete("/api/session").status_code == 200
            finally:
                release.set()
            response = future.result(timeout=6)
    # Historical connection observation is not a reusable authenticated permit.
    assert response.status_code == 200 and response.json()["state"] == "reachable"
    assert messages == ["initialize", "initialized"]
    assert (
        client.post(
            "/api/tasks",
            json={"title": "Denied after logout", "context": {"project_id": project["id"]}},
        ).status_code
        == 401
    )
    assert_no_task_or_native_effects(client)


def test_unknown_or_unauthenticated_project_cannot_observe_an_executor(client, project):
    assert client.get(endpoint({"id": str(uuid4())})).status_code == 404
    assert client.delete("/api/session").status_code == 200
    assert client.get(endpoint(project)).status_code == 401


def test_unconnected_project_is_observation_only_and_existing_planning_flow_still_works(
    client, app_checkout
):
    result = client.post(
        "/api/workbench/projects",
        json={
            "app_id": "sample-app",
            "title": "Synthetic planning project",
            "summary": "Plan one app",
            "reuse_decision": "new",
            "reuse_notes": "Need a new app",
        },
    )
    assert result.status_code == 200
    project = result.json()
    response = client.get(endpoint(project))
    assert response.json()["state"] == "unconfigured"
    assert response.json()["failure_code"] == "app_source_unavailable"
    assert_no_task_or_native_effects(client)
    task = client.post(
        "/api/tasks",
        json={"title": "Read-only setup plan", "context": {"project_id": project["id"]}},
    )
    assert (
        task.status_code == 200
        and task.json()["context"]["app_execution_boundary"] == "planning_only"
    )
