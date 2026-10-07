import json
from datetime import timedelta
from uuid import UUID, uuid4

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
    assert task.json()["context"]["app_execution_boundary"] == "planning_only"
    denied = client.post(
        f"/api/tasks/{task.json()['id']}/implement",
        json={"operation_id": str(uuid4()), "text": "Implement this app"},
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "app_source_planning_only"
    assert send_message(client, task.json(), text="Plan this app").status_code == 200
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


def test_catalog_discovers_unmanaged_apps_and_preserves_manifest_identity(client, app_catalog):
    data = json.loads(app_catalog.read_text())
    data["apps"].append(
        {
            "app_id": "candidate-review",
            "title": "Candidate review",
            "title_translations": {"ko-KR": "지원서 검토", "en-US": "Candidate review"},
            "icon_key": "clipboard-check",
            "route_base": "/apps/candidate-review",
        }
    )
    app_catalog.write_text(json.dumps(data))
    result = client.get("/api/workbench/catalog").json()["items"][-1]
    assert result["app_id"] == "candidate-review"
    assert result["title_translations"] == data["apps"][-1]["title_translations"]
    assert result["icon_key"] == "clipboard-check"
    assert result["source_paths"] == [] and result["release_unit"] is None
    assert result["source_status"] == result["deployment_status"] == "unconfigured"
    assert "source_not_configured" in result["limitations"]
    assert "release_not_configured" in result["limitations"]
    inspection = client.post(
        "/api/tasks",
        json={
            "title": "Inspect",
            "context": {"app_id": "candidate-review", "purpose": "inspection"},
        },
    )
    assert inspection.status_code == 200
    assert inspection.json()["context"]["release_unit"] is None
    assert (
        client.post(
            "/api/tasks",
            json={
                "title": "Develop",
                "context": {"app_id": "candidate-review", "purpose": "development"},
            },
        ).status_code
        == 422
    )


def test_catalog_has_no_200_app_discovery_limit_and_reports_missing_source(client, app_catalog):
    data = json.loads(app_catalog.read_text())
    template = data["apps"][0]
    data["apps"] = [
        {**template, "app_id": f"app-{i}", "route_base": f"/apps/app-{i}"} for i in range(205)
    ]
    data["apps"][-1]["management"] = {**template["management"], "source_paths": ["missing-source"]}
    app_catalog.write_text(json.dumps(data))
    result = client.get("/api/workbench/catalog").json()["items"]
    assert len(result) == 205
    assert result[0]["source_status"] == "ready"
    assert result[-1]["source_status"] == "missing"
    assert "source_missing" in result[-1]["limitations"]


def test_unmanaged_duplicate_app_ids_are_rejected(client, app_catalog):
    data = json.loads(app_catalog.read_text())
    data["apps"].append({k: v for k, v in data["apps"][0].items() if k != "management"})
    app_catalog.write_text(json.dumps(data))
    assert client.get("/api/workbench/catalog").status_code == 503


def test_runtime_catalog_traverses_all_pages_atomically(client, monkeypatch):
    client.app.state.settings.miy_api_origin = "https://miy.example.test"
    items = [
        {
            "app_id": f"app-{i}",
            "title": f"App {i}",
            "enabled": True,
            "release_unit": None,
            "runtime_ai": False,
        }
        for i in range(405)
    ]
    paths = []

    async def answer(settings, path):
        from urllib.parse import parse_qs

        page = int(parse_qs(path[1:])["page"][0])
        paths.append(path)
        return "ready", {
            "schema_version": 1,
            "items": items[(page - 1) * 200 : page * 200],
            "total": len(items),
            "page": page,
            "page_size": 200,
            "catalog_revision": "catalog-a",
            "generated_at": now().isoformat(),
        }

    monkeypatch.setattr(sources, "miy_get", answer)
    result = client.get("/api/workbench/runtime").json()
    assert result["state"] == "ready" and not result["stale"]
    assert len(result["items"]) == 405
    assert len(paths) == 3


@pytest.mark.parametrize("failure", ["revision", "duplicate", "truncated", "denied"])
def test_runtime_catalog_rejects_partial_or_changed_pages(client, monkeypatch, failure):
    client.app.state.settings.miy_api_origin = "https://miy.example.test"

    async def answer(settings, path):
        page = 1 if "page=1&" in path else 2
        if page == 2 and failure == "denied":
            return "denied", None
        items = [
            {
                "app_id": f"app-{i}",
                "title": "App",
                "enabled": True,
                "release_unit": None,
                "runtime_ai": False,
            }
            for i in (range(200) if page == 1 else [200])
        ]
        if page == 2 and failure == "duplicate":
            items[0]["app_id"] = "app-0"
        if page == 2 and failure == "truncated":
            items = []
        return "ready", {
            "schema_version": 1,
            "items": items,
            "total": 201,
            "page": page,
            "page_size": 200,
            "generated_at": now().isoformat(),
            "catalog_revision": "changed" if page == 2 and failure == "revision" else "first",
        }

    monkeypatch.setattr(sources, "miy_get", answer)
    result = client.get("/api/workbench/runtime").json()
    assert result["state"] == ("denied" if failure == "denied" else "unsupported")
    assert result["stale"] and result["items"] == []


def installation_observation(index):
    return {
        "id": str(UUID(int=index + 1)),
        "environment": "development",
        "origin": f"https://preview-{index}.example.test",
        "enabled": True,
        "state": "configured",
        "generation": 1,
        "release_id": None,
        "source_revision": None,
        "artifact_digest": None,
        "deployment": {
            "request_id": str(UUID(int=index + 1000)),
            "action": "deploy",
            "state": "unknown",
            "failure_code": "executor_unavailable",
            "updated_at": now().isoformat(),
        },
    }


def installation_page(items, page=1, **changes):
    return {
        "schema_version": 1,
        "app_id": "planner",
        "items": items[(page - 1) * 200 : page * 200],
        "total": len(items),
        "page": page,
        "page_size": 200,
        "catalog_revision": "a" * 64,
        "generated_at": now().isoformat(),
        **changes,
    }


def test_installation_observation_reads_complete_snapshot_and_retains_stale_evidence(
    client, app_catalog, monkeypatch
):
    cfg = client.app.state.settings
    cfg.miy_api_origin = "https://miy.example.test"
    items = [installation_observation(i) for i in range(205)]
    calls = []

    async def answer(settings, path):
        calls.append(path)
        assert path.startswith("/planner/installations?")
        return "ready", installation_page(items, 1 if "page=1&" in path else 2)

    monkeypatch.setattr(sources, "miy_get", answer)
    url = "/api/workbench/apps/planner/installations"
    initial = client.get(url)
    assert initial.status_code == 200
    before = initial.json()
    assert before["state"] == "ready" and not before["stale"]
    assert len(before["items"]) == 205 and len(calls) == 2
    assert before["items"][0]["deployment"]["state"] == "unknown"
    assert before["items"][0]["source_revision"] is None
    with client.app.state.factory.begin() as db:
        db.get(WorkbenchObservation, "installations:planner").checked_at = now() - timedelta(
            seconds=60
        )

    async def denied(*args):
        return "denied", None

    monkeypatch.setattr(sources, "miy_get", denied)
    after = client.get(url).json()
    assert after["state"] == "denied" and after["stale"]
    assert after["items"] == before["items"]
    assert after["checked_at"] == before["checked_at"]
    cfg.miy_api_origin = "https://another.example.test"
    changed = client.get(url).json()
    assert changed["items"] == [] and changed["checked_at"] is None
    assert client.get("/api/workbench/apps/missing/installations").status_code == 404


@pytest.mark.parametrize("failure", ["app", "origin", "revision", "duplicate", "truncated"])
def test_installation_observation_rejects_unsafe_or_partial_snapshot(
    client, app_catalog, monkeypatch, failure
):
    client.app.state.settings.miy_api_origin = "https://miy.example.test"
    items = [installation_observation(i) for i in range(201)]
    if failure == "origin":
        items[0]["origin"] = "https://user:password@preview.example.test"
    if failure == "duplicate":
        items[200]["id"] = items[0]["id"]

    async def answer(settings, path):
        page = 1 if "page=1&" in path else 2
        data = installation_page(items, page)
        if failure == "app":
            data["app_id"] = "docs"
        if page == 2 and failure == "revision":
            data["catalog_revision"] = "b" * 64
        if page == 2 and failure == "truncated":
            data["items"] = []
        return "ready", data

    monkeypatch.setattr(sources, "miy_get", answer)
    result = client.get("/api/workbench/apps/planner/installations").json()
    assert result["state"] == "unsupported" and result["stale"]
    assert result["items"] == [] and result["checked_at"] is None


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


def test_connected_catalog_uses_platform_display_identity_for_checkout_apps(client, app_catalog):
    settings = client.app.state.settings
    settings.miy_api_origin = "https://platform.example.test"
    with client.app.state.factory.begin() as db:
        db.add(
            WorkbenchObservation(
                key="runtime-catalog",
                payload={
                    "origin": settings.miy_api_origin,
                    "state": "ready",
                    "data": {
                        "items": [
                            {
                                "app_id": "planner",
                                "title": "Registered planner",
                                "title_translations": {"ko-KR": "동일한 앱 이름"},
                                "icon_key": "puzzle",
                                "enabled": True,
                                "runtime_ai": False,
                                "release_unit": "miy-app",
                            }
                        ]
                    },
                },
            )
        )
    item = client.get("/api/workbench/catalog").json()["items"][0]
    assert item["title"] == "Registered planner"
    assert item["title_translations"] == {"ko-KR": "동일한 앱 이름"}
    assert item["icon_key"] == "puzzle" and item["source_status"] == "ready"
