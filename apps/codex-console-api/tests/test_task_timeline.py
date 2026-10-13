import json
import subprocess
from uuid import uuid4

import pytest
from conftest import complete, new_task, send_message
from sqlalchemy import func, select
from test_task_git import link, worktree

from codex_console import task_git, task_timeline, tool_catalog
from codex_console.models import Event, TaskMilestone


def command(root, *args):
    return (
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        .stdout.decode()
        .strip()
    )


def call(client, task, args, **overrides):
    runtime = client.app.state.runtime
    message = {
        "id": 72,
        "method": "item/tool/call",
        "params": {
            "threadId": task["thread_id"],
            "turnId": task["turn_id"],
            "callId": "summary-call",
            "tool": "miy_task_timeline",
            "arguments": args,
            **overrides,
        },
    }
    client.portal.call(runtime.server_request, message)
    response = runtime.rpc.responses[-1][1]
    return response["success"], json.loads(response["contentItems"][0]["text"])


def timeline(client, task):
    return client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]


def merge_request(client, task, target):
    linked = link(client, task, target).json()[-1]
    path = f"/api/tasks/{task['id']}"
    snapshot = client.get(path + "/merge-target", params={"link_id": linked["id"]})
    assert snapshot.status_code == 200, snapshot.text
    data = snapshot.json()
    return dict(
        operation_id=str(uuid4()),
        link_id=linked["id"],
        expected_head=data["source_head"],
        expected_branch=data["source_branch"],
        expected_target_head=data["target_head"],
        expected_target_branch=data["target_branch"],
        permissions="ask",
    )


@pytest.mark.parametrize("client_role", ["combined", "management"], indirect=True)
def test_tool_catalog_uses_native_specs_and_requires_auth(client):
    response = client.get("/api/tool-catalog")
    assert response.status_code == 200
    data = {row["name"]: row for row in response.json()}
    assert len(data) == 5
    for module in (task_git, task_timeline):
        assert data[module.TOOL_NAME]["input_schema"] == module.specs()[0]["inputSchema"]
    assert data == {row["name"]: row for row in tool_catalog.catalog()}
    client.cookies.clear()
    assert client.get("/api/tool-catalog").status_code == 401


def test_native_summary_updates_are_durable_idempotent_scoped_and_allow_followup(client):
    task = send_message(client, new_task(client)).json()
    runtime = client.app.state.runtime
    specs = next(p["dynamicTools"] for m, p in runtime.rpc.calls if m == "thread/start")
    assert [s["name"] for s in specs] == ["miy_task_git", "miy_task_timeline"]
    ok, result = call(client, task, {"action": "list"})
    assert ok and result["recent_evidence"]
    args = dict(
        action="update",
        key="feature",
        title="구현 작업",
        phase="validation",
        state="in_progress",
        summary="검사 진행 중",
        evidence_ids=[result["recent_evidence"][0]["id"]],
    )
    assert call(client, task, args)[0]
    with client.app.state.factory() as db:
        count = db.scalar(select(func.count()).select_from(Event))
    assert call(client, task, args)[0]
    with client.app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Event)) == count
    assert len(timeline(client, task)) == 1
    other = new_task(client)
    assert timeline(client, other) == []
    with client.app.state.factory() as db:
        foreign = db.scalar(select(Event.id).where(Event.task_id == other["id"]))
    assert (
        call(client, task, {**args, "evidence_ids": [foreign]})[1]["error"]
        == "timeline_evidence_unavailable"
    )
    assert not call(client, task, args, turnId="stale-turn")[0]
    assert call(client, task, {**args, "phase": "finish", "state": "completed"})[0]
    assert (
        call(client, task, {**args, "summary": "changed"})[1]["error"]
        == "timeline_segment_completed"
    )
    assert call(client, task, {**args, "key": "followup"})[0]
    assert len(timeline(client, task)) == 2
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == "running"


