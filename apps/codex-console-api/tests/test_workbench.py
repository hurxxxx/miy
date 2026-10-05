import json
from datetime import timedelta

import httpx
import pytest
from conftest import new_task, notify, send_message
from sqlalchemy import select

from codex_console import workbench_sources as sources
from codex_console.models import DevelopmentUsageMonth, Maintenance, WorkbenchObservation, now
from codex_console.workbench_schemas import RuntimeApp, RuntimeOut


@pytest.fixture
def app_catalog(repository):
    path = repository / "packages/contracts/app-contracts.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "apps": [
                    {
                        "app_id": name,
                        "title": name.title(),
                        "route_base": "/apps/" + name,
                        "management": {
                            "summary": "An application",
                            "capabilities": ["planning"],
                            "source_paths": ["hello.txt"],
                            "release_unit": "miy-app",
                        },
                    }
                    for name in ("planner", "docs")
                ]
            }
        )
    )
    return path


def test_catalog_and_project_to_task_preserve_existing_work(client, app_catalog):
    old = new_task(client)
    listed = client.get("/api/workbench/catalog").json()
    assert len(listed["items"]) == 2
    assert listed["source_dirty"]
    body = {
        "app_id": "new-app",
        "title": "New app",
        "summary": "Approval workflow",
        "reuse_decision": "new",
        "reuse_notes": "Reviewed planner; different acceptance rules",
    }
    created = client.post("/api/workbench/projects", json=body)
    assert created.status_code == 200
    project = created.json()
    task = client.post(
        "/api/tasks",
        json={
            "title": "Build",
            "context": {
                "area": "studio",
                "project_id": project["id"],
                "app_id": "new-app",
            },
        },
    )
    assert task.status_code == 200
    assert task.json()["context"]["project_summary"] == body["summary"]
    assert client.get("/api/tasks/" + old["id"]).json()["context"] is None
    assert (
        client.post("/api/workbench/projects", json={**body, "app_id": "docs"}).status_code == 422
    )
    assert (
        client.post(
            "/api/tasks", json={"title": "bad", "context": {"app_id": "missing"}}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/tasks",
            json={"title": "bad", "context": {"app_id": "docs", "release_unit": "miy-workbench"}},
        ).status_code
        == 422
    )


def test_catalog_rejects_paths_outside_checkout(client, app_catalog):
    source = json.loads(app_catalog.read_text())
    source["apps"][0]["management"]["source_paths"] = ["../private"]
    app_catalog.write_text(json.dumps(source))
    assert client.get("/api/workbench/catalog").status_code == 403


@pytest.mark.anyio
async def test_pipeline_evidence_requires_exact_successful_typed_result(settings, monkeypatch):
    target = "a" * 40
    monkeypatch.setattr(
        sources,
        "gitlab_origin",
        lambda root: ("git.example.test", "team/repo", "https://git.example.test/team/repo"),
    )
    for row in (
        None,
        {"sha": "b" * 40, "status": "success", "id": 1},
        {"sha": target, "status": "failed", "id": 1},
        {"sha": target, "status": "success", "id": "1"},
        {"sha": target, "status": "success", "id": 1},
    ):

        async def read(*args):
            assert "sha=" + target in args[-1]
            return [row]

        monkeypatch.setattr(sources, "glab_get", read)
        evidence = await sources.verified_pipeline(settings, target)
        assert bool(evidence) == (
            isinstance(row, dict) and row == {"sha": target, "status": "success", "id": 1}
        )


@pytest.mark.parametrize("client_role", ["management", "combined"], indirect=True)
def test_workbench_is_owner_secured_and_management_independent(client, app_catalog):
    assert client.get("/api/workbench/catalog").status_code == 200
    assert client.get("/api/workbench/runtime").json()["state"] == "unconfigured"
    client.headers.pop("x-csrf-token")
    assert client.post("/api/workbench/projects", json={}).status_code == 401
    client.cookies.clear()
    assert client.get("/api/workbench/catalog").status_code == 401


