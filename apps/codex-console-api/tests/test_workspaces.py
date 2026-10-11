"""Disposable SQLite/Git boundary tests; no native model or remote mutation."""

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from codex_console import git, store, workspace_git, workspaces
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.models import (
    ResourceLease,
    Task,
    WorkbenchProject,
    WorkbenchWorkspace,
    WorkspaceOperation,
    database,
)
from codex_console.workspace_schemas import WorkspaceAction, WorkspaceCreate


@pytest.fixture
def managed(settings, repository, monkeypatch):
    settings.managed_workspaces_enabled = True
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "remote",
            "add",
            "origin",
            "https://git.example.invalid/team/miy.git",
        ],
        check=True,
        capture_output=True,
    )
    native_git = git.git

    def bounded_git(root, *args, **kwargs):
        if kwargs.get("transport"):
            assert args[0] == "fetch"
            assert args[2] == "origin"
            return b""
        return native_git(root, *args, **kwargs)

    monkeypatch.setattr(git, "git", bounded_git)
    calls = []

    async def prepare(cfg, snapshot):
        calls.append("prepare")
        return {"state": "ready", "preview": {"state": "unconfigured"}}

    async def stop(cfg, snapshot):
        calls.append("stop")
        return {"state": "stopped", "preview": {"state": "stopped"}}

    async def resume(cfg, snapshot):
        calls.append("resume")
        return {"state": "ready", "preview": {"state": "unconfigured"}}

    async def refresh(cfg, snapshot, operation_id, revision):
        calls.append("refresh")
        return {
            "state": "failed",
            "preview": {"state": "failed", "failure_code": "app_build_failed"},
        }

    def environment_for(cfg, snapshot):
        return AppExecutionEnvironment(
            key="test-" + snapshot["id"][:8],
            source_root=Path(snapshot["worktree_path"]) / snapshot["app_directory"],
            exec_server_url="ws://127.0.0.1:19999",
            auth_bearer_token="synthetic-owned-executor-token-only",
        )

    from codex_console import workspace_environment

    for name, function in {
        "prepare": prepare,
        "stop": stop,
        "resume": resume,
        "refresh": refresh,
        "environment_for": environment_for,
    }.items():
        monkeypatch.setattr(workspace_environment, name, function)
    engine, factory = database(settings.database_url)
    with factory.begin() as db:
        project = WorkbenchProject(
            app_id="equipment-test",
            title="Equipment",
            summary="Disposable fixture",
            reuse_decision="new",
            reuse_notes="Native boundary fixture",
        )
        db.add(project)
        db.flush()
        project_id = project.id
    yield settings, factory, project_id, calls
    engine.dispose()


def create(managed):
    settings, factory, project_id, _ = managed
    body = WorkspaceCreate(operation_id=uuid4())
    return asyncio.run(workspaces.create(settings, factory, project_id, body)), body


def test_new_intent_supersedes_only_stale_waiting_and_retains_remote_receipt(managed):
    current, _ = create(managed)
    _, factory, _, _ = managed
    previous_id = str(uuid4())
    receipt = {"state": "reviewing", "mr_id": 7, "source_revision": "b" * 40}
    with factory.begin() as db:
        db.add(
            WorkspaceOperation(
                id=previous_id,
                workspace_id=current.id,
                kind="integrate",
                state="waiting",
                digest="old-intent",
                source_revision="b" * 40,
                receipt=receipt,
            )
        )
    new_action = WorkspaceAction(operation_id=uuid4(), expected_version=current.version)
    _, operation_id, claimed = workspaces.reserve(factory, current.id, "refresh", new_action)
    assert claimed and operation_id != previous_id
    with factory() as db:
        previous = db.get(WorkspaceOperation, previous_id)
        assert previous.state == "blocked"
        assert previous.failure_code == "workspace_source_changed"
        assert previous.receipt == receipt
        assert db.get(WorkspaceOperation, operation_id).state == "running"


def test_unknown_work_prevents_superseding_a_stale_waiting_operation(managed):
    current, _ = create(managed)
    _, factory, _, _ = managed
    waiting_id, unknown_id = str(uuid4()), str(uuid4())
    with factory.begin() as db:
        for identity, state in ((waiting_id, "waiting"), (unknown_id, "unknown")):
            db.add(
                WorkspaceOperation(
                    id=identity,
                    workspace_id=current.id,
                    kind="integrate",
                    state=state,
                    digest=identity,
                    source_revision="b" * 40,
                )
            )
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        workspaces.reserve(
            factory,
            current.id,
            "refresh",
            WorkspaceAction(
                operation_id=uuid4(),
                expected_version=current.version,
            ),
        )
    with factory() as db:
        assert db.get(WorkspaceOperation, waiting_id).state == "waiting"
        assert db.get(WorkspaceOperation, unknown_id).state == "unknown"


