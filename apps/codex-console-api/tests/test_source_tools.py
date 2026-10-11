"""Local app saving must not depend on short-lived platform delivery authority."""

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import complete, new_task, send_message
from test_app_sources import app_checkout as app_checkout
from test_app_sources import command
from test_registration_draft import project
from test_remote_runtime import native_task as native_task

from codex_console import registration_tools, source_tools, store
from codex_console.models import AppSourceBinding, RegistrationIntent, Task


def invoke(client, task, runtime, *, action="checkpoint", **overrides):
    params = {
        "callId": "local-save-call",
        "tool": source_tools.TOOL_NAME,
        "threadId": task["thread_id"],
        "turnId": task["turn_id"],
        "arguments": {"action": action},
        **overrides,
    }
    client.portal.call(
        lambda: runtime.server_request(
            {"id": "local-save-request", "method": "item/tool/call", "params": params},
            generation=runtime.rpc.generation,
        )
    )
    value = runtime.rpc.responses[-1][1]
    return value["success"], json.loads(value["contentItems"][0]["text"])


def start_implementation(client, task):
    planning = send_message(client, task)
    assert planning.status_code == 200
    planned = complete(client, planning.json())
    result = client.post(
        f"/api/tasks/{task['id']}/implement",
        json={
            "operation_id": str(uuid4()),
            "revision_id": planned["revisions"][-1]["id"],
            "permissions": "ask",
        },
    )
    assert result.status_code == 200
    return result.json()


def test_development_thread_offers_local_save_before_first_registration(
    client, app_checkout, native_task
):
    task, runtime = native_task
    row = project(client, reuse="extend")
    (app_checkout / "README.md").write_text("App implementation awaiting its first checkpoint")
    draft = client.get(f"/api/workbench/projects/{row['id']}/registration-draft")
    assert draft.status_code == 409 and draft.json()["code"] == "app_source_dirty"
    response = send_message(client, task)
    assert response.status_code == 200
    start = next(params for method, params in runtime.rpc.calls if method == "thread/start")
    assert "miy_app_source" in [tool["name"] for tool in start["dynamicTools"]]


def test_approved_development_saves_without_grants_then_can_request_registration_consent(
    client, settings, app_checkout, native_task, monkeypatch
):
    from codex_console import delivery_tools, registration

    def forbidden(*args, **kwargs):
        pytest.fail("A local source checkpoint must not contact the platform")

    monkeypatch.setattr(registration, "api", forbidden)
    monkeypatch.setattr(delivery_tools, "api_request", forbidden)
    assert not settings.registration_authorization_enabled
    assert settings.app_delivery_grants == []
    task, runtime = native_task
    row = project(client, reuse="extend")
    task = start_implementation(client, task)
    previous = command(app_checkout, "rev-parse", "HEAD")
    (app_checkout / "README.md").write_text("Approved app implementation")
    success, context = invoke(client, task, runtime, action="context")
    assert success and context["dirty"] and context["source_revision"] == previous
    assert context["external_authorization_required"] is False
    success, saved = invoke(client, task, runtime)
    assert success and saved["created"] and saved["source_revision"] != previous
    assert command(app_checkout, "status", "--porcelain") == ""
    assert command(app_checkout, "rev-parse", "HEAD^") == previous
    assert invoke(client, task, runtime) == (
        True,
        {"source_revision": saved["source_revision"], "created": False},
    )
    draft = client.get(f"/api/workbench/projects/{row['id']}/registration-draft")
    assert draft.status_code == 200
    assert draft.json()["source_revision"] == saved["source_revision"]
    complete(client, task, "Local app implementation saved")
    with client.app.state.factory() as db:
        assert db.get(RegistrationIntent, task["id"]) is None

    settings.registration_authorization_enabled = True
    settings.miy_api_origin = "https://platform.example.test"
    settings.sso_subjects = {settings.miy_api_origin: uuid4()}
    registered = client.post(
        "/api/tasks",
        json={
            "title": "Request first registration",
            "context": {"purpose": "registration", "project_id": row["id"]},
        },
    )
    assert registered.status_code == 200
    registration_id = registered.json()["id"]
    with client.app.state.factory() as db:
        assert source_tools.specs(db.get(Task, registration_id)) == []
    consent = client.post(
        f"/api/tasks/{registration_id}/registration/authorize",
        json={"origin": "https://preview.example.test"},
    )
    assert consent.status_code == 200
    with client.app.state.factory() as db:
        intent = db.get(RegistrationIntent, registration_id)
        assert intent.authorization_state == "pending" and intent.grant_id is None