def test_merge_requires_same_repo_and_snapshot_and_preserves_permissions(client, repository):
    task = new_task(client)
    path = f"/api/tasks/{task['id']}"
    assert client.get(path + "/merge-target", params={"link_id": "root"}).status_code == 409
    target = worktree(client, repository)
    body = merge_request(client, task, target)
    assert client.post(path + "/merge", json={**body, "expected_head": "0" * 40}).status_code == 409
    assert timeline(client, task) == []
    result = client.post(path + "/merge", json=body)
    assert result.status_code == 200, result.text
    task = result.json()
    assert task["stage"] == "implement" and task["permissions"] == "ask"
    repeated = client.post(path + "/merge", json=body)
    assert repeated.status_code == 200, repeated.text
    assert len([m for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"]) == 1
    assert len(timeline(client, task)) == 1
    assert client.post(path + "/merge", json={**body, "permissions": "yolo"}).status_code == 409
    row = timeline(client, task)[0]
    assert client.post(path + f"/timeline/{row['id']}/verify", json={}).status_code == 409
    complete(client, task)
    assert timeline(client, task)[0]["state"] == "needs_attention"
    assert not timeline(client, task)[0]["merge"]["verified"]


def test_completed_turn_is_not_a_merge_but_real_integration_finishes_segment(client, repository):
    task = new_task(client)
    target = worktree(client, repository)
    body = merge_request(client, task, target)
    path = f"/api/tasks/{task['id']}"
    task = client.post(path + "/merge", json=body).json()
    row = timeline(client, task)[0]
    args = dict(
        action="update",
        key=row["key"],
        title=row["title"],
        phase="finish",
        state="completed",
        summary="완료",
    )
    assert call(client, task, args)[1]["error"] == "merge_verification_required"
    command(target, "switch", "-c", "work/summary-fixture")
    command(target, "add", "hello.txt")
    command(target, "commit", "-m", "work fixture")
    source = command(target, "rev-parse", "HEAD")
    complete(client, task)
    assert not timeline(client, task)[0]["merge"]["verified"]
    command(repository, "merge", "--ff-only", source)
    result = client.post(path + f"/timeline/{row['id']}/verify", json={})
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "completed"
    assert result.json()["merge"]["source_commit"] == source
    assert result.json()["merge"]["integrated_head"] == source
    other = new_task(client)
    assert (
        client.post(f"/api/tasks/{other['id']}/timeline/{row['id']}/verify", json={}).status_code
        == 404
    )
    followup = send_message(client, task, text="Continue follow-up").json()
    assert followup["status"] == "running"
    assert timeline(client, task)[0]["state"] == "completed"


def test_auto_receipt_for_old_thread_and_discarded_changes_are_not_completed(client, repository):
    task = new_task(client)
    target = worktree(client, repository)
    body = merge_request(client, task, target)
    path = f"/api/tasks/{task['id']}"
    task = client.post(path + "/merge", json=body).json()
    command(target, "restore", "hello.txt")
    complete(client, task)
    assert timeline(client, task)[0]["state"] == "needs_attention"
    (target / "hello.txt").write_text("real completed work\n")
    command(target, "add", "hello.txt")
    command(target, "commit", "-m", "detached work")
    command(repository, "merge", "--ff-only", command(target, "rev-parse", "HEAD"))
    # Model need not call the tool: the accepted merge turn finishing also checks Git.
    with client.app.state.factory.begin() as db:
        row = db.scalar(select(TaskMilestone).where(TaskMilestone.task_id == task["id"]))
        assert row.merge["verified"] is False
    task_timeline.settle(client.app.state.factory, client.app.state.settings, task["id"])
    assert timeline(client, task)[0]["merge"]["verified"]


def test_changed_destination_and_unlinked_source_cannot_get_completion_receipt(client, repository):
    task = new_task(client)
    target = worktree(client, repository)
    body = merge_request(client, task, target)
    path = f"/api/tasks/{task['id']}"
    task = client.post(path + "/merge", json=body).json()
    command(target, "add", "hello.txt")
    command(target, "commit", "-m", "source")
    command(repository, "merge", "--ff-only", command(target, "rev-parse", "HEAD"))
    command(repository, "branch", "-m", "renamed-destination")
    complete(client, task)
    row = timeline(client, task)[0]
    assert row["merge"]["error_code"] == "merge_workspace_changed"
    assert not row["merge"]["verified"]
    command(repository, "branch", "-m", "dev")
    assert client.delete(path + "/git-links/" + body["link_id"]).status_code == 200
    row = client.post(path + f"/timeline/{row['id']}/verify", json={}).json()
    assert row["state"] == "needs_attention" and not row["merge"]["verified"]


def test_foreign_repository_and_busy_task_cannot_submit_merge(client, repository):
    task = new_task(client)
    root = client.app.state.settings.worktree_root / "foreign"
    root.mkdir(parents=True)
    command(root, "init", "-b", "work")
    command(
        root,
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "user.name=Test",
        "commit",
        "--allow-empty",
        "-m",
        "other repository",
    )
    linked = link(client, task, root).json()[-1]
    path = f"/api/tasks/{task['id']}"
    assert client.get(path + "/merge-target", params={"link_id": linked["id"]}).status_code == 409
    target = worktree(client, repository)
    body = merge_request(client, task, target)
    send_message(client, task)
    assert client.post(path + "/merge", json=body).status_code == 409
    assert timeline(client, task) == []


def test_git_receipt_does_not_erase_reported_validation_blocker(client, repository):
    task = new_task(client)
    source = worktree(client, repository)
    body = merge_request(client, task, source)
    path = f"/api/tasks/{task['id']}"
    task = client.post(path + "/merge", json=body).json()
    row = timeline(client, task)[0]
    args = dict(
        action="update",
        key=row["key"],
        title=row["title"],
        phase="validation",
        state="needs_attention",
        summary="A required test failed",
    )
    assert call(client, task, args)[0]
    command(source, "add", "hello.txt")
    command(source, "commit", "-m", "source")
    command(repository, "merge", "--ff-only", command(source, "rev-parse", "HEAD"))
    ok, result = call(client, task, dict(action="verify_merge", key=row["key"]))
    assert ok and result["merge"]["verified"] and result["state"] == "needs_attention"
    ok, result = call(client, task, {**args, "state": "completed", "summary": "Fixed and checked"})
    assert ok and result["state"] == "completed"


def test_plain_language_summary_is_persisted_and_retries_do_not_duplicate_it(client):
    task = send_message(client, new_task(client)).json()
    args = dict(
        action="update",
        key="answer-ui",
        title="Answer UI",
        phase="implementation",
        state="in_progress",
        summary="Updated UI component, checks pending",
        headline="질문 답변\n화면 수정",
        one_line="화면에서   답변할 수 있도록 수정하고 있습니다.",
    )
    ok, result = call(client, task, args)
    assert ok
    phase = result["phases"]["implementation"]
    assert phase["headline"] == "질문 답변 화면 수정"
    assert phase["one_line"] == "화면에서 답변할 수 있도록 수정하고 있습니다."
    with client.app.state.factory() as db:
        count = db.scalar(select(func.count()).select_from(Event))
    assert call(client, task, args)[0]
    with client.app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Event)) == count
    assert timeline(client, task)[0]["phases"]["implementation"] == phase
    old_schema = {k: v for k, v in args.items() if k not in ("headline", "one_line")}
    assert (
        call(client, task, old_schema)[1]["phases"]["implementation"]["headline"]
        == phase["headline"]
    )
    assert call(client, task, {**old_schema, "summary": "Checks now passed", "state": "completed"})[
        0
    ]
    assert timeline(client, task)[0]["phases"]["implementation"]["headline"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"headline": "Missing description"},
        {"headline": "x" * 81, "one_line": "description"},
        {"headline": "title", "one_line": "x" * 181},
        {"headline": "  \n", "one_line": "description"},
    ],
)
def test_invalid_plain_language_summary_does_not_modify_the_timeline(client, fields):
    task = send_message(client, new_task(client)).json()
    ok, result = call(
        client,
        task,
        dict(
            action="update",
            key="invalid",
            title="Work",
            phase="start",
            state="in_progress",
            summary="Started",
            **fields,
        ),
    )
    assert not ok and result["error"] == "invalid_input"
    assert timeline(client, task) == []
