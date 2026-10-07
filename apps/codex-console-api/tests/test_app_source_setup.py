"""New source preparation never borrows a host execution grant or replaces personal files."""

import json
import os
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from codex_console import app_source_setup as setup
from codex_console.cli import migrate
from codex_console.config import Settings
from codex_console.models import AppSourceBinding, AppSourceSetup, Task, WorkbenchProject, database
from codex_console.workbench_schemas import SourceSetupInput


@pytest.fixture
def creation_root(settings, tmp_path):
    root = tmp_path / "created-apps"
    root.mkdir(mode=0o700)
    settings.app_source_roots = [root]
    settings.app_creation_roots = [root]
    return root


def project(client, app_id="new-app"):
    response = client.post(
        "/api/workbench/projects",
        json={
            "app_id": app_id,
            "title": "신청 앱",
            "summary": "간단한 신청을 기록한다.",
            "reuse_decision": "new",
            "reuse_notes": "별도 개인 앱이 필요하다.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def request(client, row, template="basic"):
    options = client.get("/api/workbench/source-setup/options").json()
    return {
        "operation_id": str(uuid4()),
        "repository": "https://example.test/team/new-app.git",
        "root_id": options["roots"][0]["id"],
        "template_id": template,
        "expected_bundle_digest": options["templates"][0]["bundle_digest"],
    }


def prepare(client, row, body):
    return client.post(f"/api/workbench/projects/{row['id']}/source-setup", json=body)


def status(client, row):
    return client.get(f"/api/workbench/projects/{row['id']}/source-setup").json()["setup"]


@pytest.mark.parametrize("template", ["basic", "private-notes"])
def test_fixed_starter_creates_bound_source_without_execution_or_installation(
    client, settings, creation_root, template
):
    row = project(client)
    task = client.post(
        "/api/tasks",
        json={
            "title": "Plan new app",
            "context": {
                "project_id": row["id"],
                "app_id": row["app_id"],
                "purpose": "development",
            },
        },
    ).json()
    assert task["context"]["app_execution_boundary"] == "planning_only"
    body = request(client, row, template)
    response = prepare(client, row, body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["state"] == "ready", result
    path = creation_root / "new-app"
    assert result["source_root"] == str(path)
    assert len(result["source_revision"]) == 40 and result["source_version"] == 1
    manifest = json.loads((path / "app.manifest.json").read_text())
    assert manifest["display"]["name"] == "신청 앱"
    assert manifest["runtime_profile"] == (
        "web-api-v1" if template == "basic" else "web-api-postgres-v1"
    )
    assert (path / "vendor/miy-app-sdk/src/index.mjs").is_file()
    assert (path / "AGENTS.md").is_file()
    assert not (path / ".venv").exists() and not (path / "node_modules").exists()
    assert subprocess.check_output(["git", "-C", str(path), "status", "--porcelain"]) == b""
    assert settings.app_execution_environments == []
    catalog = client.get("/api/workbench/catalog").json()
    app = next(item for item in catalog["items"] if item["app_id"] == "new-app")
    assert app["source_status"] == "ready" and app["execution_status"] == "unconfigured"
    assert app["deployment_status"] == "unconfigured"
    assert (
        client.get(f"/api/tasks/{task['id']}").json()["context"]["app_execution_boundary"]
        == "planning_only"
    )
    rejected = client.post(
        "/api/tasks", json={"title": "Implement", "context": {"app_id": "new-app"}}
    )
    assert rejected.status_code == 503 and rejected.json()["code"] == "app_executor_unavailable"
    assert status(client, row) == result
    # A response retry returns the prior preparation, preserving all later personal edits.
    (path / "personal.txt").write_text("Keep my later work")
    assert prepare(client, row, body).json() == result
    assert (path / "personal.txt").read_text() == "Keep my later work"
    assert not list(creation_root.glob(".miy-source-*"))


def test_explicit_root_opt_in_is_separate_from_read_binding(client, settings, creation_root):
    row = project(client)
    body = request(client, row)
    settings.app_creation_roots = []
    assert client.get("/api/workbench/source-setup/options").json()["roots"] == []
    response = prepare(client, row, body)
    assert response.status_code == 403 and response.json()["code"] == "app_setup_root_denied"
    assert status(client, row) is None
    assert list(creation_root.iterdir()) == []


@pytest.mark.parametrize(
    "value",
    [
        "https://user:secret@example.test/app.git",
        "https://example.test/app.git?token=private",
        "ssh://example.test/app.git",
    ],
)
def test_rejects_unsafe_repository_before_intent(client, creation_root, value):
    row = project(client)
    body = {**request(client, row), "repository": value}
    assert prepare(client, row, body).status_code == 422
    assert status(client, row) is None and list(creation_root.iterdir()) == []


@pytest.mark.parametrize("app_id", ["a-", "a--b"])
def test_canonical_independent_ids_round_trip_catalog_and_task_context(
    client, creation_root, app_id
):
    row = project(client, app_id)
    result = prepare(client, row, request(client, row)).json()
    assert result["state"] == "ready", result
    assert any(
        item["app_id"] == app_id for item in client.get("/api/workbench/catalog").json()["items"]
    )
    response = client.post("/api/tasks", json={"title": "App", "context": {"app_id": app_id}})
    assert response.status_code == 503, response.text


@pytest.mark.parametrize("app_id", ["a", "7-demo", "a" * 65])
def test_old_project_ids_remain_readable_but_new_preparation_rejects_them(
    client, creation_root, app_id
):
    with client.app.state.factory.begin() as db:
        row = WorkbenchProject(
            app_id=app_id,
            title="Legacy project",
            summary="Keep",
            reuse_decision="new",
            reuse_notes="Previous valid ID",
        )
        db.add(row)
        db.flush()
        identifier = row.id
    row = {"id": identifier}
    catalog = client.get("/api/workbench/catalog")
    assert catalog.status_code == 200
    assert any(item["app_id"] == app_id for item in catalog.json()["projects"])
    response = prepare(client, row, request(client, row))
    assert response.status_code == 422 and response.json()["code"] == "app_setup_invalid"
    assert status(client, row) is None


def test_same_id_and_project_require_identical_inputs(client, creation_root):
    row = project(client)
    body = request(client, row)
    assert prepare(client, row, body).json()["state"] == "ready"
    for changed in (
        {"repository": "https://example.test/other.git"},
        {"template_id": "private-notes"},
        {"operation_id": str(uuid4())},
    ):
        response = prepare(client, row, {**body, **changed})
        assert response.status_code == 409 and response.json()["code"] == "app_setup_conflict"
    other = project(client, "other-app")
    assert prepare(client, other, body).status_code == 409
    assert not (creation_root / "other-app").exists()


@pytest.mark.parametrize("kind", ["empty", "personal", "symlink"])
def test_existing_destination_is_never_replaced(client, creation_root, tmp_path, kind):
    row = project(client)
    target = creation_root / "new-app"
    outside = tmp_path / "outside"
    outside.mkdir()
    if kind == "symlink":
        target.symlink_to(outside, target_is_directory=True)
    else:
        target.mkdir()
        if kind == "personal":
            (target / "mine.txt").write_text("Keep")
    before = target.lstat()
    result = prepare(client, row, request(client, row)).json()
    assert result["state"] == "conflict"
    assert target.lstat().st_ino == before.st_ino
    assert not (target / ".git").exists()
    assert list(outside.iterdir()) == []


def test_response_loss_after_publication_recovers_same_source_and_commit(
    client, creation_root, monkeypatch
):
    row = project(client)
    body = request(client, row)
    original = setup.publish

    def lost_response(*args):
        original(*args)
        raise OSError("synthetic response loss")

    monkeypatch.setattr(setup, "publish", lost_response)
    failed = prepare(client, row, body).json()
    assert failed["state"] == "failed"
    path = creation_root / "new-app"
    inode = path.stat().st_ino
    head = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"]).decode().strip()
    with client.app.state.factory() as db:
        assert db.get(AppSourceBinding, "new-app") is None
    monkeypatch.setattr(setup, "publish", original)
    ready = prepare(client, row, body).json()
    assert ready["state"] == "ready" and ready["source_revision"] == head
    assert path.stat().st_ino == inode
    with client.app.state.factory() as db:
        assert len(db.scalars(select(AppSourceSetup)).all()) == 1


def test_failed_staging_resumes_without_overwriting_changed_files(
    client, creation_root, monkeypatch
):
    row = project(client)
    body = request(client, row)
    original = setup.initialize_git
    monkeypatch.setattr(
        setup, "initialize_git", lambda *args: (_ for _ in ()).throw(OSError("synthetic failure"))
    )
    assert prepare(client, row, body).json()["state"] == "failed"
    stage = creation_root / (".miy-source-" + body["operation_id"])
    (stage / "README.md").write_text("Personal change; keep")
    monkeypatch.setattr(setup, "initialize_git", original)
    result = prepare(client, row, body).json()
    assert (
        result["state"] == "conflict"
        and (stage / "README.md").read_text() == "Personal change; keep"
    )
    assert not (creation_root / "new-app").exists()


def test_creation_root_settings_require_an_explicit_source_root_subset(settings, creation_root):
    data = settings.model_dump()
    data["app_creation_roots"] = [creation_root.parent / "not-allowed"]
    with pytest.raises(ValueError, match="contained"):
        Settings(**data, _env_file=None)


def test_unmodified_partial_source_resumes_same_owned_directory(client, creation_root, monkeypatch):
    row = project(client)
    body = request(client, row)
    original = setup.initialize_git
    monkeypatch.setattr(
        setup, "initialize_git", lambda *args: (_ for _ in ()).throw(OSError("synthetic failure"))
    )
    assert prepare(client, row, body).json()["state"] == "failed"
    stage = creation_root / (".miy-source-" + body["operation_id"])
    inode = stage.stat().st_ino
    monkeypatch.setattr(setup, "initialize_git", original)
    assert prepare(client, row, body).json()["state"] == "ready"
    assert (creation_root / "new-app").stat().st_ino == inode


@pytest.mark.parametrize("kind", ["blob", "index", "worktree", "hook", "hardlink"])
def test_published_source_recovery_rejects_changed_objects_and_metadata(
    client, creation_root, monkeypatch, tmp_path, kind
):
    row = project(client)
    body = request(client, row)
    original = setup.publish

    def lost_response(*args):
        original(*args)
        raise OSError("synthetic response loss")

    monkeypatch.setattr(setup, "publish", lost_response)
    assert prepare(client, row, body).json()["state"] == "failed"
    path = creation_root / "new-app"
    if kind == "blob":
        blob = (
            subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD:README.md"])
            .decode()
            .strip()
        )
        changed = path / ".git/objects" / blob[:2] / blob[2:]
        content = b"Different archived source"
        changed.unlink()
        changed.write_bytes(zlib.compress(b"blob " + str(len(content)).encode() + b"\0" + content))
    elif kind == "index":
        changed = path / ".git/index"
        changed.write_bytes(b"corrupt index")
    elif kind == "hook":
        changed = path / ".git/hooks/pre-commit"
        changed.parent.mkdir()
        changed.write_text("#!/bin/sh\nexit 1\n")
    elif kind == "hardlink":
        changed = path / "README.md"
        os.link(changed, tmp_path / "other-link")
    else:
        changed = path / "README.md"
        changed.write_text("Personal changed worktree")
    previous = changed.read_bytes()
    monkeypatch.setattr(setup, "publish", original)
    result = prepare(client, row, body).json()
    assert result["state"] == "conflict" and result["failure_code"] == "app_setup_conflict"
    assert changed.read_bytes() == previous
    with client.app.state.factory() as db:
        assert db.get(AppSourceBinding, "new-app") is None


def test_atomic_publication_preserves_a_racing_empty_destination(
    client, creation_root, monkeypatch
):
    row = project(client)
    original = setup.publish
    existing = []

    def racing_destination(parent, source, destination):
        os.mkdir(destination, dir_fd=parent)
        existing.append(os.stat(destination, dir_fd=parent).st_ino)
        original(parent, source, destination)

    monkeypatch.setattr(setup, "publish", racing_destination)
    result = prepare(client, row, request(client, row)).json()
    destination = creation_root / "new-app"
    assert result["state"] == "conflict" and destination.stat().st_ino == existing[0]
    assert list(destination.iterdir()) == []


def test_project_lock_rejects_a_second_consumer_without_a_long_sqlite_write_transaction(
    client, settings, creation_root, monkeypatch
):
    row = project(client)
    original = setup.initialize_git
    observations = []

    def initialize(*args):
        # A distinct connection can write while filesystem/Git preparation is active.
        with client.app.state.factory.begin() as db:
            stored = db.get(WorkbenchProject, row["id"])
            stored.summary = "Concurrent project metadata"
        with pytest.raises(setup.ConsoleError) as error:
            with setup.ownership(settings, row["id"]):
                pytest.fail("A second operation acquired ownership")
        observations.append(error.value.code)
        return original(*args)

    monkeypatch.setattr(setup, "initialize_git", initialize)
    result = prepare(client, row, request(client, row)).json()
    assert result["state"] == "ready" and observations == ["app_setup_busy"]


def test_stale_bundle_is_rejected_before_any_durable_intent(client, creation_root):
    row = project(client)
    body = {**request(client, row), "expected_bundle_digest": "sha256:" + "0" * 64}
    response = prepare(client, row, body)
    assert response.status_code == 409 and response.json()["code"] == "app_setup_bundle_changed"
    assert status(client, row) is None and list(creation_root.iterdir()) == []


def test_git_ignores_host_config_template_hooks_and_inherited_git_environment(
    client, creation_root, monkeypatch, tmp_path
):
    row = project(client)
    marker = tmp_path / "host-hook-ran"
    template = tmp_path / "git-template"
    (template / "hooks").mkdir(parents=True)
    hook = template / "hooks/pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o700)
    config = tmp_path / "host-gitconfig"
    config.write_text(
        f"[init]\n\ttemplateDir = {template}\n[core]\n\thooksPath = {template / 'hooks'}\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(template / "hooks"))
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "host-index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "host-objects"))
    result = prepare(client, row, request(client, row)).json()
    assert result["state"] == "ready"
    assert not marker.exists() and not (tmp_path / "host-index").exists()
    assert not (tmp_path / "host-objects").exists()
    assert not (creation_root / "new-app/.git/hooks").exists()


def test_creation_root_replacement_never_writes_into_the_replacement(
    client, creation_root, monkeypatch, tmp_path
):
    row = project(client)
    body = request(client, row)
    outside = tmp_path / "outside"
    outside.mkdir()
    retained = tmp_path / "retained"
    original = setup.current_root

    def replace_root(path, descriptor):
        creation_root.rename(retained)
        creation_root.symlink_to(outside, target_is_directory=True)
        original(path, descriptor)

    monkeypatch.setattr(setup, "current_root", replace_root)
    result = prepare(client, row, body).json()
    assert result["state"] == "conflict" and list(outside.iterdir()) == []
    stage = retained / (".miy-source-" + body["operation_id"])
    assert stage.is_dir() and list(stage.iterdir()) == []


def test_schema_six_preserves_schema_five_projects_tasks_and_source_bindings(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "before.sqlite3")
    migrate(url, revision="console_sqlite_0005")
    engine, factory = database(url)
    try:
        with factory.begin() as db:
            db.add(
                WorkbenchProject(
                    id="previous-project",
                    app_id="a",
                    title="Previous",
                    summary="Keep",
                    reuse_decision="new",
                    reuse_notes="Previously valid ID",
                )
            )
            db.add(
                Task(
                    id="previous-task",
                    title="Keep task",
                    root=str(tmp_path),
                    status="completed",
                    context={
                        "app_execution_boundary": "planning_only",
                        "project_id": "previous-project",
                    },
                )
            )
            db.add(
                AppSourceBinding(
                    app_id="existing-app",
                    repository_root=str(tmp_path / "existing"),
                    manifest={"keep": "original"},
                    manifest_digest="sha256:" + "a" * 64,
                    version=7,
                )
            )
        migrate(url)
        migrate(url)
        with factory() as db:
            assert db.get(WorkbenchProject, "previous-project").app_id == "a"
            assert (
                db.get(Task, "previous-task").context["app_execution_boundary"] == "planning_only"
            )
            source = db.get(AppSourceBinding, "existing-app")
            assert source.version == 7 and source.manifest == {"keep": "original"}
            assert db.scalars(select(AppSourceSetup)).all() == []
            assert db.scalar(text("PRAGMA integrity_check")) == "ok"
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()


def test_concurrent_projects_cannot_claim_the_same_operation_id(
    client, settings, creation_root, monkeypatch
):
    rows = [project(client, "first-app"), project(client, "second-app")]
    body = SourceSetupInput(**request(client, rows[0]))
    barrier = Barrier(2, timeout=10)

    original = setup.app_starters.render

    def synchronized_read(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait()
        return result

    def run(row):
        try:
            return setup.prepare(settings, client.app.state.factory, row["id"], body)
        except setup.ConsoleError as error:
            return error

    monkeypatch.setattr(setup.app_starters, "render", synchronized_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, rows))
    success = next(value for value in results if not isinstance(value, setup.ConsoleError))
    rejected = next(value for value in results if isinstance(value, setup.ConsoleError))
    assert success.state == "ready"
    assert rejected.code == "app_setup_conflict" and rejected.status == 409
    assert [path.name for path in creation_root.iterdir()] == [success.app_id]
    with client.app.state.factory() as db:
        assert len(db.scalars(select(AppSourceSetup)).all()) == 1
        assert len(db.scalars(select(AppSourceBinding)).all()) == 1


def test_git_initial_commit_dates_are_explicit_utc_even_for_naive_storage_values(monkeypatch):
    observed = []

    def run(_argv, **kwargs):
        observed.append(kwargs["env"])
        return subprocess.CompletedProcess([], 0, stdout=b"ok")

    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.git(1, SimpleNamespace(created_at=datetime(2026, 10, 6, 12, 30)), "version")
    assert observed[0]["GIT_AUTHOR_DATE"] == "2026-10-06T12:30:00+00:00"
    assert observed[0]["GIT_COMMITTER_DATE"] == "2026-10-06T12:30:00+00:00"