@pytest.mark.parametrize(
    "boundary", ["child", "turn", "read_only", "binding", "project", "purpose"]
)
def test_local_save_denial_preserves_source_and_git_metadata(
    client, settings, app_checkout, native_task, boundary
):
    task, runtime = native_task
    if boundary == "read_only":
        task = send_message(client, task).json()
    else:
        task = start_implementation(client, task)
    overrides = {}
    if boundary == "child":
        overrides["threadId"] = "unowned-native-child"
    elif boundary == "turn":
        overrides["turnId"] = "old-native-turn"
    elif boundary in ("binding", "project", "purpose"):
        with client.app.state.factory.begin() as db:
            stored = db.get(Task, task["id"])
            if boundary == "binding":
                db.get(AppSourceBinding, "sample-app").version += 1
            else:
                stored.context = {
                    **stored.context,
                    **(
                        {"project_id": "missing-project"}
                        if boundary == "project"
                        else {"purpose": "registration"}
                    ),
                }
    (app_checkout / "README.md").write_text("App files must survive a rejected save")
    head = command(app_checkout, "rev-parse", "HEAD")
    index = (app_checkout / ".git/index").read_bytes()
    success, result = invoke(client, task, runtime, **overrides)
    assert not success
    assert result["error"] == (
        "app_source_changed" if boundary in ("binding", "project") else "app_source_save_denied"
    )
    assert command(app_checkout, "rev-parse", "HEAD") == head
    assert (app_checkout / ".git/index").read_bytes() == index
    assert (app_checkout / "README.md").read_text() == "App files must survive a rejected save"


def test_local_tool_rejects_model_selected_paths_and_external_operations():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        source_tools.Arguments(action="checkpoint", path="/other/app")
    for action in ("register", "deploy", "push"):
        with pytest.raises(ValidationError):
            source_tools.Arguments(action=action)
    assert registration_tools.TOOL_NAME != source_tools.TOOL_NAME


def test_binding_change_before_checkpoint_head_cas_is_denied(
    client, app_checkout, native_task, monkeypatch
):
    from codex_console import app_checkpoints

    task, runtime = native_task
    task = start_implementation(client, task)
    (app_checkout / "README.md").write_text("Save approval must remain current")
    head = command(app_checkout, "rev-parse", "HEAD")
    index = (app_checkout / ".git/index").read_bytes()
    original = app_checkpoints._git

    def change_binding(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[0] == "commit-tree":
            with client.app.state.factory.begin() as db:
                db.get(AppSourceBinding, "sample-app").version += 1
        return result

    monkeypatch.setattr(app_checkpoints, "_git", change_binding)
    assert invoke(client, task, runtime) == (False, {"error": "app_source_changed"})
    assert command(app_checkout, "rev-parse", "HEAD") == head
    assert (app_checkout / ".git/index").read_bytes() == index
    assert not (app_checkout / ".git/index.lock").exists()


def test_all_app_tools_follow_pinned_native_thread_start_schema():
    from jsonschema import Draft7Validator

    from codex_console import delivery_tools
    from codex_console.rpc import CONTRACT

    task = SimpleNamespace(
        context={"purpose": "development", "source_binding": {"app_id": "sample-app"}}
    )
    tools = source_tools.specs(task)
    task.context["purpose"] = "registration"
    tools += registration_tools.specs(task)
    task.context["installation_id"] = str(uuid4())
    tools += delivery_tools.specs(task)
    assert len(tools) == 3
    Draft7Validator(CONTRACT["schemas"]["ThreadStartParams"]).validate(
        {"cwd": "/synthetic/app", "dynamicTools": tools}
    )


@pytest.mark.parametrize("is_app", [False, True])
def test_unbound_app_planning_disables_host_procedures_without_changing_core(client, is_app):
    from codex_console.runtime import APP_WORKFLOW, WORKFLOW

    if is_app:
        row = project(client)
        response = client.post(
            "/api/tasks",
            json={"title": "Plan an app", "context": {"project_id": row["id"]}},
        )
        assert response.status_code == 200
        task = response.json()
    else:
        task = new_task(client)
    response = send_message(client, task)
    assert response.status_code == 200
    rpc = client.app.state.runtime.rpc
    start = next(params for method, params in rpc.calls if method == "thread/start")
    assert start["developerInstructions"] == (APP_WORKFLOW if is_app else WORKFLOW)
    for feature, value in (
        ("skip_host_skill_discovery", True),
        ("hooks", False),
        ("skill_mcp_dependency_install", False),
        ("shell_snapshot", False),
        ("shell_snapshot_v2", False),
    ):
        if is_app:
            assert start["config"]["features." + feature] is value
        else:
            assert "features." + feature not in start["config"]
    if is_app:
        task = complete(client, response.json())
        denied = client.post(
            f"/api/tasks/{task['id']}/messages",
            json={
                "stage": "plan",
                "text": "Use a host procedure",
                "operation_id": str(uuid4()),
                "skill_names": ["legacy-host-procedure"],
            },
        )
        assert denied.status_code == 422
        assert denied.json()["code"] == "app_host_skills_unavailable"
        assert not any(method == "skills/list" for method, _ in rpc.calls)


def test_new_development_context_recovers_same_project_native_plan_without_authorizing_writes(
    client, settings, app_checkout, native_task
):
    task, runtime = native_task
    row = project(client, reuse="extend")
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, task["id"])
        selected.context = {**selected.context, "project_id": row["id"]}
        previous = Task(
            id=str(uuid4()),
            title="Earlier app planning",
            root=str(settings.workspace),
            context={
                "app_id": "sample-app",
                "project_id": row["id"],
                "app_execution_boundary": "planning_only",
            },
            created_at=selected.created_at - timedelta(seconds=1),
        )
        db.add(previous)
        plan = store.save_revision(
            db,
            previous,
            "plan",
            "Confirmed business decisions and the final implementation plan",
            source_turn_id="completed-native-planning-turn",
        )
        reference_id = plan.id
        previous_id = previous.id
    task = send_message(client, task).json()
    success, context = invoke(client, task, runtime, action="context")
    assert success
    assert context["prior_plan"] == {
        "task_id": previous_id,
        "revision_id": reference_id,
        "version": 1,
        "body": "Confirmed business decisions and the final implementation plan",
        "truncated": False,
        "reference_only": True,
        "execution_authorized": False,
    }
    (app_checkout / "README.md").write_text("Referenced plan does not approve a checkpoint")
    previous_head = command(app_checkout, "rev-parse", "HEAD")
    assert invoke(client, task, runtime) == (False, {"error": "app_source_save_denied"})
    assert command(app_checkout, "rev-parse", "HEAD") == previous_head
    with client.app.state.factory() as db:
        assert db.get(Task, task["id"]).approved_revision is None


