"""Owner-selected repositories and immutable task roots never follow app instructions."""

import json
import subprocess
from pathlib import Path

import pytest
from conftest import send_message
from sqlalchemy import select

from codex_console import app_sources, git
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.models import AppSourceBinding, Task, WorkbenchObservation


def command(root, *args):
    return (
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        .stdout.decode()
        .strip()
    )


@pytest.fixture
def app_checkout(settings, tmp_path):
    root = tmp_path / "apps" / "sample-app"
    root.mkdir(parents=True)
    settings.app_source_roots = [root.parent]
    settings.app_execution_environments = [
        AppExecutionEnvironment(
            key="sample-app-v1",
            source_root=root,
            exec_server_url="ws://127.0.0.1:19391",
            auth_bearer_token="synthetic-executor-token-" + "x" * 32,
        )
    ]
    command(root, "init", "-b", "main")
    command(root, "config", "user.email", "test@example.test")
    command(root, "config", "user.name", "Test")
    command(root, "remote", "add", "origin", "git@example.test:team/sample-app.git")
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[3] / "templates/independent-app/app.manifest.json"
        ).read_text()
    )
    (root / "app.manifest.json").write_text(json.dumps(manifest))
    (root / "README.md").write_text("App source")
    command(root, "add", ".")
    command(root, "commit", "-m", "fixture")
    return root


def bind(client, root, version=0):
    return client.put(
        "/api/workbench/apps/sample-app/source",
        json={"repository_root": str(root), "version": version},
    )


def launch(client, *, isolate=False):
    return client.post(
        "/api/tasks",
        json={
            "title": "App task",
            "isolate": isolate,
            "context": {"app_id": "sample-app", "purpose": "development"},
        },
    )


def test_explicit_source_binding_uses_repository_without_guessing_release(
    client, settings, app_checkout
):
    result = bind(client, app_checkout)
    assert result.status_code == 200, result.text
    app = result.json()
    assert app["source_status"] == "ready" and app["release_unit"] is None
    assert app["execution_status"] == "configured"
    assert app["source_root"] == str(app_checkout) and app["source_version"] == 1
    assert bind(client, app_checkout).status_code == 409
    assert client.get("/api/workbench/catalog").json()["items"][0]["app_id"] == "sample-app"
    task = launch(client).json()
    assert task["root"] == str(app_checkout)
    assert task["context"]["source_binding"]["revision"] == command(
        app_checkout, "rev-parse", "HEAD"
    )
    assert task["context"]["release_unit"] is None
    settings.worktree_base_ref = "origin/core-only-ref"
    isolated = launch(client, isolate=True)
    assert isolated.status_code == 422
    assert isolated.json()["code"] == "app_executor_worktree_unsupported"
    with client.app.state.factory() as db:
        source = db.scalar(select(AppSourceBinding))
        assert source.repository_root == str(app_checkout)
        app_sources.require_task_source(settings, db.get(Task, task["id"]))


def test_runtime_only_registration_visible_and_binding_compares_registry_identity(
    client, settings, app_checkout
):
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
                                "app_id": "sample-app",
                                "title": "Registered name",
                                "title_translations": {"ko-KR": "등록 앱"},
                                "icon_key": "puzzle",
                                "enabled": True,
                                "release_unit": "independent-app:sample-app",
                                "runtime_ai": False,
                                "source_repository": "https://example.test/another/repo.git",
                            }
                        ]
                    },
                },
            )
        )
    catalog = client.get("/api/workbench/catalog").json()["items"]
    assert catalog[0]["discovery"] == "runtime" and catalog[0]["source_status"] == "unconfigured"
    assert catalog[0]["title"] == "Registered name"
    assert launch(client).status_code == 422
    assert bind(client, app_checkout).status_code == 409
    with client.app.state.factory.begin() as db:
        row = db.get(WorkbenchObservation, "runtime-catalog")
        payload = json.loads(json.dumps(row.payload))
        payload["data"]["items"][0]["source_repository"] = (
            "https://example.test/team/sample-app.git"
        )
        row.payload = payload
    result = bind(client, app_checkout)
    assert result.status_code == 200, result.text
    assert result.json()["title"] == "Registered name"
    assert result.json()["release_unit"] == "independent-app:sample-app"


def test_existing_task_can_repair_manifest_but_new_tasks_cannot_adopt_invalid_source(
    client, app_checkout
):
    assert bind(client, app_checkout).status_code == 200
    task = launch(client).json()
    (app_checkout / "app.manifest.json").write_text("malformed")
    assert launch(client).status_code == 422
    assert bind(client, app_checkout, version=1).status_code == 422
    response = send_message(client, task)
    assert response.status_code == 200, response.text
    runtime = client.app.state.runtime.for_task(task["id"])
    assert runtime.rpc.calls[-1][1]["cwd"] == str(app_checkout)


def test_rebinding_only_affects_new_tasks_and_current_owner_policy_still_applies(
    client, settings, app_checkout
):
    assert bind(client, app_checkout).status_code == 200
    old = launch(client).json()
    other = app_checkout.parent / "replacement"
    command(app_checkout.parent, "clone", "--no-hardlinks", str(app_checkout), str(other))
    command(other, "remote", "set-url", "origin", "https://example.test/team/sample-app.git")
    assert bind(client, other, version=1).status_code == 200
    settings.app_execution_environments.append(
        settings.app_execution_environments[0].model_copy(
            update={"key": "replacement-v1", "source_root": other}
        )
    )
    assert launch(client).json()["root"] == str(other)
    with client.app.state.factory() as db:
        task = db.get(Task, old["id"])
        app_sources.require_task_source(settings, task)
        assert task.root == str(app_checkout)
        settings.app_source_roots = [other]
        with pytest.raises(ConsoleError, match="app_source_denied"):
            app_sources.require_task_source(settings, task)