def test_maintenance_link_version_and_budget_survive_new_sessions(client, app_catalog):
    root = "/api/workbench/apps/planner"
    patch = client.post(
        root + "/maintenance", json={"title": "Repair planner", "due_on": "2025-01-01"}
    ).json()
    task = client.post(
        "/api/tasks",
        json={
            "title": "Repair",
            "context": {
                "app_id": "planner",
                "maintenance_id": patch["id"],
                "area": "apps",
            },
        },
    ).json()
    linked = client.get(root + "/maintenance").json()[0]
    assert linked["task_id"] == task["id"]
    assert linked["version"] == patch["version"] + 1
    assert (
        client.put(
            root + "/maintenance/" + patch["id"], json={"title": "stale", "version": 1}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/tasks",
            json={
                "title": "wrong app",
                "context": {"app_id": "docs", "maintenance_id": patch["id"]},
            },
        ).status_code
        == 422
    )
    assert client.put(root + "/budget", json={"development_tokens": 100}).status_code == 200
    assert client.put(root + "/budget", json={"development_tokens": 200}).status_code == 409
    usage = client.get(root + "/usage").json()
    assert usage["development_tokens"] is None
    assert usage["runtime"] is None
    assert "patch_overdue" in usage["alerts"]
    assert usage["budget"]["development_tokens"] == 100


def test_native_usage_is_deduplicated_and_separate_from_runtime(client, app_catalog):
    task = client.post(
        "/api/tasks", json={"title": "Code", "context": {"app_id": "planner"}}
    ).json()
    task = send_message(client, task).json()
    for total in (100, 100, 90, 150):
        notify(
            client,
            task,
            "thread/tokenUsage/updated",
            {"tokenUsage": {"total": {"totalTokens": total}}},
        )
    usage = client.get("/api/workbench/apps/planner/usage").json()
    assert usage["development_tokens"] == 150
    assert usage["development_amount_minor"] is None
    assert usage["runtime_state"] == "unconfigured"
    with client.app.state.factory() as db:
        assert db.scalar(select(DevelopmentUsageMonth.total_tokens)) == 150


def test_workbench_records_survive_online_backup(client, app_catalog, tmp_path):
    from codex_console.models import AppBudget, WorkbenchProject, database
    from codex_console.transfer import backup

    project = client.post(
        "/api/workbench/projects",
        json={
            "app_id": "planner",
            "title": "Planner update",
            "summary": "Review scheduling",
            "reuse_decision": "extend",
            "reuse_notes": "Existing planner owns this feature",
        },
    ).json()
    patch = client.post("/api/workbench/apps/planner/maintenance", json={"title": "Repair"}).json()
    assert (
        client.put("/api/workbench/apps/planner/budget", json={"runtime_tokens": 100}).status_code
        == 200
    )
    path = backup(client.app.state.settings.database_url, tmp_path / "restored.sqlite3")
    engine, factory = database("sqlite+pysqlite:///" + str(path))
    try:
        with factory() as db:
            assert db.get(WorkbenchProject, project["id"]).reuse_decision == "extend"
            assert db.get(Maintenance, patch["id"]).title == "Repair"
            assert db.get(AppBudget, "planner").runtime_tokens == 100
    finally:
        engine.dispose()


def test_patch_completion_requires_current_exact_installation_and_ci(
    client, app_catalog, monkeypatch
):
    target = "a" * 40
    patch = client.post(
        "/api/workbench/apps/planner/maintenance", json={"title": "Fix", "target_revision": target}
    ).json()
    url = f"/api/workbench/apps/planner/maintenance/{patch['id']}/verify"

    async def installed(*args, **kwargs):
        return RuntimeOut(
            state="ready",
            stale=False,
            checked_at=now(),
            items=[
                RuntimeApp(
                    app_id="planner",
                    title="Planner",
                    enabled=True,
                    release_unit="miy-app",
                    installed_revision=target,
                    runtime_ai=False,
                )
            ],
        )

    async def failed(*args):
        return None

    monkeypatch.setattr(sources, "runtime_catalog", installed)
    monkeypatch.setattr(sources, "verified_pipeline", failed)
    assert client.post(url, json={"version": 1}).status_code == 409

    async def passed(*args):
        return {"pipeline_id": 14, "revision": target}

    monkeypatch.setattr(sources, "verified_pipeline", passed)
    response = client.post(url, json={"version": 1})
    assert response.status_code == 200
    assert response.json()["state"] == "verified"
    assert response.json()["verification"]["installed_revision"] == target
    assert (
        client.post(
            "/api/tasks",
            json={
                "title": "New patch",
                "context": {"app_id": "planner", "maintenance_id": patch["id"]},
            },
        ).status_code
        == 422
    )
    assert client.post(url, json={"version": 1}).status_code == 409
    with client.app.state.factory() as db:
        assert db.get(Maintenance, patch["id"]).verification["pipeline_id"] == 14


def test_release_identity_rejects_untrusted_or_incomplete_manifests(tmp_path):
    from codex_console.build_identity import read_identity

    path = tmp_path / "_build.json"
    assert read_identity(path) is None
    identity = {"source_revision": "a" * 40, "source_dirty": True, "digest": "sha256:" + "b" * 64}
    path.write_text(json.dumps(identity))
    assert read_identity(path) == identity
    link = tmp_path / "link.json"
    link.symlink_to(path)
    assert read_identity(link) is None
    path.write_text(json.dumps({**identity, "source_dirty": "false"}))
    assert read_identity(path) is None