@pytest.mark.parametrize(
    "boundary", ["core", "foreign_project", "foreign_app", "current", "later", "manual"]
)
def test_plan_context_excludes_other_scopes_and_non_native_revisions(
    client, settings, native_task, boundary
):
    task, _ = native_task
    row = project(client, reuse="extend")
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, task["id"])
        selected.context = {**selected.context, "project_id": row["id"]}
        context = {"app_id": "sample-app", "project_id": row["id"]}
        if boundary == "core":
            context = None
        elif boundary == "foreign_project":
            context["project_id"] = str(uuid4())
        elif boundary == "foreign_app":
            context["app_id"] = "another-app"
        previous = (
            selected
            if boundary == "current"
            else Task(
                id=str(uuid4()),
                title="A plan outside the reference boundary",
                root=str(settings.workspace),
                context=context,
                created_at=selected.created_at
                + timedelta(seconds=1 if boundary == "later" else -1),
            )
        )
        if previous is not selected:
            db.add(previous)
        store.save_revision(
            db,
            previous,
            "plan",
            "This plan must not enter the app context",
            source_turn_id=None if boundary == "manual" else "completed-other-turn",
        )
        db.expunge(selected)
    assert source_tools.prior_plan(client.app.state.factory, selected) is None


def test_prior_plan_uses_latest_final_revision_with_bounded_utf8_reference(
    client, settings, native_task
):
    task, _ = native_task
    row = project(client, reuse="extend")
    with client.app.state.factory.begin() as db:
        selected = db.get(Task, task["id"])
        selected.context = {**selected.context, "project_id": row["id"]}
        previous = Task(
            id=str(uuid4()),
            title="Earlier native plan",
            root=str(settings.workspace),
            context={"app_id": "sample-app", "project_id": row["id"]},
            created_at=selected.created_at - timedelta(seconds=1),
        )
        db.add(previous)
        store.save_revision(db, previous, "plan", "Earlier decision", source_turn_id="first-turn")
        body = "가" * 10000
        latest = store.save_revision(db, previous, "plan", body, source_turn_id="latest-turn")
        reference_id = latest.id
        # A later manual document is not a completed native plan reference.
        store.save_revision(db, previous, "plan", "Manual draft")
        db.expunge(selected)
    reference = source_tools.prior_plan(client.app.state.factory, selected)
    assert reference["revision_id"] == reference_id and reference["version"] == 2
    assert reference["body"] == "가" * (source_tools.MAX_PRIOR_PLAN_BYTES // 3)
    assert len(reference["body"].encode()) <= source_tools.MAX_PRIOR_PLAN_BYTES
    assert reference["truncated"] and reference["reference_only"]
    assert reference["execution_authorized"] is False
