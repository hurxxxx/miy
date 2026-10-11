import asyncio
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import new_task, send_message
from sqlalchemy import select

from codex_console import store, templates
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.models import Operation, PendingRequest, Task, TaskTemplate


@pytest.mark.parametrize("name", ["코드 검토", "테스트"])
@pytest.mark.parametrize("state", ["untouched", "edited", "archived", "versioned"])
def test_validation_default_transition_preserves_owner_edits_and_execution_history(
    client, name, state
):
    defaults = client.get("/api/templates").json()
    current = next(row for row in defaults if row["definition"]["name"] == name)
    old_prompt = {
        "코드 검토": (
            "Review {{request}}. Inspect the actual changes and relevant contracts and tests. "
            "Report actionable findings with evidence. Do not modify code or publish comments."
        ),
        "테스트": (
            "Validate {{request}} using relevant behavior and contract checks. Report commands, "
            "results and anything not verified. Do not weaken checks, publish or deploy changes."
        ),
    }[name]
    previous = {
        **current["definition"],
        "prompt": (
            "Read AGENTS.md and the applicable repository instructions. Preserve unrelated work. "
            + old_prompt
        ),
    }
    if state == "edited":
        previous = {**previous, "context": "Keep the owner's chosen test scope"}
    original = {"template_id": current["id"], "version": 1, "definition": previous}
    task = new_task(client)
    factory = client.app.state.factory
    with factory.begin() as db:
        saved = db.get(TaskTemplate, current["id"])
        saved.definition = previous
        saved.version = 2 if state == "versioned" else 1
        saved.archived = state == "archived"
        db.get(Task, task["id"]).template_snapshot = original
    templates.seed(factory)
    templates.seed(factory)  # A restart does not create another revision.
    with factory() as db:
        saved = db.get(TaskTemplate, current["id"])
        assert saved.definition == (current["definition"] if state == "untouched" else previous)
        assert saved.version == (2 if state in ("untouched", "versioned") else 1)
        assert saved.archived is (state == "archived")
        assert db.get(Task, task["id"]).template_snapshot == original


@pytest.mark.parametrize("reference_state", ["changed", "unavailable"])
def test_resume_explains_reference_changes_without_rewriting_launch_snapshot(
    client, repository, reference_state
):
    row = template(client)
    launched = launch(client, row).json()
    original = launched["template_snapshot"]
    runtime = client.app.state.template_runtime
    client.portal.call(
        runtime.on_message,
        {
            "method": "turn/completed",
            "params": {
                "threadId": launched["thread_id"],
                "turn": {"id": launched["turn_id"], "status": "completed"},
            },
        },
    )
    if reference_state == "changed":
        (repository / "hello.txt").write_text("The current contract has changed.\n")
    else:
        (repository / "hello.txt").unlink()
    resumed = send_message(client, launched, text="Continue the authorized review")
    assert resumed.status_code == 200, resumed.json()
    request = [p for m, p in runtime.rpc.calls if m == "turn/start"][-1]
    changes = json.loads(request["additionalContext"]["template_context_changes"]["value"])
    assert changes["changes"] == [{"reference": "hello.txt", "state": reference_state}]
    assert client.get(f"/api/tasks/{launched['id']}").json()["template_snapshot"] == original
    assert len([m for m, _ in runtime.rpc.calls if m == "thread/start"]) == 1


