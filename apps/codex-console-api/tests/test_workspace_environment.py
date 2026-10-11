"""Native adapter doubles prove policy/response-loss handling, not live SDK health."""

import asyncio
import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from codex_console import workspace_environment as environment
from codex_console.errors import ConsoleError


@pytest.fixture
def snapshot():
    return {
        "id": str(uuid4()),
        "app_id": "equipment-test",
        "profile_id": "app",
        "source_revision": "a" * 40,
        "worktree_path": "/disposable/managed/app",
        "app_directory": "personal-apps/equipment-test",
        "preview": {
            "state": "ready",
            "portal_url": "https://portal.invalid/installed/old",
            "installation_id": str(uuid4()),
            "runtime_revision": "b" * 40,
        },
    }


@pytest.fixture
def configured():
    return SimpleNamespace(
        miy_api_origin="https://core.invalid",
        app_delivery_grants=[
            SimpleNamespace(app_id="equipment-test"),
        ],
    )


def context(snapshot):
    return {
        "id": snapshot["id"],
        "app_id": snapshot["app_id"],
        "state": "ready",
        "profile_id": "app",
        "source_revision": snapshot["source_revision"],
        "version": 1,
        "definition_digest": "c" * 64,
        "portal_url": snapshot["preview"]["portal_url"],
        "installation": {"id": snapshot["preview"]["installation_id"], "generation": 1},
    }


@pytest.mark.parametrize(
    "response,code,status",
    [
        ({"state": "error", "failure_code": "workspace_busy"}, "workspace_busy", 409),
        ({"state": "unknown"}, "workspace_operation_unknown", 409),
        (
            {"state": "error", "failure_code": "workspace_operation_unknown"},
            "workspace_operation_unknown",
            409,
        ),
        (
            {"state": "unknown", "failure_code": "workspace_busy"},
            "workspace_operation_unknown",
            409,
        ),
        (
            {"state": "error", "failure_code": "source_binding_changed"},
            "workspace_environment_unavailable",
            503,
        ),
        (["workspace_busy"], "workspace_environment_unavailable", 503),
        (b"not-json", "workspace_environment_unavailable", 503),
    ],
    ids=[
        "busy",
        "unknown-state",
        "unknown-code",
        "unknown-priority",
        "hard-failure",
        "list",
        "invalid-json",
    ],
)
def test_native_helper_nonzero_preserves_busy_and_existing_failure_boundaries(
    snapshot, monkeypatch, response, code, status
):
    command = ["/operator/python", "/operator/managed.py", "--config", "/operator/managed.json"]
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        body = response if isinstance(response, bytes) else json.dumps(response).encode()
        return subprocess.CompletedProcess(args, 1, stdout=body)

    monkeypatch.setattr(environment.subprocess, "run", execute)
    with pytest.raises(ConsoleError) as failure:
        environment.environment_for(SimpleNamespace(managed_environment_command=command), snapshot)
    assert failure.value.code == code and failure.value.status == status
    assert len(calls) == 1
    args, options = calls[0]
    assert args == [*command, "describe"]
    assert options["timeout"] == 10 and options["stderr"] == subprocess.DEVNULL
    assert json.loads(options["input"]) == environment._public(snapshot)