def test_native_transport_reuses_owned_operator_credentials_only_for_transport(
    repository, tmp_path, monkeypatch
):
    home = tmp_path / "operator-home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[credential]\nhelper = synthetic-native-helper\n[core]\nhooksPath = /unsafe-hook\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/untrusted/environment-selected-config")
    assert (
        git.git(repository, "config", "--get", "credential.helper", transport=True)
        == b"synthetic-native-helper\n"
    )
    assert (
        git.git(repository, "config", "--get", "core.hooksPath", transport=True) == b"/dev/null\n"
    )
    with pytest.raises(ConsoleError, match="git_unavailable"):
        git.git(repository, "config", "--get", "credential.helper")


def test_native_transport_refuses_writable_operator_global_config(
    repository, tmp_path, monkeypatch
):
    home = tmp_path / "operator-home"
    home.mkdir()
    config = home / ".gitconfig"
    config.write_text("[credential]\nhelper = synthetic-native-helper\n")
    config.chmod(0o666)
    monkeypatch.setenv("HOME", str(home))
    with pytest.raises(ConsoleError, match="workspace_repository_denied"):
        git.git(repository, "config", "--get", "credential.helper", transport=True)
    assert git.repository_root(repository) == repository


def test_failed_before_worktree_can_resume_same_workspace_without_replaying_creation(
    managed, monkeypatch
):
    settings, factory, project_id, calls = managed
    native_git = git.git

    def unavailable_fetch(root, *args, **kwargs):
        if kwargs.get("transport"):
            raise ConsoleError("git_unavailable")
        return native_git(root, *args, **kwargs)

    monkeypatch.setattr(git, "git", unavailable_fetch)
    failed, original_body = create(managed)
    assert failed.state == "error" and not failed.admission_open
    assert failed.source_revision is None and failed.base_revision is None
    assert calls == []
    with factory() as db:
        saved = db.get(WorkbenchWorkspace, failed.id)
        branch = saved.branch
        assert not Path(saved.worktree_root).exists()
        assert db.get(WorkspaceOperation, str(original_body.operation_id)).state == "failed"
    monkeypatch.setattr(git, "git", native_git)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    body = WorkspaceAction(operation_id=uuid4(), expected_version=failed.version)
    resumed = asyncio.run(workspaces.action(app, failed.id, "resume", body))
    assert resumed.id == failed.id and resumed.project_id == project_id
    assert resumed.branch == branch and resumed.state == "ready" and resumed.admission_open
    assert resumed.base_revision and resumed.source_revision and calls == ["prepare"]
    with factory() as db:
        assert db.get(WorkspaceOperation, str(original_body.operation_id)).state == "failed"
        assert db.get(WorkspaceOperation, str(body.operation_id)).state == "succeeded"
    same = asyncio.run(workspaces.action(app, failed.id, "resume", body))
    assert same.id == failed.id and calls == ["prepare"]


def test_unmaterialized_workspace_resume_does_not_adopt_existing_branch(managed, monkeypatch):
    settings, factory, _, calls = managed
    native_git = git.git

    def unavailable_fetch(root, *args, **kwargs):
        if kwargs.get("transport"):
            raise ConsoleError("git_unavailable")
        return native_git(root, *args, **kwargs)

    monkeypatch.setattr(git, "git", unavailable_fetch)
    failed, _ = create(managed)
    monkeypatch.setattr(git, "git", native_git)
    native_git(settings.workspace, "branch", failed.branch, "HEAD")
    before = native_git(settings.workspace, "rev-parse", "refs/heads/" + failed.branch)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    result = asyncio.run(
        workspaces.action(
            app,
            failed.id,
            "resume",
            WorkspaceAction(operation_id=uuid4(), expected_version=failed.version),
        )
    )
    assert result.state == "error" and not result.admission_open
    assert result.failure_code == "workspace_source_collision" and calls == []
    assert native_git(settings.workspace, "rev-parse", "refs/heads/" + failed.branch) == before
    with factory() as db:
        assert not Path(db.get(WorkbenchWorkspace, failed.id).worktree_root).exists()


