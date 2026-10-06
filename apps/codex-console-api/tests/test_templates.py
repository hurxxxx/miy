import asyncio
from uuid import uuid4

import pytest
from conftest import new_task, send_message
from sqlalchemy import select

from codex_console import store
from codex_console.errors import ConsoleError
from codex_console.models import Operation, PendingRequest, Task


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
    row = template(
        client, directory="component", references=["entry.txt"], stage="implement"
    )
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
