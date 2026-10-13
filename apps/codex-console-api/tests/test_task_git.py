import json
import shutil
import subprocess

from conftest import new_task, send_message
from sqlalchemy import select

from codex_console.models import Task, TaskGitLink


def worktree(client, root, name="extra"):
    target = client.app.state.settings.worktree_root / name
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(target), "HEAD"],
        check=True,
        capture_output=True,
    )
    (target / "hello.txt").write_text("specific worktree change\n")
    return target


def link(client, task, root):
    return client.post(f"/api/tasks/{task['id']}/git-links", json={"root": str(root)})


def test_general_task_displays_only_explicit_links_and_scopes_diff(client, repository):
    task = new_task(client)
    with client.app.state.factory.begin() as db:
        row = db.get(Task, task["id"])
        row.root = str(repository.parent)
        # Legacy generic root is sufficient here; do not change execution selection.
    target = worktree(client, repository)
    unrelated = worktree(client, repository, "unrelated")
    path = f"/api/tasks/{task['id']}"
    assert client.get(path + "/git-links").json() == []
    response = link(client, task, target)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1 and rows[0]["root"] == str(target)
    assert str(unrelated) not in json.dumps(rows)
    row = rows[0]
    assert row["state"]["detached"] and row["state"]["changed"] == 1
    query = {"link_id": row["id"]}
    assert client.get(path + "/changes", params=query).json()[0]["path"] == "hello.txt"
    diff = client.get(path + "/diff", params={**query, "path": "hello.txt"})
    assert diff.status_code == 200 and "specific worktree change" in diff.text
    other = new_task(client)
    assert client.get(f"/api/tasks/{other['id']}/git", params=query).status_code == 404
    assert len(link(client, task, target).json()) == 1
    assert client.get(path).json()["root"] == str(repository.parent)


def test_initial_root_deduplicates_and_named_branch_is_read_live(client, repository):
    task = new_task(client)
    assert link(client, task, repository).json()[0]["id"] == "root"
    target = worktree(client, repository)
    row = link(client, task, target).json()[1]
    subprocess.run(
        ["git", "-C", str(target), "switch", "-c", "work/new-name"], check=True, capture_output=True
    )
    rows = client.get(f"/api/tasks/{task['id']}/git-links").json()
    assert rows[1]["state"]["branch"] == "work/new-name"
    assert rows[1]["id"] == row["id"]
    assert client.delete(f"/api/tasks/{task['id']}/git-links/{row['id']}").status_code == 200
    assert target.exists() and (target / "hello.txt").exists()


def test_missing_repointed_and_untrusted_paths_are_rejected(client, repository, tmp_path):
    task = new_task(client)
    target = worktree(client, repository)
    row = link(client, task, target).json()[1]
    alias = target.parent / "alias"
    alias.symlink_to(target)
    assert link(client, task, alias).status_code == 403
    assert link(client, task, tmp_path).status_code == 403
    assert link(client, task, target / "..").status_code == 403
    other = worktree(client, repository, "other")
    original = (target / ".git").read_text()
    (target / ".git").write_text((other / ".git").read_text())
    changed = client.get(f"/api/tasks/{task['id']}/git-links").json()[1]
    assert changed["state"] is None and changed["error_code"] == "git_link_changed"
    (target / ".git").write_text(original)
    shutil.rmtree(target)
    rows = client.get(f"/api/tasks/{task['id']}/git-links").json()
    assert rows[1]["state"] is None and rows[1]["error_code"]
    assert (
        client.get(
            f"/api/tasks/{task['id']}/diff", params={"link_id": row["id"], "path": "hello.txt"}
        ).status_code
        == 403
    )
    assert client.delete(f"/api/tasks/{task['id']}/git-links/{row['id']}").status_code == 200


def test_native_registration_tool_is_task_bound_and_display_only(client, repository):
    task = send_message(client, new_task(client)).json()
    runtime = client.app.state.runtime
    params = next(p for m, p in runtime.rpc.calls if m == "thread/start")
    assert params["dynamicTools"][0]["name"] == "miy_task_git"
    target = worktree(client, repository)
    message = {
        "id": 66,
        "method": "item/tool/call",
        "params": {
            "threadId": task["thread_id"],
            "turnId": task["turn_id"],
            "callId": "tool-call",
            "tool": "miy_task_git",
            "arguments": {"action": "register", "root": str(target)},
        },
    }
    client.portal.call(runtime.server_request, message)
    assert runtime.rpc.responses[-1][1]["success"] is True
    registered = json.loads(runtime.rpc.responses[-1][1]["contentItems"][0]["text"])
    # A later review or a retry can recover the same association without duplicating it.
    client.portal.call(runtime.server_request, message)
    assert json.loads(runtime.rpc.responses[-1][1]["contentItems"][0]["text"]) == registered
    message["params"]["arguments"] = {"action": "list"}
    client.portal.call(runtime.server_request, message)
    listed = json.loads(runtime.rpc.responses[-1][1]["contentItems"][0]["text"])["links"]
    assert [row["id"] for row in listed] == ["root", registered["id"]]
    assert listed[1]["root"] == str(target) and listed[1]["state"]["changed"] == 1
    with client.app.state.factory() as db:
        rows = list(db.scalars(select(TaskGitLink)))
        assert len(rows) == 1 and rows[0].task_id == task["id"] and rows[0].source == "agent"
        row = db.get(Task, task["id"])
        assert row.root == str(repository) and row.permissions == "read-only"
    message["params"]["turnId"] = "wrong-turn"
    client.portal.call(runtime.server_request, message)
    assert runtime.rpc.responses[-1][1]["success"] is False