def test_workspace_is_durable_and_creates_named_scoped_checkpoint(managed, repository):
    row, body = create(managed)
    settings, factory, project_id, calls = managed
    assert row.state == "ready" and row.admission_open
    assert row.preview.state == "unconfigured"
    with factory() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        root, app, metadata = workspace_git.validate(settings, saved)
        assert app == root / "personal-apps/equipment-test"
        assert metadata.parent == repository / ".git/worktrees"
        manifest = json.loads((app / "app.manifest.json").read_text())
        assert manifest["source"]["directory"] == "personal-apps/equipment-test"
        assert git.git(root, "cat-file", "blob", "HEAD:hello.txt") == b"hello\n"
        assert git.git(repository, "cat-file", "blob", "HEAD:hello.txt") == b"hello\n"
    same = asyncio.run(workspaces.create(settings, factory, project_id, body))
    assert same.id == row.id and calls == ["prepare"]


def test_native_worktree_config_supports_managed_checkpoint_and_cleanup_without_rewriting_config(
    managed, repository
):
    def native(*args):
        return subprocess.run(
            ["git", "-C", str(repository), *args], check=True, capture_output=True
        )

    native("config", "extensions.worktreeConfig", "true")
    native("config", "--worktree", "user.name", "Scoped operator")
    shared_config = (repository / ".git/config").read_bytes()
    root_config = (repository / ".git/config.worktree").read_bytes()
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        saved = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    root, app, metadata = workspace_git.validate(settings, saved)
    subprocess.run(
        ["git", "-C", str(root), "config", "--worktree", "user.name", "Scoped task"],
        check=True,
        capture_output=True,
    )
    linked_config = (metadata / "config.worktree").read_bytes()
    (app / "business.py").write_text("# Disposable app change\n")
    result = workspace_git.checkpoint(settings, saved)
    assert result["created"]
    saved.source_revision = result["source_revision"]
    assert (metadata / "config.worktree").read_bytes() == linked_config
    workspace_git.remove(settings, saved)
    assert not root.exists()
    assert (repository / ".git/config").read_bytes() == shared_config
    assert (repository / ".git/config.worktree").read_bytes() == root_config
    assert workspace_git.repository(settings) == repository


@pytest.mark.parametrize("scope", ["shared", "root", "linked"])
@pytest.mark.parametrize("key", ["include.path", "core.worktree"])
def test_managed_worktree_config_still_refuses_include_and_root_redirection(
    managed, repository, tmp_path, scope, key
):
    subprocess.run(
        ["git", "-C", str(repository), "config", "extensions.worktreeConfig", "true"],
        check=True,
        capture_output=True,
    )
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        saved = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config").write_text("[user]\nname = External\n")
    metadata = Path(saved.git_dir) if scope == "linked" else repository / ".git"
    config = metadata / ("config" if scope == "shared" else "config.worktree")
    subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(config),
            key,
            str(outside / "config" if key == "include.path" else outside),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(ConsoleError, match="workspace_(repository_denied|source_changed)"):
        workspace_git.validate(settings, saved)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "writable", "conversion_helper"])
def test_managed_worktree_config_rejects_unsafe_metadata_and_conversion_helpers(
    managed, repository, tmp_path, kind
):
    subprocess.run(
        ["git", "-C", str(repository), "config", "extensions.worktreeConfig", "true"],
        check=True,
        capture_output=True,
    )
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        saved = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    config = Path(saved.git_dir) / "config.worktree"
    outside = tmp_path / "outside-config"
    outside.write_text("[user]\nname = External\n")
    if kind == "symlink":
        config.symlink_to(outside)
    elif kind == "hardlink":
        config.hardlink_to(outside)
    elif kind == "writable":
        config.write_text(outside.read_text())
        config.chmod(0o666)
    else:
        config.write_text('[filter "untrusted"]\nclean = false\n')
    with pytest.raises(ConsoleError, match="workspace_repository_denied|app_source_git_policy"):
        workspace_git.validate(settings, saved)


def test_subtree_checkpoint_preserves_platform_tree_and_rejects_external_edit(managed):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        saved = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    root, app, _ = workspace_git.validate(settings, saved)
    (app / "business.py").write_text("# fixture app only\n")
    result = workspace_git.checkpoint(settings, saved)
    assert result["created"]
    assert git.git(root, "cat-file", "blob", result["source_revision"] + ":hello.txt") == b"hello\n"
    saved.source_revision = result["source_revision"]
    (root / "hello.txt").write_text("outside edit\n")
    with pytest.raises(ConsoleError):
        workspace_git.checkpoint(settings, saved)


