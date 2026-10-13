import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import complete, new_task

from codex_console import git, task_environments
from codex_console.models import Task


@pytest.fixture
def environments(client, repository):
    settings = client.app.state.settings
    settings.project_root = repository.parent
    prod = repository.parent / "prod"
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "-b", "main", str(prod)],
        check=True,
        capture_output=True,
    )
    settings.production_workspace = prod
    settings.protected_workspaces = [prod]
    settings.branch_setup_command = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    return settings


def create(client, kind, **extra):
    return client.post(
        "/api/tasks", json={"title": "Environment test", "environment": kind, **extra}
    )


def send(client, task, stage="plan", **extra):
    return client.post(
        f"/api/tasks/{task['id']}/" + ("messages" if stage == "plan" else "implement"),
        json={"operation_id": str(uuid4()), "text": "Inspect the selected target", **extra},
    )


def prepared(client, task):
    for _ in range(200):
        detail = client.get(f"/api/tasks/{task['id']}").json()
        if detail["context"]["task_environment"]["preparation"]["state"] in ("ready", "failed"):
            return detail
        time.sleep(0.02)
    pytest.fail("Preparation did not settle")


def test_environment_options_require_explicit_profiles(client):
    options = {row["kind"]: row for row in client.get("/api/task-environments").json()}
    assert options["development"]["available"]
    assert not options["general"]["available"]
    assert not options["production"]["available"]
    assert not options["branch"]["available"]
    assert create(client, "production").status_code == 409
    assert create(client, "general").status_code == 409


def test_empty_optional_core_roots_keep_the_example_profiles_disabled(settings):
    from codex_console.config import Settings

    values = settings.model_dump()
    values.update(project_root="", production_workspace="")
    selected = Settings(**values, _env_file=None)
    assert selected.project_root is None and selected.production_workspace is None


@pytest.mark.parametrize("client_role", ["management"], indirect=True)
def test_environment_selection_is_served_by_the_management_process(client):
    response = client.get("/api/task-environments")
    assert response.status_code == 200
    assert {option["kind"] for option in response.json()} == {
        "general",
        "development",
        "branch",
        "existing_branch",
        "production",
    }


