"""Real helper journals bridge to API observations; native services remain doubles."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from test_workspace_unknown_sdk_journal import fixture_module
from test_workspace_unknown_sdk_journal import sdk_journal as sdk_journal

from codex_console import workspace_environment as environment
from codex_console import workspaces
from codex_console.models import WorkbenchProject, WorkbenchWorkspace, WorkspaceOperation, database


@pytest.fixture
def api_journal(sdk_journal, database_url, monkeypatch):
    fixture, settings, snapshot, calls, requests = sdk_journal
    engine, factory = database(database_url)
    removals = []

    def no_local_removal(*args):
        removals.append("local")
        pytest.fail("Read-only observation must not remove a worktree")

    async def no_remote_removal(*args):
        removals.append("remote")
        pytest.fail("Read-only observation must not remove a remote branch")

    monkeypatch.setattr(workspaces.workspace_git, "remove", no_local_removal)
    monkeypatch.setattr(workspaces.workspace_gitlab, "remove_remote", no_remote_removal)
    try:
        yield fixture, settings, snapshot, factory, calls, requests, removals
    finally:
        engine.dispose()


def unknown_operation(api_journal, kind):
    fixture, _, snapshot, factory, *_ = api_journal
    operation_id = str(uuid4())
    receipt = {"core": {"stage": "/" + kind, "acknowledged": False}, "owned_intent": operation_id}
    with factory.begin() as db:
        project = WorkbenchProject(
            app_id=snapshot["app_id"],
            title="Disposable app",
            summary="Journal recovery",
            reuse_decision="new",
            reuse_notes="Synthetic lifecycle only",
        )
        db.add(project)
        db.flush()
        db.add(
            WorkbenchWorkspace(
                id=snapshot["id"],
                project_id=project.id,
                app_id=snapshot["app_id"],
                title="Disposable workspace",
                profile="app",
                repository_root=snapshot["repository_root"],
                repository="https://git.invalid/miy.git",
                source_directory=snapshot["app_directory"],
                worktree_root=snapshot["worktree_path"],
                common_dir=str(fixture.config["repository_root"] / ".git"),
                branch=snapshot["branch"],
                base_revision=snapshot["base_revision"],
                source_revision=snapshot["source_revision"],
                state="stopping" if kind == "stop" else "cleanup_pending",
                admission_open=False,
                preview=snapshot["preview"],
                environment={"state": "unknown"},
                integration={"state": "succeeded", "merged_revision": snapshot["source_revision"]}
                if kind == "cleanup"
                else {},
                cleanup={"state": "cleanup_pending"} if kind == "cleanup" else {},
            )
        )
        db.add(
            WorkspaceOperation(
                id=operation_id,
                workspace_id=snapshot["id"],
                kind=kind,
                source_revision=snapshot["source_revision"],
                digest="synthetic-approved-intent",
                state="unknown",
                receipt=receipt,
                failure_code="workspace_operation_unknown",
            )
        )
    return operation_id, receipt


def lose_final_journal(api_journal, monkeypatch, kind):
    fixture, *_ = api_journal
    helper = fixture_module.helper
    fixture.action("prepare")
    write = helper.write_private
    with monkeypatch.context() as fault:

        def lose_write(path, value, **kwargs):
            if path == fixture.private("journal.json") and json.loads(value)["state"] == "stopped":
                helper.refuse("workspace_operation_unknown")
            return write(path, value, **kwargs)

        native_require = fixture.native.require

        def lose_after_reload(*args):
            native_require(*args)
            if (
                args == ("daemon-reload",)
                and helper.read_json(fixture.private("journal.json"))["state"] == "cleaning"
            ):
                helper.refuse("workspace_operation_unknown")

        if kind == "stop":
            fault.setattr(helper, "write_private", lose_write)
        else:
            fault.setattr(fixture.native, "require", lose_after_reload)
        with pytest.raises(helper.Refused, match="workspace_operation_unknown"):
            fixture.action(kind)
    assert helper.read_json(fixture.private("journal.json"))["state"] == (
        "stopping" if kind == "stop" else "cleaning"
    )


def test_stop_loss_observation_completes_original_intent_and_helper_resume(
    api_journal, monkeypatch
):
    fixture, settings, snapshot, factory, calls, requests, removals = api_journal
    lose_final_journal(api_journal, monkeypatch, "stop")
    descriptor_sha = hashlib.sha256(fixture.private("descriptor.json").read_bytes()).hexdigest()
    operation_id, receipt = unknown_operation(api_journal, "stop")
    commands = fixture.native.commands.copy()
    observed = asyncio.run(workspaces.observe(settings, factory, snapshot["id"]))
    assert observed.state == "stopped" and not observed.admission_open
    assert calls == ["status"] and requests == ["/context"]
    assert fixture.native.commands == commands and not removals
    assert fixture_module.helper.read_json(fixture.private("journal.json"))["state"] == "stopped"
    with factory() as db:
        operation = db.get(WorkspaceOperation, operation_id)
        assert operation.state == "succeeded" and operation.receipt == receipt
        assert operation.source_revision == snapshot["source_revision"]
    resumed = asyncio.run(
        environment.resume(settings, workspaces.snapshot(db_row(factory, snapshot["id"])))
    )
    assert resumed["state"] == "ready" and resumed["preview"]["state"] == "unconfigured"
    assert calls == ["status", "resume"] and requests == ["/context", "/context"]
    assert fixture_module.helper.read_json(fixture.private("journal.json"))["state"] == "ready"
    assert (
        hashlib.sha256(fixture.private("descriptor.json").read_bytes()).hexdigest()
        == descriptor_sha
    )
    assert fixture.source.is_dir() and not removals


def db_row(factory, workspace_id):
    with factory() as db:
        return workspaces.detached(db.get(WorkbenchWorkspace, workspace_id))


def cleanup_context(api_journal, monkeypatch):
    _, _, snapshot, _, _, requests, _ = api_journal
    snapshot["preview"] = {"state": "stopped", "installation_id": str(uuid4())}

    async def read(cfg, selected, suffix, body=None, **kwargs):
        assert suffix == "/context" and body is None
        requests.append(suffix)
        return {"state": "cleaned", "source_handoff_complete": True}

    monkeypatch.setattr(environment, "_call", read)


def test_cleanup_loss_observation_waits_on_same_intent_without_git_removal(
    api_journal, monkeypatch
):
    fixture, settings, snapshot, factory, calls, requests, removals = api_journal
    cleanup_context(api_journal, monkeypatch)
    lose_final_journal(api_journal, monkeypatch, "cleanup")
    assert not list(fixture.config["unit_root"].iterdir())
    descriptor_sha = hashlib.sha256(fixture.private("descriptor.json").read_bytes()).hexdigest()
    operation_id, receipt = unknown_operation(api_journal, "cleanup")
    commands = fixture.native.commands.copy()
    observed = asyncio.run(workspaces.observe(settings, factory, snapshot["id"]))
    assert observed.state == "cleanup_pending" and not observed.admission_open
    selected = next(op for op in observed.operations if op.operation_id == operation_id)
    assert selected.state == "waiting" and selected.continuable
    assert calls == ["status"] and requests == ["/context"]
    assert fixture.native.commands == commands and not removals
    assert fixture_module.helper.read_json(fixture.private("journal.json"))["state"] == "cleaned"
    assert (
        hashlib.sha256(fixture.private("descriptor.json").read_bytes()).hexdigest()
        == descriptor_sha
    )
    assert fixture.source.is_dir() and Path(snapshot["worktree_path"]).is_dir()
    with factory() as db:
        operation = db.get(WorkspaceOperation, operation_id)
        row = db.get(WorkbenchWorkspace, snapshot["id"])
        assert operation.state == "waiting" and operation.receipt == receipt
        assert operation.source_revision == snapshot["source_revision"]
        assert row.cleanup == {"state": "cleanup_pending"}
        assert row.source_revision == snapshot["source_revision"]
        assert row.environment == {"state": "unknown"} and row.preview == snapshot["preview"]


@pytest.mark.parametrize(
    "kind,missing",
    [("stop", "active"), ("stop", "foreign"), ("cleanup", "partial"), ("cleanup", "foreign")],
)
def test_insufficient_stop_or_cleanup_proof_preserves_unknown_intent(
    api_journal, monkeypatch, kind, missing
):
    fixture, settings, snapshot, factory, calls, requests, removals = api_journal
    if kind == "cleanup":
        cleanup_context(api_journal, monkeypatch)
    fixture.action("prepare")
    unit = next(fixture.config["unit_root"].iterdir())
    unit_name, unit_body = unit.name, unit.read_bytes()
    # Stop/cleanup crashes after native execution, before final journal storage.
    helper = fixture_module.helper
    journal = helper.read_json(fixture.private("journal.json"))
    journal["state"] = "stopping" if kind == "stop" else "cleaning"
    helper.write_private(fixture.private("journal.json"), helper.canonical(journal))
    fixture.native.active = missing == "active"
    if kind == "cleanup":
        for path in fixture.config["unit_root"].iterdir():
            path.unlink()
        fixture.native.loaded = False
        if missing == "partial":
            (fixture.config["unit_root"] / unit_name).write_bytes(unit_body)
            fixture.native.loaded = True
    if missing == "foreign":
        fixture.native.foreign = True
        if kind == "stop":
            unit.write_bytes(unit_body + b"# foreign unit\n")
    operation_id, receipt = unknown_operation(api_journal, kind)
    original_journal = fixture.private("journal.json").read_bytes()
    commands = fixture.native.commands.copy()
    observed = asyncio.run(workspaces.observe(settings, factory, snapshot["id"]))
    selected = next(op for op in observed.operations if op.operation_id == operation_id)
    assert selected.unknown and selected.state == "unknown"
    assert not observed.admission_open
    assert calls == ["status"] and requests == ["/context"]
    assert fixture.native.commands == commands and not removals
    assert fixture.private("journal.json").read_bytes() == original_journal
    assert fixture.source.is_dir()
    with factory() as db:
        operation = db.get(WorkspaceOperation, operation_id)
        row = db.get(WorkbenchWorkspace, snapshot["id"])
        assert (
            operation.receipt == receipt
            and operation.source_revision == snapshot["source_revision"]
        )
        assert row.source_revision == snapshot["source_revision"]
        assert row.environment == {"state": "unknown"} and row.preview == snapshot["preview"]