def test_workspace_admission_and_task_owned_leases_are_atomic(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    with factory.begin() as db:
        tasks = [
            Task(
                title="Plan",
                root="/disposable",
                workspace_id=row.id,
                context={"workspace_id": row.id},
            )
            for _ in range(2)
        ]
        db.add_all(tasks)
        db.flush()
        ids = [task.id for task in tasks]
        for task in tasks:
            store.lease(db, task.id, workspace="ignored-path", stage="plan")
        assert {lease.resource for lease in db.scalars(select(ResourceLease))} == {
            "workspace:" + row.id
        }
        with pytest.raises(ConsoleError, match="workspace_busy"):
            store.lease(db, ids[0], workspace="different-path", stage="implement")
        db.get(WorkbenchWorkspace, row.id).admission_open = False
        with pytest.raises(ConsoleError, match="workspace_stopped"):
            store.lease(db, ids[0], workspace="different-path", stage="plan")


def test_stop_keeps_code_and_same_operation_never_replays(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    app = SimpleNamespace(
        state=SimpleNamespace(settings=settings, factory=factory, runtime=SimpleNamespace())
    )
    body = WorkspaceAction(operation_id=uuid4(), expected_version=row.version)
    stopped = asyncio.run(workspaces.action(app, row.id, "stop", body))
    assert stopped.state == "stopped" and not stopped.admission_open
    with factory() as db:
        assert Path(db.get(WorkbenchWorkspace, row.id).worktree_root).is_dir()
    same = asyncio.run(workspaces.action(app, row.id, "stop", body))
    assert same.state == "stopped" and calls == ["prepare", "stop"]


def test_stop_closes_admission_before_native_interrupt_ack(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    with factory.begin() as db:
        task = Task(
            title="Running",
            root="/disposable",
            status="running",
            workspace_id=row.id,
            context={"workspace_id": row.id},
        )
        db.add(task)
        db.flush()

    class NativeOwner:
        def for_task(self, task_id):
            return self

        async def refresh_agents(self, task_id):
            pass

        async def interrupt(self, task_id):
            with factory() as db:
                assert not db.get(WorkbenchWorkspace, row.id).admission_open
            # An acknowledged interruption is deliberately still in progress.

    app = SimpleNamespace(
        state=SimpleNamespace(settings=settings, factory=factory, runtime=NativeOwner())
    )
    stopped = asyncio.run(
        workspaces.action(
            app, row.id, "stop", WorkspaceAction(operation_id=uuid4(), expected_version=row.version)
        )
    )
    assert stopped.state == "stopping" and not stopped.admission_open
    assert stopped.failure_code == "workspace_busy"
    assert calls == ["prepare"]


def test_workspace_operation_survives_task_removal_and_unknown_blocks_new_action(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    operation_id = str(uuid4())
    with factory.begin() as db:
        task = Task(title="Temporary session", root="/disposable", workspace_id=row.id)
        db.add(task)
        db.flush()
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="refresh",
                digest="a" * 64,
                state="unknown",
            )
        )
        db.flush()
        db.execute(delete(Task).where(Task.id == task.id))
    with factory() as db:
        assert db.get(WorkspaceOperation, operation_id) is not None
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        workspaces.reserve(
            factory,
            row.id,
            "refresh",
            WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
        )


def test_turn_completion_refresh_is_once_and_known_build_failure_allows_source_repair(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    with factory.begin() as db:
        task = Task(title="Completed", root="/disposable", workspace_id=row.id, status="idle")
        db.add(task)
        db.flush()
        workspaces.queue_refresh(db, task, "native-turn-1")
        workspaces.queue_refresh(db, task, "native-turn-1")
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    asyncio.run(workspaces.finish_refresh(settings, factory, row.id))
    repaired = workspaces.read(factory, row.id)
    assert repaired.state == "ready" and repaired.admission_open
    assert repaired.preview.state == "failed"
    assert calls == ["prepare", "refresh"]


def test_managed_context_cannot_select_another_app_or_delivery_installation(managed):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        with pytest.raises(ConsoleError, match="invalid_input"):
            workspaces.context(settings, db, {"workspace_id": row.id, "app_id": "other-app"})
        with pytest.raises(ConsoleError, match="workspace_task_denied"):
            workspaces.context(
                settings, db, {"workspace_id": row.id, "installation_id": str(uuid4())}
            )


def test_waiting_stop_continues_same_intent_only_after_native_idle(managed):
    row, _ = create(managed)
    settings, factory, _, calls = managed
    operation_id = str(uuid4())
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.state, saved.admission_open = "stopping", False
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="stop",
                digest="f" * 64,
                state="waiting",
                source_revision=saved.source_revision,
            )
        )
        task = Task(
            title="Native still running", root="/disposable", workspace_id=row.id, status="running"
        )
        db.add(task)
        db.flush()
        task_id = task.id
    before = workspaces.read(factory, row.id)
    assert not before.operations[0].continuable
    body = WorkspaceAction(operation_id=operation_id, expected_version=before.version)
    with pytest.raises(ConsoleError, match="workspace_busy"):
        workspaces.reserve(factory, row.id, "stop", body)
    with factory.begin() as db:
        db.get(Task, task_id).status = "idle"
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=settings,
            factory=factory,
            runtime=SimpleNamespace(
                for_task=lambda _: SimpleNamespace(refresh_agents=_native_idle)
            ),
        )
    )
    after = asyncio.run(workspaces.action(app, row.id, "stop", body))
    assert after.state == "stopped" and after.operations[0].operation_id == operation_id
    assert calls == ["prepare", "stop"]