@pytest.mark.parametrize("permissions", ["ask", "yolo"])
@pytest.mark.parametrize("approve_plan", [False, True])
def test_general_non_git_root_and_existing_development_requests(
    client, environments, repository, permissions, approve_plan
):
    environments.binary = "/opt/latest-codex/bin/codex"
    general = create(client, "general").json()
    assert general["root"] == str(repository.parent)
    assert general["implementation_permissions"] == ["ask", "yolo"]
    status = client.get(f"/api/tasks/{general['id']}/git").json()
    assert status["available"] is False and status["detached"] is False
    assert client.get(f"/api/tasks/{general['id']}/changes").json() == []
    turn = send(client, general)
    assert turn.status_code == 200
    start = [p for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"][-1]
    assert start["cwd"] == str(repository.parent)
    assert start["sandboxPolicy"]["type"] == "readOnly"
    thread = [p for m, p in client.app.state.runtime.rpc.calls if m == "thread/start"][-1]
    allowed_env = thread["config"]["shell_environment_policy.include_only"]
    assert "PYTHONPATH" not in allowed_env and not any(
        name.startswith("MIY_") for name in allowed_env
    )
    assert thread["config"]["features.shell_snapshot"] is False
    assert thread["config"]["shell_environment_policy.set"]["PATH"].startswith(
        "/opt/latest-codex/bin:"
    )
    planned = complete(client, turn.json())
    approval = {"revision_id": planned["revisions"][-1]["id"]} if approve_plan else {}
    execution = send(client, general, "implement", permissions=permissions, **approval)
    assert execution.status_code == 200
    assert execution.json()["permissions"] == permissions
    start = [p for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"][-1]
    assert start["cwd"] == str(repository.parent)
    assert start["approvalPolicy"] == ("never" if permissions == "yolo" else "on-request")
    assert start["sandboxPolicy"]["type"] == (
        "dangerFullAccess" if permissions == "yolo" else "workspaceWrite"
    )
    complete(client, execution.json())
    assert send(client, general).status_code == 200
    start = [p for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"][-1]
    assert start["sandboxPolicy"]["type"] == "readOnly"
    dev = create(client, "development").json()
    assert dev["root"] == str(repository)
    assert new_task(client)["root"] == str(repository)


def test_production_is_exact_read_only_exception_not_a_write_permission(client, environments):
    prod = create(client, "production").json()
    assert prod["root"] == str(environments.production_workspace)
    assert prod["implementation_permissions"] == []
    assert send(client, prod, "implement").json()["code"] == "production_read_only"
    assert send(client, prod, "implement", permissions="yolo").status_code == 403
    assert client.get(f"/api/tasks/{prod['id']}/git").status_code == 200
    assert client.get(f"/api/tasks/{prod['id']}/changes").status_code == 200
    assert send(client, prod).status_code == 200
    params = [p for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"][-1]
    assert params["cwd"] == prod["root"] and params["sandboxPolicy"]["type"] == "readOnly"


def test_production_root_change_is_blocked_before_native_execution(client, environments):
    task = create(client, "production").json()
    with client.app.state.factory.begin() as db:
        db.get(Task, task["id"]).root = str(environments.workspace)
    assert send(client, task).json()["code"] == "task_environment_changed"
    assert not client.app.state.runtime.rpc


def test_root_writer_locks_overlapping_development_checkout(client, environments):
    general = create(client, "general").json()
    assert send(client, general, "implement").status_code == 200
    dev = create(client, "development").json()
    result = send(client, dev, "implement")
    assert result.status_code == 409 and result.json()["code"] == "workspace_busy"
    result = create(client, "branch", branch_name="feature/blocked")
    assert result.status_code == 409 and result.json()["code"] == "workspace_busy"
    assert not git.git(environments.workspace, "branch", "--list", "feature/blocked").strip()
    complete(client, client.get(f"/api/tasks/{general['id']}").json())
    assert send(client, dev, "implement").status_code == 200


def test_named_branch_preparation_preserves_dev_dirty_state(client, environments, repository):
    (repository / "uncommitted.txt").write_text("preserve")
    task = create(client, "branch", branch_name="feature/console-test").json()
    task = prepared(client, task)
    assert task["context"]["task_environment"]["preparation"]["state"] == "ready"
    assert task["isolated"]
    assert git.status(Path(task["root"]))["branch"] == "feature/console-test"
    assert git.status(repository)["branch"] == "dev"
    assert (repository / "uncommitted.txt").read_text() == "preserve"
    assert not (Path(task["root"]) / "uncommitted.txt").exists()
    assert send(client, task).status_code == 200


@pytest.mark.parametrize(
    "name", ["dev", "main", "HEAD", "../escape", "--force", "bad name", "a..b"]
)
def test_invalid_or_protected_branch_is_rejected(client, environments, name):
    assert create(client, "branch", branch_name=name).status_code == 422


def test_existing_branch_is_not_adopted(client, environments):
    subprocess.run(
        ["git", "-C", str(environments.workspace), "branch", "feature/existing"], check=True
    )
    result = create(client, "branch", branch_name="feature/existing")
    assert result.status_code == 409 and result.json()["code"] == "branch_exists"


def test_failed_dependency_preparation_blocks_turns_and_retries_owned_checkout(
    client, environments
):
    environments.branch_setup_command = [sys.executable, "-c", "raise SystemExit(1)"]
    task = prepared(client, create(client, "branch").json())
    assert task["status"] == "failed" and task["error_code"] == "branch_setup_failed"
    assert send(client, task).json()["code"] == "task_environment_not_ready"
    root = task["root"]
    environments.branch_setup_command = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    assert client.post(f"/api/tasks/{task['id']}/prepare", json={}).status_code == 200
    resumed = prepared(client, task)
    assert resumed["status"] == "idle" and resumed["root"] == root
    assert resumed["context"]["task_environment"]["preparation"]["state"] == "ready"
    assert client.post(f"/api/tasks/{task['id']}/prepare", json={}).status_code == 200


def test_new_environment_cannot_override_app_or_arbitrary_path(client, environments):
    assert create(client, "general", context={"purpose": "development"}).status_code == 422
    assert create(client, "development", root="/tmp/arbitrary").status_code == 422
    assert create(client, "development", isolate=True).status_code == 422
    assert create(client, "general", branch_name="feature/x").status_code == 422


def test_startup_marks_interrupted_preparation_without_recreating_checkout(client, environments):
    task = prepared(client, create(client, "branch").json())
    with client.app.state.factory.begin() as db:
        row = db.get(Task, task["id"])
        context = dict(row.context)
        meta = dict(context["task_environment"])
        meta["preparation"] = {"state": "preparing", "step": "dependencies"}
        row.context = {**context, "task_environment": meta}
        row.status = "starting"
    task_environments.recover_startup(client.app.state.factory)
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert detail["error_code"] == "branch_setup_interrupted"
    assert Path(task["root"]).is_dir()


def add_worktree(settings, name="feature/existing", *, root=None, detached=False):
    root = root or settings.worktree_root / "existing"
    root.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "-C", str(settings.workspace), "worktree", "add"]
    command += ["--detach"] if detached else ["-b", name]
    subprocess.run([*command, str(root), "HEAD"], check=True, capture_output=True)
    return root


def test_existing_branch_reuses_dirty_checkout_without_preparation(client, environments):
    root = add_worktree(environments)
    (root / "uncommitted.txt").write_text("keep existing changes")
    (root / ".env").write_text("TEST_SETTING=preserve\n")
    environments.branch_setup_command = []
    options = {row["kind"]: row for row in client.get("/api/task-environments").json()}
    assert options["existing_branch"]["available"] and not options["branch"]["available"]
    response = create(client, "existing_branch", branch_name="feature/existing")
    assert response.status_code == 200
    task = response.json()
    assert task["root"] == str(root) and task["status"] == "idle"
    assert not task["isolated"] and task["thread_id"] is None
    assert task["context"]["task_environment"]["branch"] == "feature/existing"
    assert "preparation" not in task["context"]["task_environment"]
    assert send(client, task).status_code == 200
    assert [p for m, p in client.app.state.runtime.rpc.calls if m == "turn/start"][-1][
        "cwd"
    ] == str(root)
    assert (root / "uncommitted.txt").read_text() == "keep existing changes"
    assert (root / ".env").read_text() == "TEST_SETTING=preserve\n"
    assert git.status(environments.workspace)["branch"] == "dev"
    assert not (environments.worktree_root / f"codex-{task['id']}").exists()


def test_existing_worktree_list_excludes_other_paths_and_detached_branches(client, environments):
    root = add_worktree(environments)
    add_worktree(environments, "feature/outside", root=environments.workspace.parent / "outside")
    add_worktree(environments, root=environments.worktree_root / "detached", detached=True)
    subprocess.run(
        ["git", "-C", str(environments.workspace), "branch", "feature/no-worktree"], check=True
    )
    response = client.get("/api/task-environments/worktrees")
    assert response.status_code == 200
    assert response.json() == [
        {"branch": "feature/existing", "root": str(root), "available": True, "reason": None}
    ]
    for name in ("dev", "main", "feature/outside", "feature/no-worktree", "missing"):
        assert (
            create(client, "existing_branch", branch_name=name).json()["code"]
            == "worktree_unavailable"
        )
    assert create(client, "existing_branch").status_code == 422
    assert (
        create(
            client, "existing_branch", branch_name="feature/existing", root=str(root)
        ).status_code
        == 422
    )


def test_existing_branch_rejects_unready_environment_and_preserves_source_task(
    client, environments
):
    environments.branch_setup_command = [sys.executable, "-c", "raise SystemExit(1)"]
    source = prepared(client, create(client, "branch", branch_name="feature/unfinished").json())
    rows = client.get("/api/task-environments/worktrees").json()
    assert rows[0]["available"] is False and rows[0]["reason"] == "task_environment_not_ready"
    assert (
        create(client, "existing_branch", branch_name="feature/unfinished").json()["code"]
        == "task_environment_not_ready"
    )
    environments.branch_setup_command = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    assert client.post(f"/api/tasks/{source['id']}/prepare", json={}).status_code == 200
    source = prepared(client, source)
    resumed = create(client, "existing_branch", branch_name="feature/unfinished").json()
    assert resumed["root"] == source["root"] and resumed["id"] != source["id"]
    assert send(client, resumed, "implement").status_code == 200
    conflict = send(client, source, "implement")
    assert conflict.status_code == 409 and conflict.json()["code"] == "workspace_busy"


@pytest.mark.parametrize("change", ["branch", "removed", "protected", "locked", "symlink"])
def test_existing_worktree_is_revalidated_before_execution(client, environments, change):
    root = add_worktree(environments)
    task = create(client, "existing_branch", branch_name="feature/existing").json()
    if change == "branch":
        subprocess.run(
            ["git", "-C", str(root), "switch", "-c", "feature/changed"],
            check=True,
            capture_output=True,
        )
    elif change == "removed":
        subprocess.run(
            ["git", "-C", str(environments.workspace), "worktree", "remove", str(root)], check=True
        )
    elif change == "protected":
        environments.protected_workspaces.append(root)
    elif change == "locked":
        subprocess.run(
            ["git", "-C", str(environments.workspace), "worktree", "lock", str(root)], check=True
        )
    else:
        destination = root.with_name("relocated")
        root.rename(destination)
        root.symlink_to(destination, target_is_directory=True)
    assert send(client, task).json()["code"] == "task_environment_changed"
    assert not client.app.state.runtime.rpc
    assert create(client, "existing_branch", branch_name="feature/existing").status_code == 409


@pytest.mark.parametrize("client_role", ["management"], indirect=True)
def test_existing_worktree_list_requires_authentication(client, environments):
    add_worktree(environments)
    assert client.get("/api/task-environments/worktrees").status_code == 200
    client.cookies.clear()
    assert client.get("/api/task-environments/worktrees").status_code == 401


def test_existing_worktree_requires_its_persisted_branch_identity(client, environments):
    add_worktree(environments)
    task = create(client, "existing_branch", branch_name="feature/existing").json()
    with client.app.state.factory.begin() as db:
        row = db.get(Task, task["id"])
        meta = dict(row.context["task_environment"])
        del meta["branch"]
        row.context = {"task_environment": meta}
    assert send(client, task).json()["code"] == "task_environment_changed"
    assert not client.app.state.runtime.rpc