def test_runtime_unknown_preserves_last_observation_and_does_not_invent_zero(
    client, app_catalog, monkeypatch
):
    cfg = client.app.state.settings
    cfg.miy_api_origin = "https://miy.example.test"

    async def answer(*args):
        return "ready", {
            "schema_version": 1,
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": 200,
            "generated_at": now().isoformat(),
        }

    monkeypatch.setattr(sources, "miy_get", answer)
    assert client.get("/api/workbench/runtime").json()["stale"] is False
    with client.app.state.factory.begin() as db:
        db.get(WorkbenchObservation, "runtime-catalog").checked_at = now() - timedelta(seconds=60)

    async def denied(*args):
        return "denied", None

    monkeypatch.setattr(sources, "miy_get", denied)
    result = client.get("/api/workbench/runtime").json()
    assert result["stale"] and result["state"] == "denied"
    assert result["checked_at"] is not None


def test_http_null_cannot_refresh_installation_or_usage_evidence(client, app_catalog, monkeypatch):
    from pydantic import SecretStr

    cfg = client.app.state.settings
    cfg.miy_api_origin = "https://miy.example.test"
    cfg.miy_api_key = SecretStr("test-read-key")
    revision = "a" * 40
    responses = {
        "/api/v1/integrations/apps": {
            "schema_version": 1,
            "items": [
                {
                    "app_id": "planner",
                    "title": "Planner",
                    "enabled": True,
                    "release_unit": "miy-app",
                    "installed_revision": revision,
                    "runtime_ai": False,
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 200,
            "generated_at": now().isoformat(),
        },
        "/api/v1/integrations/apps/planner/usage": {
            "schema_version": 1,
            "app_id": "planner",
            "month": now().strftime("%Y-%m"),
            "app_opens": 2,
            "llm_calls": 1,
            "llm_errors": 0,
            "total_tokens": 42,
            "unreported_calls": 0,
            "complete": True,
            "cost_basis": "not_reported",
            "generated_at": now().isoformat(),
        },
    }
    original = httpx.AsyncClient
    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=json.dumps(responses[request.url.path]),
                    headers={"content-type": "application/json"},
                )
            ),
        ),
    )
    before = client.get("/api/workbench/runtime").json()
    usage = client.get("/api/workbench/apps/planner/usage").json()
    assert not before["stale"] and not usage["stale"]
    patch = client.post(
        "/api/workbench/apps/planner/maintenance",
        json={
            "title": "Patch",
            "target_revision": revision,
        },
    ).json()

    async def passed(*args):
        return {"pipeline_id": 14, "revision": revision}

    monkeypatch.setattr(sources, "verified_pipeline", passed)
    responses = dict.fromkeys(responses)
    with client.app.state.factory.begin() as db:
        for row in db.scalars(select(WorkbenchObservation)):
            row.checked_at = now() - timedelta(seconds=60)
    assert (
        client.post(
            f"/api/workbench/apps/planner/maintenance/{patch['id']}/verify",
            json={"version": 1},
        ).status_code
        == 409
    )
    after = client.get("/api/workbench/runtime").json()
    assert after["state"] == "unsupported" and after["stale"]
    assert after["items"] == before["items"]
    assert after["checked_at"] == before["checked_at"]
    after_usage = client.get("/api/workbench/apps/planner/usage").json()
    assert after_usage["runtime_state"] == "unsupported" and after_usage["stale"]
    assert after_usage["runtime"] == usage["runtime"]
    assert after_usage["runtime_checked_at"] == usage["runtime_checked_at"]


@pytest.mark.anyio
async def test_miy_adapter_bounds_redirects_and_credentials(settings, monkeypatch):
    from pydantic import SecretStr

    settings.miy_api_origin = "https://miy.example.test"
    settings.miy_api_key = SecretStr("test-key")
    original = httpx.AsyncClient
    seen = []

    def reply(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://other.example.test"})

    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(reply)),
    )
    state, data = await sources.miy_get(settings, "?page_size=200")
    assert state == "unavailable" and data is None
    assert len(seen) == 1
    assert seen[0].url.host == "miy.example.test"


def test_catalog_rejects_symlink(client, app_catalog, repository):
    target = repository / "actual.json"
    app_catalog.rename(target)
    app_catalog.symlink_to(target)
    assert client.get("/api/workbench/catalog").status_code == 403