def test_connected_source_does_not_imply_configured_executor(client, settings, app_checkout):
    environment = settings.app_execution_environments.pop()
    app = bind(client, app_checkout).json()
    assert app["source_status"] == "ready"
    assert app["execution_status"] == "unconfigured"
    assert "executor_not_configured" in app["limitations"]
    response = launch(client)
    assert response.status_code == 503
    assert response.json()["code"] == "app_executor_unavailable"
    with client.app.state.factory() as db:
        assert list(db.scalars(select(Task))) == []
    settings.app_execution_environments.append(environment)
    app = client.get("/api/workbench/catalog").json()["items"][0]
    assert app["execution_status"] == "configured"
    assert "executor_not_configured" not in app["limitations"]
    assert launch(client).status_code == 200
    settings.app_execution_environments.clear()
    app = client.get("/api/workbench/catalog").json()["items"][0]
    assert app["execution_status"] == "unconfigured"
    assert launch(client).status_code == 503


@pytest.mark.parametrize(
    "unsafe",
    [
        "not_allowed",
        "wrong_app",
        "wrong_remote",
        "symlink",
        "protected",
        "external_gitdir",
        "directory_traversal",
    ],
)
def test_source_boundary_rejects_unsafe_binding(client, settings, app_checkout, tmp_path, unsafe):
    selected = app_checkout
    if unsafe == "not_allowed":
        settings.app_source_roots = []
    elif unsafe == "wrong_app":
        path = app_checkout / "app.manifest.json"
        value = json.loads(path.read_text())
        value["app_id"] = "other-app"
        path.write_text(json.dumps(value))
    elif unsafe == "wrong_remote":
        command(app_checkout, "remote", "set-url", "origin", "https://example.test/other.git")
    elif unsafe == "symlink":
        selected = app_checkout.parent / "alias"
        selected.symlink_to(app_checkout, target_is_directory=True)
    elif unsafe == "protected":
        settings.protected_workspaces = [app_checkout]
    elif unsafe == "external_gitdir":
        selected = app_checkout.parent / "redirect"
        selected.mkdir()
        (selected / ".git").write_text(f"gitdir: {app_checkout / '.git'}")
        (selected / "app.manifest.json").write_text(
            (app_checkout / "app.manifest.json").read_text()
        )
    else:
        path = app_checkout / "app.manifest.json"
        value = json.loads(path.read_text())
        value["source"]["directory"] = "../sample-app"
        path.write_text(json.dumps(value))
    assert bind(client, selected).status_code in (403, 422)


@pytest.mark.parametrize(
    "key",
    [
        "filter.evil.clean",
        "filter.evil.smudge",
        "filter.evil.process",
        "diff.evil.textconv",
        "remote.origin.promisor",
        "remote.origin.partialclonefilter",
        "extensions.partialClone",
    ],
)
def test_git_execution_helpers_and_lazy_fetch_are_rejected_before_execution(
    client, app_checkout, key
):
    marker = app_checkout.parent / "executed"
    command(app_checkout, "config", key, f"touch {marker}")
    (app_checkout / ".gitattributes").write_text("* filter=evil diff=evil")
    result = bind(client, app_checkout)
    assert result.status_code == 422, result.text
    assert result.json()["code"] == "app_source_git_policy"
    assert not marker.exists()


def test_server_git_disables_hooks_fsmonitor_and_transports(client, app_checkout):
    marker = app_checkout.parent / "executed"
    hook = app_checkout / ".git/hooks/post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o700)
    command(app_checkout, "config", "core.fsmonitor", str(hook))
    assert bind(client, app_checkout).status_code == 200
    task = launch(client).json()
    git.prepare_workspace(
        app_checkout,
        task["id"],
        base_ref="HEAD",
        worktree_root=client.app.state.settings.worktree_root,
    )
    with pytest.raises(ConsoleError):
        git.git(app_checkout, "ls-remote", app_checkout.as_uri())
    assert not marker.exists()


def test_owned_worktree_metadata_cannot_be_redirected_to_another_task(
    client, settings, app_checkout
):
    assert bind(client, app_checkout).status_code == 200
    first, second = launch(client).json(), launch(client).json()
    roots = []
    for selected in (first, second):
        root, owned = git.prepare_workspace(
            app_checkout, selected["id"], base_ref="HEAD", worktree_root=settings.worktree_root
        )
        assert owned
        roots.append(root)
        with client.app.state.factory.begin() as db:
            row = db.get(Task, selected["id"])
            row.root, row.worktree_owned = str(root), True
    first_root, second_root = roots
    (first_root / ".git").write_text((second_root / ".git").read_text())
    with client.app.state.factory() as db:
        with pytest.raises(ConsoleError, match="app_source_changed"):
            app_sources.require_task_source(settings, db.get(Task, first["id"]))


def test_changed_manifest_and_origin_do_not_retarget_an_accepted_binding(client, app_checkout):
    assert bind(client, app_checkout).status_code == 200
    path = app_checkout / "app.manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source"]["repository"] = "https://example.test/other/repository.git"
    path.write_text(json.dumps(manifest))
    command(app_checkout, "remote", "set-url", "origin", manifest["source"]["repository"])
    assert launch(client).status_code == 422


def test_concurrent_binding_updates_require_the_original_version(client, app_checkout):
    from concurrent.futures import ThreadPoolExecutor

    assert bind(client, app_checkout).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: bind(client, app_checkout, version=1), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