def test_resume_reports_retired_skill_without_reapplying_it(client, monkeypatch):
    from conftest import FakeRPC

    native_call = FakeRPC.call
    installed = True

    async def call(rpc, method, params):
        if method == "skills/list":
            return {
                "data": [
                    {
                        "cwd": str(client.app.state.settings.workspace),
                        "skills": [
                            {
                                "name": "review-helper",
                                "path": "/skills/review/SKILL.md",
                                "enabled": True,
                            }
                        ]
                        if installed
                        else [],
                    }
                ]
            }
        return await native_call(rpc, method, params)

    monkeypatch.setattr(FakeRPC, "call", call)
    launched = launch(client, template(client, skills=["review-helper"])).json()
    runtime = client.app.state.template_runtime
    original = launched["template_snapshot"]
    client.portal.call(
        runtime.on_message,
        {
            "method": "turn/completed",
            "params": {
                "threadId": launched["thread_id"],
                "turn": {"id": launched["turn_id"], "status": "completed"},
            },
        },
    )
    installed = False
    assert send_message(client, launched).status_code == 200
    request = [p for m, p in runtime.rpc.calls if m == "turn/start"][-1]
    changes = json.loads(request["additionalContext"]["template_context_changes"]["value"])
    assert changes["changes"] == [{"skill": "review-helper", "state": "unavailable"}]
    assert not any(item["type"] == "skill" for item in request["input"])
    assert client.get(f"/api/tasks/{launched['id']}").json()["template_snapshot"] == original


def template(client, **changes):
    response = client.post(
        "/api/templates",
        json={
            "name": "Repository question",
            "prompt": "Inspect {{topic}}",
            "stage": "plan",
            "references": ["hello.txt"],
            "variables": [{"name": "topic", "label": "Topic", "default": "the repository"}],
            **changes,
        },
    )
    assert response.status_code == 200
    return response.json()


def launch(client, row, **changes):
    return client.post(
        f"/api/templates/{row['id']}/run",
        json={
            "launch_id": str(uuid4()),
            "version": row["version"],
            "values": {},
            **changes,
        },
    )


