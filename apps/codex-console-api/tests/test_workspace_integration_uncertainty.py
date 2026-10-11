"""Exact Core request doubles and disposable storage; no remote/SDK execution."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_workspaces import create
from test_workspaces import managed as managed

from codex_console import workspace_environment, workspace_git, workspace_gitlab, workspaces
from codex_console.config import DeliveryGrant
from codex_console.errors import ConsoleError
from codex_console.models import WorkbenchWorkspace, WorkspaceOperation
from codex_console.workspace_schemas import WorkspaceAction

MERGED = "d" * 40


@pytest.mark.parametrize("uncertain_stage", ["build", "deploy"])
def test_unknown_dev_delivery_holds_new_intents_and_recovers_only_exact_existing_request(
    managed, monkeypatch, uncertain_stage
):
    row, _ = create(managed)
    settings, factory, _, _ = managed
    installation_id, release_id = str(uuid4()), str(uuid4())
    settings.miy_api_origin = "https://core.invalid"
    settings.app_delivery_grants = [
        DeliveryGrant(
            app_id=row.app_id,
            installation_id=installation_id,
            token="synthetic-private-delegation-only",
        )
    ]
    operation_id = str(uuid4())
    snapshot = {"id": row.id}
    build_id = workspace_environment._id(snapshot, operation_id, "dev-build")
    deployment_id = workspace_environment._id(snapshot, operation_id, "dev-deploy")
    prefix = "/workspaces/" + row.id
    build, deployed, calls, cleanup_calls = None, None, [], []
    integrated, handoff = False, False

    def assert_delivery_remains_in_flight():
        with factory() as db:
            current = db.get(WorkbenchWorkspace, row.id)
            assert db.get(WorkspaceOperation, operation_id).state == "running"
            version = current.version
        with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
            workspaces.reserve(
                factory,
                row.id,
                "integrate",
                WorkspaceAction(operation_id=uuid4(), expected_version=version),
            )

    def core_context():
        return {
            "id": row.id,
            "app_id": row.app_id,
            "profile_id": "app",
            "state": "ready",
            "source_revision": row.source_revision,
            "integration_revision": MERGED if integrated else None,
            "source_handoff_complete": handoff,
            "version": 1,
            "definition_digest": "sha256:" + "c" * 64,
            "permanent_portal_url": "https://core.invalid/apps/equipment-test/installed/stable",
        }

    async def request(cfg, grant, suffix, *, body=None, allow_missing=False):
        nonlocal build, deployed, integrated, handoff
        calls.append((suffix, body))
        if suffix == prefix + "/context":
            return core_context()
        if suffix == "/context":
            return {
                **core_context(),
                "installation": {"id": installation_id, "generation": 1, "release_id": None},
            }
        if suffix == prefix + "/integrate":
            assert body["source_revision"] == MERGED
            integrated = True
            return core_context()
        if suffix == "/builds/" + build_id:
            assert body is None and (allow_missing or build is not None)
            return build
        if suffix == "/builds":
            assert_delivery_remains_in_flight()
            assert body["request_id"] == build_id and body["source_revision"] == MERGED
            assert build is None, "The same build may not be submitted twice"
            build = {
                "id": build_id,
                "state": "unknown" if uncertain_stage == "build" else "succeeded",
                "source_revision": MERGED,
                "release_id": release_id,
            }
            return {**build, "state": "queued"}
        if suffix == "/deployments/" + deployment_id:
            assert body is None and (allow_missing or deployed is not None)
            return deployed
        if suffix == "/deployments":
            assert_delivery_remains_in_flight()
            assert body["request_id"] == deployment_id and body["release_id"] == release_id
            assert deployed is None, "The same deployment may not be submitted twice"
            deployed = {
                "request_id": deployment_id,
                "state": "unknown" if uncertain_stage == "deploy" else "succeeded",
            }
            return {**deployed, "state": "queued"}
        if suffix == prefix + "/complete":
            assert body == {"deployment_id": deployment_id}
            assert deployed["state"] == "succeeded"
            handoff = True
            return core_context()
        raise AssertionError("Unexpected Core request")

    async def merged(cfg, item, operation, persist):
        assert operation.id == operation_id
        result = {
            **(operation.receipt or {}),
            "mr_id": 2,
            "mr_url": "https://git.invalid/team/miy/-/merge_requests/2",
            "source_revision": row.source_revision,
            "target_revision": "e" * 40,
            "merge_attempted": True,
        }
        return await workspace_gitlab.merged_result(item, result, MERGED, persist)

    def assert_unknown_merge_receipt_keeps_active_executor():
        assert_delivery_remains_in_flight()
        with factory() as db:
            receipt = db.get(WorkspaceOperation, operation_id).receipt
            assert receipt["state"] == "unknown" and receipt["merged_revision"] == MERGED
        before = len(calls)
        observed = asyncio.run(workspaces.observe(settings, factory, row.id))
        assert next(op for op in observed.operations if op.operation_id == operation_id).state == (
            "running"
        )
        assert len(calls) == before

    native_git = workspace_git.git.git

    def native_fetch(root, *args, **kwargs):
        if kwargs.get("transport"):
            assert args == (
                "fetch",
                "--no-tags",
                "origin",
                "refs/heads/dev:refs/remotes/origin/dev",
            )
            assert_unknown_merge_receipt_keeps_active_executor()
            return b""
        return native_git(root, *args, **kwargs)

    def tree_proof(item, saved, revision):
        assert revision == MERGED and saved["target_revision"] == "e" * 40
        assert_unknown_merge_receipt_keeps_active_executor()
        return "f" * 40

    async def owned_cleanup(app, item, identity):
        assert identity == operation_id and handoff
        assert item.integration["dev_runtime_revision"] == MERGED
        cleanup_calls.append(identity)

    monkeypatch.setattr(workspace_gitlab, "integrate", merged)
    monkeypatch.setattr(workspace_git.git, "git", native_fetch)
    monkeypatch.setattr(workspace_git, "reviewed_merge_tree", tree_proof)
    monkeypatch.setattr(workspace_environment.delivery_tools, "api_request", request)
    monkeypatch.setattr(workspaces, "cleanup", owned_cleanup)
    app = SimpleNamespace(state=SimpleNamespace(settings=settings, factory=factory))
    initial = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "integrate",
            WorkspaceAction(operation_id=operation_id, expected_version=row.version),
        )
    )
    operation = next(op for op in initial.operations if op.operation_id == operation_id)
    assert operation.state == "unknown" and operation.unknown and not operation.retryable
    assert initial.integration.state == "merged" and not initial.admission_open
    assert initial.integration.merged_revision == MERGED
    assert initial.integration.dev_runtime_revision is None and not cleanup_calls
    with factory() as db:
        receipt = db.get(WorkspaceOperation, operation_id).receipt
        assert receipt["core"]["request_id"] == (
            build_id if uncertain_stage == "build" else deployment_id
        )
        assert receipt["core"]["permanent"] is True and receipt["core"]["acknowledged"] is True

    for kind in ("integrate", "refresh"):
        before = len(calls)
        with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
            asyncio.run(
                workspaces.action(
                    app,
                    row.id,
                    kind,
                    WorkspaceAction(operation_id=uuid4(), expected_version=initial.version),
                )
            )
        assert len(calls) == before

    before = len(calls)
    still_unknown = asyncio.run(workspaces.observe(settings, factory, row.id))
    assert next(op for op in still_unknown.operations if op.operation_id == operation_id).unknown
    assert all(body is None for _, body in calls[before:])
    assert not cleanup_calls
    if uncertain_stage == "build":
        build["state"] = "succeeded"
    else:
        deployed["state"] = "succeeded"
    before = len(calls)
    known = asyncio.run(workspaces.observe(settings, factory, row.id))
    operation = next(op for op in known.operations if op.operation_id == operation_id)
    assert operation.state == "waiting" and operation.continuable and not operation.unknown
    assert not known.admission_open and known.integration.state == "merged"
    assert all(body is None for _, body in calls[before:])
    exact_requests = [
        suffix for suffix, _ in calls[before:] if "/builds/" in suffix or "/deployments/" in suffix
    ]
    assert exact_requests and all(
        suffix in {"/builds/" + build_id, "/deployments/" + deployment_id}
        for suffix in exact_requests
    )

    completed = asyncio.run(
        workspaces.action(
            app,
            row.id,
            "integrate",
            WorkspaceAction(operation_id=operation_id, expected_version=known.version),
        )
    )
    assert completed.integration.state == "succeeded"
    assert completed.integration.dev_runtime_revision == MERGED and handoff
    assert cleanup_calls == [operation_id]
    assert sum(suffix == "/builds" for suffix, _ in calls) == 1
    assert sum(suffix == "/deployments" for suffix, _ in calls) == 1
    assert (
        next(op for op in completed.operations if op.operation_id == operation_id).state
        == "succeeded"
    )