async def _native_idle(*args):
    pass


def test_source_change_refuses_same_waiting_integration_intent(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    operation_id = str(uuid4())
    with factory.begin() as db:
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=row.id,
                kind="integrate",
                digest="f" * 64,
                state="waiting",
                source_revision="f" * 40,
            )
        )
    with pytest.raises(ConsoleError, match="workspace_busy"):
        workspaces.reserve(
            factory,
            row.id,
            "integrate",
            WorkspaceAction(operation_id=operation_id, expected_version=row.version),
        )


def test_restart_marks_orphan_running_workspace_operation_unknown(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    with factory.begin() as db:
        db.add(
            WorkspaceOperation(
                id=str(uuid4()),
                workspace_id=row.id,
                kind="refresh",
                digest="f" * 64,
                state="running",
                source_revision=row.source_revision,
            )
        )
    workspaces.recover_startup(factory)
    result = workspaces.read(factory, row.id)
    assert not result.admission_open and result.operations[0].unknown


def test_owned_worktree_removal_is_idempotent(managed):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        item = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    workspace_git.remove(settings, item)
    workspace_git.remove(settings, item)
    assert not Path(item.worktree_root).exists()


def test_managed_registration_task_observes_committed_app_and_hides_private_resources(managed):
    from codex_console import app_sources, registration_source

    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.environment = {"private_credential_reference": "not-public"}
        value = workspaces.context(
            settings, db, {"workspace_id": row.id, "purpose": "registration"}
        )
        assert "resources" not in value["source_binding"]["managed_workspace"]
        assert "preview" not in value["source_binding"]["managed_workspace"]
        task = Task(
            title="Registration",
            root=value["source_binding"]["executor_root"],
            workspace_id=row.id,
            context=value,
        )
        db.add(task)
        db.flush()
        task_id = task.id
        app_sources.require_task_source(settings, task)
    draft = registration_source.snapshot(settings, factory, task_id)
    assert draft.app_id == row.app_id
    assert draft.source_revision == row.source_revision
    assert draft.definition["source"]["directory"] == "personal-apps/equipment-test"


def test_unknown_refresh_blocks_admission_until_exact_read_only_evidence(managed, monkeypatch):
    from codex_console import workspace_environment

    row, _ = create(managed)
    settings, factory, _, _ = managed

    async def unavailable(*args):
        raise ConsoleError("workspace_operation_unknown", 409)

    monkeypatch.setattr(workspace_environment, "refresh", unavailable)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory, runtime=None))
    result = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "refresh",
            WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
        )
    )
    assert not result.admission_open and result.operations[0].unknown
    calls = []

    async def observe(cfg, snapshot, operation_id, kind, revision):
        calls.append((operation_id, kind))
        return {"state": "ready", "preview": {"state": "ready", "runtime_revision": revision}}

    monkeypatch.setattr(workspace_environment, "observe", observe)
    observed = asyncio.run(workspaces.observe(settings, factory, row.id))
    assert observed.admission_open and observed.operations[0].state == "succeeded"
    assert calls == [(result.operations[0].operation_id, "refresh")]