@pytest.fixture
def app_source(client, tmp_path):
    root = tmp_path / "bound-app"
    root.mkdir()
    manifest = json.loads(
        (Path(__file__).parents[3] / "templates/independent-app/app.manifest.json").read_text()
    )
    manifest["source"]["directory"] = "app"
    (root / "app/ui").mkdir(parents=True)
    (root / "app/ui/hello.txt").write_text("App review reference\n")
    (root / "app.manifest.json").write_text(json.dumps(manifest))
    for args in (
        ("init", "-b", "personal"),
        ("config", "user.email", "console@test.invalid"),
        ("config", "user.name", "Console Test"),
        ("remote", "add", "origin", manifest["source"]["repository"]),
        ("add", "."),
        ("commit", "-m", "app fixture"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    cfg = client.app.state.settings
    cfg.app_source_roots = [root]
    cfg.app_execution_environments = [
        AppExecutionEnvironment(
            key="sample",
            source_root=root,
            exec_server_url="ws://127.0.0.1:19876",
            auth_bearer_token="synthetic-executor-token-" * 3,
        )
    ]
    # The platform branch does not exist in the independent repository.
    cfg.worktree_base_ref = "origin/dev"
    result = client.put(
        "/api/workbench/apps/sample-app/source",
        json={"repository_root": str(root), "version": 0},
    )
    assert result.status_code == 200, result.json()
    return root


def test_app_template_uses_selected_remote_repository_and_nested_directory(client, app_source):
    row = template(client, app_id="sample-app", directory="ui")
    response = launch(client, row)
    assert response.status_code == 200, response.json()
    task = response.json()
    expected = app_source / "app/ui"
    assert task["root"] == str(expected)
    with client.app.state.factory() as db:
        assert not db.get(Task, task["id"]).worktree_owned
    assert task["context"]["source_binding"]["directory"] == "app"
    assert task["context"]["release_unit"] is None
    assert task["template_snapshot"]["definition"]["app_id"] == "sample-app"
    assert task["template_snapshot"]["reference_hashes"]["hello.txt"]
    runtime = client.app.state.template_runtime.for_task(task["id"])
    assert runtime.remote_task_id == task["id"]
    host_rpc = client.app.state.template_runtime.rpc
    assert not host_rpc or not any(
        method in ("thread/start", "thread/resume", "turn/start") for method, _ in host_rpc.calls
    )
    request = [p for m, p in runtime.rpc.calls if m == "turn/start"][-1]
    assert request["cwd"] == str(expected)
    assert request["environments"][0]["cwd"] == str(expected)


def test_app_template_cannot_create_unmounted_host_worktree(client, app_source):
    row = template(client, app_id="sample-app", directory="ui", isolate=True)
    response = launch(client, row)
    assert response.status_code == 200
    task = response.json()
    assert task["status"] == "failed"
    assert task["error_code"] == "app_executor_worktree_unsupported"
    assert task["thread_id"] is None and task["root"] == str(app_source / "app/ui")
    assert not any(client.app.state.settings.worktree_root.glob("codex-*"))


def test_bound_app_can_be_repaired_but_new_template_launch_requires_valid_manifest(
    client, app_source
):
    row = template(client, app_id="sample-app", directory="ui")
    task = launch(client, row).json()
    runtime = client.app.state.template_runtime.for_task(task["id"])
    client.portal.call(
        runtime.on_message,
        {
            "method": "turn/completed",
            "params": {
                "threadId": task["thread_id"],
                "turn": {"id": task["turn_id"], "status": "completed"},
            },
        },
    )
    (app_source / "app.manifest.json").write_text("{ invalid")
    resumed = send_message(client, task, text="Repair the app manifest")
    assert resumed.status_code == 200, resumed.json()
    assert resumed.json()["root"] == str(app_source / "app/ui")
    assert launch(client, row).status_code == 422
    client.app.state.settings.app_source_roots = []
    denied = send_message(client, task)
    assert denied.status_code == 403, denied.json()


def test_app_template_picker_never_discovers_host_skills_for_app_source(client, app_source):
    response = client.get("/api/templates/catalog?app_id=sample-app&directory_name=ui")
    assert response.status_code == 200, response.json()
    assert response.json()["workspace"] == str(app_source / "app/ui")
    assert response.json()["skills"] == []
    assert not any(m == "skills/list" for m, _ in client.app.state.template_runtime.rpc.calls)
    assert (
        client.get("/api/templates/catalog?app_id=sample-app&directory_name=../..").status_code
        == 403
    )


def test_templates_preserve_versions_and_start_independent_native_threads(client):
    row = template(client)
    first, second = launch(client, row), launch(client, row)
    assert first.status_code == second.status_code == 200
    first, second = first.json(), second.json()
    assert first["executor"] == second["executor"] == "templates"
    assert first["thread_id"] != second["thread_id"]
    assert first["status"] == "running"
    starts = [p for m, p in client.app.state.template_runtime.rpc.calls if m == "thread/start"]
    assert len(starts) == 2
    assert all(
        "Respond to the user in Korean by default" in p["developerInstructions"] for p in starts
    )
    assert first["template_snapshot"]["resolved_values"] == {"topic": "the repository"}
    assert len(first["template_snapshot"]["reference_hashes"]["hello.txt"]) == 64
    saved = client.put(
        f"/api/templates/{row['id']}",
        json={
            "version": row["version"],
            "definition": {**row["definition"], "prompt": "New request"},
        },
    )
    assert saved.status_code == 200 and saved.json()["version"] == 2
    old = client.get(f"/api/tasks/{first['id']}").json()
    assert old["template_snapshot"]["definition"]["prompt"] == "Inspect {{topic}}"
    assert launch(client, row).status_code == 409
    assert client.app.state.runtime.rpc is None


def test_launch_retry_returns_original_task_without_replaying(client):
    row = template(client)
    request_id = str(uuid4())
    first = launch(client, row, launch_id=request_id).json()
    second = launch(client, row, launch_id=request_id).json()
    assert first["id"] == second["id"]
    rpc = client.app.state.template_runtime.rpc
    assert len([m for m, _ in rpc.calls if m == "turn/start"]) == 1
    assert launch(client, row, launch_id=request_id, values={"topic": "changed"}).status_code == 409


def test_template_history_survives_renaming_archiving_and_excludes_same_named_copies(client):
    row = template(client)
    first = launch(client, row).json()
    copied = template(client)
    other = launch(client, copied).json()
    updated = client.put(
        f"/api/templates/{row['id']}",
        json={
            "version": row["version"],
            "definition": {**row["definition"], "name": "Renamed template"},
        },
    ).json()
    second = launch(client, updated).json()
    archived = client.put(
        f"/api/templates/{row['id']}",
        json={"version": updated["version"], "definition": updated["definition"], "archived": True},
    ).json()
    assert client.get(f"/api/templates/{row['id']}").json() == archived
    for path in ("/api/overview", "/api/tasks"):
        runs = client.get(path, params={"template_id": row["id"]}).json()
        assert {r["id"] for r in runs} == {first["id"], second["id"]}
        assert {r["template_snapshot"]["version"] for r in runs} == {1, 2}
        filtered = client.get(path, params={"template_id": row["id"], "search": "Renamed"}).json()
        assert [r["id"] for r in filtered] == [second["id"]]
        assert [r["id"] for r in client.get(path, params={"template_id": copied["id"]}).json()] == [
            other["id"]
        ]
        assert client.get(path, params={"template_id": str(uuid4())}).json() == []
        assert client.get(path, params={"template_id": "invalid"}).status_code == 422
    assert client.get(f"/api/templates/{uuid4()}").status_code == 404
    client.delete("/api/session")
    assert client.get(f"/api/templates/{row['id']}").status_code == 401
    assert client.get("/api/overview", params={"template_id": row["id"]}).status_code == 401


def test_template_history_scopes_before_recent_limit_and_tracked_work(client, repository):
    from datetime import UTC, datetime

    row = template(client)
    with client.app.state.factory.begin() as db:
        old = Task(
            title="Old 100%_done",
            root=str(repository),
            executor="templates",
            template_snapshot={"template_id": row["id"], "version": 1},
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        db.add(old)
        db.add_all(Task(title=f"Recent {i}", root=str(repository)) for i in range(201))
        db.add(
            Task(
                title="Unrelated pinned failure", root=str(repository), status="failed", pinned=True
            )
        )
        db.flush()
        old_id = old.id
    assert old_id not in {r["id"] for r in client.get("/api/overview").json()}
    for search in ("", "100%_done"):
        runs = client.get(
            "/api/overview", params={"template_id": row["id"], "search": search}
        ).json()
        assert [r["id"] for r in runs] == [old_id]


def test_native_import_cannot_claim_a_template_child_as_a_session_task(client):
    from codex_console.models import Agent

    row = template(client)
    task = launch(client, row).json()
    with client.app.state.factory.begin() as db:
        db.add(
            Agent(
                thread_id="template-child", task_id=task["id"], parent_thread_id=task["thread_id"]
            )
        )
    client.get("/api/codex/account")
    rpc = client.app.state.runtime.rpc
    rpc.threads["template-child"] = {
        "id": "template-child",
        "cwd": str(client.app.state.settings.workspace),
        "turns": [],
    }
    response = client.post(
        "/api/tasks/import", json={"thread_id": "template-child", "confirm_inactive": True}
    )
    assert response.status_code == 409 and response.json()["code"] == "thread_owned"
    assert [t["id"] for t in client.get("/api/overview").json()] == [task["id"]]


def test_nested_template_preserves_cwd_when_isolated_and_diff_uses_repository_paths(
    client, repository
):
    from pathlib import Path

    from codex_console import git

    nested = repository / "component"
    nested.mkdir()
    (nested / "entry.txt").write_text("before\n")
    git.git(repository, "add", "component")
    git.git(repository, "commit", "-m", "nested fixture")
    (repository / "unrelated.txt").write_text("Keep this existing work\n")
    row = template(
        client, directory="component", references=["entry.txt"], stage="implement", isolate=True
    )
    task = launch(client, row).json()
    assert task["status"] == "running", task.get("error_code")
    root = Path(task["root"])
    assert root.name == "component" and root.parent.name == f"codex-{task['id']}"
    rpc = client.app.state.template_runtime.rpc
    request = next(params for method, params in rpc.calls if method == "turn/start")
    assert request["cwd"] == str(root)
    assert task["template_snapshot"]["execution_root"] == str(root)
    (root / "entry.txt").write_text("after\n")
    (root / "new.txt").write_text("first\n")
    assert {r["path"] for r in git.changes(root)} == {"component/entry.txt", "component/new.txt"}
    assert git.diff(root, "component/entry.txt")["new"] == "after\n"
    (root / "new.txt").write_text("second\n")
    assert git.diff(root, "component/new.txt")["new"] == "second\n"
    assert (repository / "unrelated.txt").read_text() == "Keep this existing work\n"


def test_templates_reject_stale_edit_and_archived_run(client):
    row = template(client)
    body = {"version": 1, "definition": row["definition"], "archived": True}
    assert client.put(f"/api/templates/{row['id']}", json=body).status_code == 200
    assert client.put(f"/api/templates/{row['id']}", json=body).status_code == 409
    assert launch(client, row).status_code == 404
    assert any(r["id"] == row["id"] for r in client.get("/api/templates?archived=true").json())


@pytest.mark.parametrize(
    "changes",
    [
        {"directory": "../outside"},
        {"directory": "/tmp"},
        {"prompt": "Unknown {{input}}"},
    ],
)
def test_invalid_template_is_not_saved(client, changes):
    before = client.get("/api/templates").json()
    result = client.post("/api/templates", json={"name": "Invalid", "prompt": "inspect", **changes})
    assert result.status_code in (403, 422)
    assert client.get("/api/templates").json() == before


def test_missing_skill_or_required_value_does_not_create_a_task(client):
    row = template(client, skills=["not-installed"])
    assert launch(client, row).json()["code"] == "skill_unavailable"
    row = template(client, variables=[{"name": "topic", "label": "Topic"}])
    assert launch(client, row).status_code == 422
    assert client.get("/api/overview").json() == []


def test_missing_reference_is_rejected_before_creating_a_native_task(client):
    row = template(client, references=["missing.txt"])
    response = launch(client, row)
    assert response.status_code == 404
    assert response.json() == {"code": "reference_not_found"}
    assert client.get("/api/overview").json() == []
    assert client.app.state.template_runtime.rpc is None


def test_empty_reference_is_a_valid_file(client, repository):
    (repository / "empty.txt").touch()
    row = template(client, references=["empty.txt"])
    response = launch(client, row)
    assert response.status_code == 200
    assert response.json()["status"] == "running"


def test_hard_link_reference_cannot_be_sent_to_a_native_task(client, repository, tmp_path):
    import os

    private = tmp_path / "private.txt"
    private.write_text("SYNTHETIC_PRIVATE_VALUE")
    os.link(private, repository / "reference.txt")
    response = launch(client, template(client, references=["reference.txt"]))
    assert response.status_code == 403
    assert response.json() == {"code": "path_denied"}
    assert client.get("/api/overview").json() == []
    assert client.app.state.template_runtime.rpc is None


def test_session_restart_and_disconnect_leave_template_execution_and_approval_intact(client):
    row = template(client)
    task = launch(client, row).json()
    runtime = client.app.state.template_runtime
    client.portal.call(
        runtime.server_request,
        {
            "id": 41,
            "method": "item/tool/requestUserInput",
            "params": {
                "threadId": task["thread_id"],
                "turnId": task["turn_id"],
                "itemId": "question",
                "questions": [
                    {
                        "id": "decision",
                        "header": "Next",
                        "question": "Continue?",
                        "options": None,
                        "isOther": False,
                        "isSecret": False,
                    }
                ],
            },
        },
    )
    store.recover_startup(client.app.state.factory, "session")
    client.portal.call(client.app.state.runtime.on_disconnect)
    current = client.get(f"/api/tasks/{task['id']}").json()
    assert current["status"] == "waiting" and len(current["requests"]) == 1
    with client.app.state.factory() as db:
        assert (
            db.scalar(select(Operation).where(Operation.task_id == task["id"])).state == "accepted"
        )
        assert (
            db.scalar(select(PendingRequest).where(PendingRequest.task_id == task["id"])).state
            == "pending"
        )
    with pytest.raises(ConsoleError, match="executor_mismatch"):
        client.portal.call(client.app.state.runtime.interrupt, task["id"])


def test_resource_capacity_is_shared_between_executors(client):
    client.app.state.settings.max_active_tasks = 1
    send_message(client, new_task(client))
    result = launch(client, template(client)).json()
    assert result["status"] == "failed" and result["error_code"] == "capacity_busy"


def test_parent_and_nested_writers_share_one_workspace_lease(client, repository):
    from codex_console import git

    nested = repository / "component"
    nested.mkdir()
    (nested / "entry.txt").write_text("fixture\n")
    git.git(repository, "add", "component")
    git.git(repository, "commit", "-m", "nested fixture")
    root_id = new_task(client)["id"]
    response = client.post(
        f"/api/tasks/{root_id}/implement",
        json={"text": "Inspect the repository", "operation_id": str(uuid4())},
    )
    assert response.status_code == 200
    root_task = response.json()
    assert root_task["status"] == "running"
    row = template(client, directory="component", references=["entry.txt"], stage="implement")
    blocked = launch(client, row).json()
    assert blocked["status"] == "failed" and blocked["error_code"] == "workspace_busy"
    isolated = launch(client, template(client, isolate=True, stage="implement")).json()
    assert isolated["status"] == "running", isolated.get("error_code")


def test_launch_preparation_cannot_be_overtaken_by_another_message(client, monkeypatch):
    import threading

    import httpx

    from codex_console import git

    row = template(client, isolate=True)
    identity = str(uuid4())
    entered, release = threading.Event(), threading.Event()
    original = git.prepare_workspace

    def slow_prepare(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(git, "prepare_workspace", slow_prepare)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url="http://localhost",
            cookies=client.cookies,
            headers=dict(client.headers),
        ) as browser:
            path = f"/api/templates/{row['id']}/run"
            body = {"launch_id": identity, "version": 1, "values": {}}
            first = asyncio.create_task(browser.post(path, json=body))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                repeated = (await browser.post(path, json=body)).json()
                assert repeated["status"] == "starting" and not repeated["thread_id"]
                competing = asyncio.create_task(
                    browser.post(
                        f"/api/tasks/{repeated['id']}/messages",
                        json={
                            "text": "Competing request",
                            "stage": "plan",
                            "operation_id": str(uuid4()),
                        },
                    )
                )
                await asyncio.sleep(0)
                assert not any(
                    m == "turn/start" for m, _ in client.app.state.template_runtime.rpc.calls
                )
            finally:
                release.set()
            initial = (await first).json()
            response = await competing
            assert initial["status"] == "running"
            assert response.status_code == 409
            assert initial["root"] != str(client.app.state.settings.workspace)
            calls = [p for m, p in client.app.state.template_runtime.rpc.calls if m == "turn/start"]
            assert len(calls) == 1 and calls[0]["cwd"] == initial["root"]

    client.portal.call(run)


def test_simultaneous_launches_with_one_identity_execute_once(client):
    row = template(client)
    identity = str(uuid4())

    async def run():
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app),
            base_url="http://localhost",
            cookies=client.cookies,
            headers=dict(client.headers),
        ) as browser:
            return await asyncio.gather(
                *[
                    browser.post(
                        f"/api/templates/{row['id']}/run",
                        json={"launch_id": identity, "version": 1, "values": {}},
                    )
                    for _ in range(2)
                ]
            )

    results = client.portal.call(run)
    assert all(r.status_code == 200 for r in results)
    assert results[0].json()["id"] == results[1].json()["id"]
    with client.app.state.factory() as db:
        assert len(list(db.scalars(select(Task)))) == 1