def test_native_helper_timeout_remains_unknown_without_retry(snapshot, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(environment.subprocess, "run", execute)
    settings = SimpleNamespace(
        managed_environment_command=["/operator/python", "/operator/managed.py"]
    )
    with pytest.raises(ConsoleError) as failure:
        environment.environment_for(settings, snapshot)
    assert failure.value.code == "workspace_operation_unknown" and failure.value.status == 409
    assert len(calls) == 1


def test_prepare_lost_core_response_is_unknown_not_unconfigured(configured, snapshot, monkeypatch):
    monkeypatch.setattr(environment, "_helper", lambda *_: {"state": "ready"})
    monkeypatch.setattr(environment, "environment_for", lambda *_: object())
    monkeypatch.setattr(environment, "_manifest", lambda *_: {})

    async def request(settings, grant, suffix, *, body=None, allow_missing=False):
        if body is None:
            return None
        raise ConsoleError("app_delivery_unavailable", 503)

    monkeypatch.setattr(environment.delivery_tools, "api_request", request)
    result = asyncio.run(environment.prepare(configured, snapshot))
    assert result["state"] == "ready"
    assert result["preview"]["state"] == "unknown" and result["operation_unknown"]


def test_known_registration_conflict_keeps_sdk_editable(configured, snapshot, monkeypatch):
    monkeypatch.setattr(environment, "_helper", lambda *_: {"state": "ready"})
    monkeypatch.setattr(environment, "environment_for", lambda *_: object())

    async def request(*args, **kwargs):
        raise ConsoleError("app_delivery_conflict", 409)

    monkeypatch.setattr(environment.delivery_tools, "api_request", request)
    result = asyncio.run(environment.prepare(configured, snapshot))
    assert result["state"] == "ready" and result["preview"]["state"] == "blocked"
    assert not result.get("operation_unknown")


@pytest.mark.parametrize("action,wanted", [("stop", "stopped"), ("cleanup", "cleaned")])
def test_unregistered_workspace_can_stop_sdk_without_core_authority(
    snapshot, monkeypatch, action, wanted
):
    snapshot["preview"] = {"state": "unconfigured"}
    calls = []

    def helper(settings, selected, current):
        calls.append(current)
        return {"state": wanted}

    monkeypatch.setattr(environment, "_helper", helper)
    result = asyncio.run(
        getattr(environment, action)(
            SimpleNamespace(miy_api_origin=None, app_delivery_grants=[]), snapshot
        )
    )
    assert calls == [action] and result["state"] == wanted
    assert result["source_handoff_complete"] is False


def test_failed_candidate_preserves_last_runtime_link_and_revision(
    configured, snapshot, monkeypatch
):
    async def request(settings, selected, suffix, body=None, **kwargs):
        if suffix.endswith("/builds/" + environment._id(snapshot, "test", "build")):
            return {"state": "failed", "failure_code": "app_build_failed"}
        raise AssertionError("No deployment may be dispatched for a failed build")

    monkeypatch.setattr(environment, "_call", request)
    result = asyncio.run(
        environment._build_deploy(configured, snapshot, context(snapshot), "test", "a" * 40)
    )
    assert result["state"] == "failed"
    assert result["preview"]["runtime_revision"] == "b" * 40
    assert result["preview"]["portal_url"] == snapshot["preview"]["portal_url"]
    assert result["preview"]["source_revision"] == "a" * 40


def test_get_observer_never_resends_missing_unknown_deployment(configured, snapshot, monkeypatch):
    snapshot["operation_receipt"] = {"core": {"stage": "/deployments", "acknowledged": False}}
    calls = []

    async def request(settings, selected, suffix, body=None, **kwargs):
        assert body is None
        calls.append(suffix)
        if suffix == "/context":
            return context(snapshot)
        if "/builds/" in suffix:
            return {"state": "succeeded", "release_id": str(uuid4())}
        return None

    monkeypatch.setattr(environment, "_call", request)
    assert (
        asyncio.run(environment.observe(configured, snapshot, "test", "refresh", "a" * 40)) is None
    )
    assert len(calls) == 3


def test_confirmed_lost_build_can_wait_for_explicit_same_intent_continuation(
    configured, snapshot, monkeypatch
):
    snapshot["operation_receipt"] = {"core": {"stage": "/builds", "acknowledged": False}}

    async def request(settings, selected, suffix, body=None, **kwargs):
        assert body is None
        if suffix == "/context":
            return context(snapshot)
        return {"state": "succeeded"} if "/builds/" in suffix else None

    monkeypatch.setattr(environment, "_call", request)
    assert (
        asyncio.run(environment.observe(configured, snapshot, "test", "refresh", "a" * 40))["state"]
        == "waiting"
    )


def test_complete_requires_core_handoff_proof_and_uses_verified_permanent_link(
    configured, snapshot, monkeypatch
):
    selected = context(snapshot)
    selected.update(
        permanent_portal_url="https://portal.invalid/installed/permanent",
        integration_revision="d" * 40,
    )
    monkeypatch.setattr(environment, "_manifest", lambda *_: {})

    async def request(settings, value, suffix, body=None, **kwargs):
        if suffix == "/complete":
            return {"source_handoff_complete": False, "integration_revision": "d" * 40}
        return dict(selected)

    async def deploy(settings, value, target, operation, revision, **kwargs):
        assert target["portal_url"] == selected["permanent_portal_url"]
        return {"state": "ready", "deployment_id": str(uuid4())}

    monkeypatch.setattr(environment, "_call", request)
    monkeypatch.setattr(environment, "_build_deploy", deploy)
    with pytest.raises(ConsoleError, match="workspace_source_handoff_required"):
        asyncio.run(environment.integrate(configured, snapshot, "test", "d" * 40))


def test_mutation_records_attempt_before_dispatch_and_ack_after_response(
    configured, snapshot, monkeypatch
):
    evidence = []
    snapshot["record"] = evidence.append

    async def request(settings, grant, suffix, **kwargs):
        assert evidence[-1]["acknowledged"] is False
        return {"state": "queued"}

    monkeypatch.setattr(environment.delivery_tools, "api_request", request)
    asyncio.run(environment._call(configured, snapshot, "/builds", {"request_id": "opaque"}))
    assert [entry["acknowledged"] for entry in evidence] == [False, True]
    assert all(
        set(entry) == {"stage", "permanent", "acknowledged", "request_id", "source_revision"}
        for entry in evidence
    )


def test_sdk_only_lost_stop_is_resolved_by_owned_read_only_status(snapshot, monkeypatch):
    snapshot["preview"] = {"state": "unconfigured"}
    calls = []

    def helper(settings, selected, action):
        calls.append(action)
        return {"state": "stopped"}

    monkeypatch.setattr(environment, "_helper", helper)
    settings = SimpleNamespace(miy_api_origin=None, app_delivery_grants=[])
    result = asyncio.run(environment.observe(settings, snapshot, "same-intent", "stop", "a" * 40))
    assert result["state"] == "stopped" and result["source_handoff_complete"] is False
    assert calls == ["status"]
    snapshot["preview"]["installation_id"] = str(uuid4())
    assert (
        asyncio.run(environment.observe(settings, snapshot, "same-intent", "stop", "a" * 40))
        is None
    )
    assert calls == ["status"]


def test_sdk_cleanup_does_not_reclassify_core_cleaned_state_as_stopping(
    configured, snapshot, monkeypatch
):
    calls = []
    monkeypatch.setattr(environment, "_helper", lambda *_: {"state": "cleaned"})

    async def request(settings, selected, suffix, body=None, **kwargs):
        calls.append(suffix)
        assert body is None
        return {**context(snapshot), "state": "cleaned", "source_handoff_complete": True}

    monkeypatch.setattr(environment, "_call", request)
    result = asyncio.run(environment.stop(configured, snapshot))
    assert result["state"] == "stopped" and result["environment"]["state"] == "cleaned"
    assert result["source_handoff_complete"] is True and calls == ["/context"]


@pytest.mark.parametrize("has_core", [True, False])
def test_lost_resume_acknowledgement_restores_sdk_without_claiming_preview_deployment(
    configured, snapshot, monkeypatch, has_core
):
    snapshot["preview"]["state"] = "stopped"
    if not has_core:
        snapshot["preview"] = {"state": "unconfigured", "runtime_revision": None}
    previous_runtime = snapshot["preview"]["runtime_revision"]
    settings = (
        configured if has_core else SimpleNamespace(miy_api_origin=None, app_delivery_grants=[])
    )
    core_ready, sdk_ready, lose_ack = True, False, False
    requests, helpers, descriptors, evidence = [], [], [], []
    snapshot["record"] = evidence.append

    async def request(cfg, grant, suffix, *, body=None, **kwargs):
        nonlocal core_ready
        requests.append((suffix, body))
        if suffix.endswith("/context"):
            assert body is None
            return {**context(snapshot), "state": "ready" if core_ready else "stopped"}
        assert suffix.endswith("/resume") and body == {"expected_version": 1}
        core_ready = True
        return context(snapshot)

    def helper(cfg, selected, action):
        nonlocal sdk_ready
        helpers.append(action)
        if action == "resume":
            sdk_ready = True
            if lose_ack:
                raise ConsoleError("workspace_operation_unknown", 409)
            return {"state": "ready"}
        assert action == "status"
        return {"state": "ready" if sdk_ready else "stopped"}

    def descriptor(*args):
        descriptors.append("exact_owned_descriptor")
        return object()

    monkeypatch.setattr(environment.delivery_tools, "api_request", request)
    monkeypatch.setattr(environment, "_helper", helper)
    monkeypatch.setattr(environment, "environment_for", descriptor)
    normal = asyncio.run(environment.resume(settings, snapshot))
    assert normal["state"] == "ready" and normal["environment"]["state"] == "ready"
    assert normal["preview"]["state"] == ("configured" if has_core else "unconfigured")
    assert normal["preview"]["runtime_revision"] == previous_runtime

    requests.clear()
    helpers.clear()
    evidence.clear()
    core_ready, sdk_ready, lose_ack = False, False, True
    with pytest.raises(ConsoleError, match="workspace_operation_unknown"):
        asyncio.run(environment.resume(settings, snapshot))
    assert helpers == ["resume"]
    assert sum(body is not None for _, body in requests) == int(has_core)
    snapshot["operation_receipt"] = {"core": evidence[-1]} if evidence else {}
    before = len(requests)
    observed = asyncio.run(
        environment.observe(
            settings, snapshot, "same-intent", "resume", snapshot["source_revision"]
        )
    )
    assert observed["state"] == "ready" and observed["environment"]["state"] == "ready"
    assert observed["preview"]["state"] == normal["preview"]["state"]
    assert observed["preview"]["runtime_revision"] == previous_runtime
    assert observed["preview"]["runtime_revision"] != snapshot["source_revision"]
    assert observed["preview"]["source_revision"] == snapshot["source_revision"]
    assert helpers == ["resume", "status"] and descriptors == ["exact_owned_descriptor"]
    assert all(body is None for _, body in requests[before:])
    assert all(suffix.endswith(("/context", "/resume")) for suffix, _ in requests)


def test_observed_successful_deployment_updates_runtime_revision(configured, snapshot, monkeypatch):
    operation_id = str(uuid4())
    requests = []
    deployment_path = (
        "/workspaces/"
        + snapshot["id"]
        + "/deployments/"
        + environment._id(snapshot, operation_id, "deploy")
    )

    async def request(cfg, grant, suffix, *, body=None, **kwargs):
        assert body is None
        requests.append(suffix)
        if suffix.endswith("/context"):
            return context(snapshot)
        assert suffix == deployment_path
        return {"state": "succeeded"}

    monkeypatch.setattr(environment.delivery_tools, "api_request", request)
    observed = asyncio.run(
        environment.observe(
            settings=configured,
            snapshot=snapshot,
            operation_id=operation_id,
            kind="refresh",
            revision=snapshot["source_revision"],
        )
    )
    assert observed["state"] == "ready" and observed["preview"]["state"] == "ready"
    assert observed["preview"]["runtime_revision"] == snapshot["source_revision"]
    assert requests == ["/workspaces/" + snapshot["id"] + "/context", deployment_path]