def test_queued_refresh_survives_restart_as_explicit_continuation(managed):
    row, _ = create(managed)
    _, factory, _, _ = managed
    with factory.begin() as db:
        task = Task(title="Completed", root="/disposable", workspace_id=row.id, status="idle")
        db.add(task)
        db.flush()
        workspaces.queue_refresh(db, task, "native-completed-turn")
    workspaces.recover_startup(factory)
    result = workspaces.read(factory, row.id)
    assert not result.admission_open
    assert result.operations[0].state == "waiting" and result.operations[0].continuable


def test_partial_cleanup_preserves_a_different_branch_head(managed):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory() as db:
        item = workspaces.detached(db.get(WorkbenchWorkspace, row.id))
    workspace_git.remove(settings, item)
    original = Path(item.repository_root)
    different = workspace_git.revision(original)
    assert different != item.source_revision
    git.git(original, "update-ref", "refs/heads/" + item.branch, different)
    with pytest.raises(ConsoleError, match="workspace_remote_branch_changed"):
        workspace_git.remove(settings, item)
    assert git.git(original, "rev-parse", "refs/heads/" + item.branch).decode().strip() == different


def test_integrate_confirmed_dev_delivery_cleans_owned_worktree_in_same_intent(
    managed, monkeypatch
):
    from codex_console import workspace_environment, workspace_gitlab

    row, _ = create(managed)
    settings, factory, _, _ = managed
    calls = []

    async def merged(cfg, item, operation, receipt):
        result = {
            "state": "merged",
            "source_revision": item.source_revision,
            "merged_revision": "d" * 40,
            "mr_id": 1,
            "mr_url": "https://git.invalid/mr/1",
        }
        receipt(result, "running")
        calls.append("merge")
        return result

    async def delivered(cfg, snapshot, operation_id, revision):
        calls.append("dev_delivery")
        return {"state": "ready", "dev_runtime_revision": revision}

    async def cleaned(cfg, snapshot):
        calls.append("core_cleanup")
        return {"state": "cleaned", "source_handoff_complete": True}

    async def delete_ref(cfg, item, record=None):
        assert item.integration["state"] == "succeeded"
        calls.append("owned_remote_delete")

    monkeypatch.setattr(workspace_gitlab, "integrate", merged)
    monkeypatch.setattr(workspace_environment, "integrate", delivered)
    monkeypatch.setattr(workspace_environment, "cleanup", cleaned)
    monkeypatch.setattr(workspace_gitlab, "remove_remote", delete_ref)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory, runtime=None))
    operation_id = uuid4()
    result = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "integrate",
            WorkspaceAction(operation_id=operation_id, expected_version=row.version),
        )
    )
    assert (
        result.integration.state == "succeeded"
        and result.integration.dev_runtime_revision == "d" * 40
    )
    assert result.state == "cleaned" and result.cleanup.state == "cleaned"
    assert result.operations[0].operation_id == str(operation_id)
    assert calls == ["merge", "dev_delivery", "core_cleanup", "owned_remote_delete"]
    with factory() as db:
        assert not Path(db.get(WorkbenchWorkspace, row.id).worktree_root).exists()


def test_core_handoff_proof_is_required_before_any_git_cleanup(managed, monkeypatch):
    from codex_console import workspace_environment, workspace_gitlab

    row, _ = create(managed)
    settings, factory, _, _ = managed
    with factory.begin() as db:
        saved = db.get(WorkbenchWorkspace, row.id)
        saved.integration = {
            "state": "succeeded",
            "mr_id": 1,
            "source_revision": saved.source_revision,
            "merged_revision": "d" * 40,
        }

    async def no_proof(*args):
        return {"state": "cleaned", "source_handoff_complete": False}

    async def forbidden(*args):
        pytest.fail("No Git deletion without persistent Core source handoff proof")

    monkeypatch.setattr(workspace_environment, "cleanup", no_proof)
    monkeypatch.setattr(workspace_gitlab, "remove_remote", forbidden)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory, runtime=None))
    result = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "cleanup",
            WorkspaceAction(operation_id=uuid4(), expected_version=row.version),
        )
    )
    assert result.state == "cleanup_pending" and not result.admission_open
    assert result.failure_code == "workspace_source_handoff_required"
    with factory() as db:
        assert Path(db.get(WorkbenchWorkspace, row.id).worktree_root).exists()
