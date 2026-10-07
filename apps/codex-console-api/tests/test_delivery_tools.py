import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from jsonschema import ValidationError
from test_app_sources import app_checkout as app_checkout
from test_app_sources import bind, launch

from codex_console import delivery_tools as delivery
from codex_console.config import DeliveryGrant
from codex_console.errors import ConsoleError
from codex_console.models import Operation, Task, now


@pytest.mark.parametrize("version", [1, 1.0])
def test_manifest_integer_literals_have_one_canonical_representation(app_checkout, version):
    manifest = json.loads((app_checkout / "app.manifest.json").read_text())
    manifest.update(schema_version=version, sdk_version=version)
    normalized = delivery.normalize_manifest(manifest)
    assert type(normalized["schema_version"]) is int
    assert type(normalized["sdk_version"]) is int
    assert type(manifest["schema_version"]) is type(version)
    expected = delivery.normalize_manifest({**manifest, "schema_version": 1, "sdk_version": 1})
    assert json.dumps(normalized, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("version", [True, "1", 2.0])
def test_manifest_literal_canonicalization_does_not_widen_validation(app_checkout, version):
    manifest = json.loads((app_checkout / "app.manifest.json").read_text())
    manifest.update(schema_version=version, sdk_version=version)
    with pytest.raises(ValidationError):
        delivery.normalize_manifest(manifest)


@pytest.fixture
def target(client, settings, request):
    checkout = request.getfixturevalue("app_checkout")
    assert bind(client, checkout).status_code == 200
    body = launch(client).json()
    installation_id = uuid4()
    settings.miy_api_origin = "https://platform.example.test"
    settings.app_delivery_grants = [
        DeliveryGrant(app_id="sample-app", installation_id=installation_id, token="synthetic-" * 8)
    ]
    with client.app.state.factory.begin() as db:
        task = db.get(Task, body["id"])
        task.context = {
            **task.context,
            "purpose": "deployment",
            "installation_id": str(installation_id),
        }
    with client.app.state.factory() as db:
        task = db.get(Task, body["id"])
        db.expunge(task)
    revision, manifest = delivery.local_source(settings, task)
    context = {
        "app_id": "sample-app",
        "allowed_actions": ["read", "sync", "build", "deploy", "rollback"],
        "definition": manifest,
        "definition_digest": "sha256:" + "a" * 64,
        "source_revision": revision,
        "installation": {
            "id": str(installation_id),
            "environment": "development",
            "origin": "https://preview.example.test",
            "generation": 1,
            "release_id": None,
            "state": "configured",
            "enabled": True,
        },
        "releases": [],
    }
    return task, context


@pytest.mark.anyio
async def test_lost_build_response_reuses_existing_external_request(settings, target, monkeypatch):
    task, context = target
    records, posts = {}, []

    async def api(cfg, grant, suffix, *, body=None, allow_missing=False):
        if suffix == "/context":
            return context
        if suffix.startswith("/builds/"):
            return records.get(suffix.rsplit("/", 1)[-1])
        assert suffix == "/builds"
        posts.append(body)
        records[body["request_id"]] = {
            "id": body["request_id"],
            "app_id": "sample-app",
            "source_revision": body["source_revision"],
            "state": "queued",
            "failure_code": None,
            "release_id": None,
            "created_at": now().isoformat(),
            "updated_at": now().isoformat(),
        }
        raise ConsoleError("app_delivery_unavailable", 503)

    monkeypatch.setattr(delivery, "api_request", api)
    args = delivery.Arguments(action="build")
    lost = await delivery.execute(settings, task, args)
    assert lost["state"] == "unknown" and lost["next_action"] == "build_status"
    retry = await delivery.execute(settings, task, args)
    assert retry["state"] == "queued" and retry["id"] == lost["request_id"]
    assert len(posts) == 1
    assert set(posts[0]) == {"request_id", "source_revision", "definition_digest"}
    assert "synthetic" not in json.dumps(lost) + json.dumps(retry)


@pytest.mark.anyio
async def test_sync_uses_canonical_manifest_defaults_without_rewriting(
    settings, target, monkeypatch
):
    task, context = target
    calls = []

    async def api(cfg, grant, suffix, **kwargs):
        calls.append((suffix, kwargs))
        return context

    monkeypatch.setattr(delivery, "api_request", api)
    result = await delivery.execute(settings, task, delivery.Arguments(action="sync"))
    assert result["definition"]["entrypoints"]["health"] == "/healthz"
    assert all(suffix == "/context" and not kwargs for suffix, kwargs in calls)


@pytest.mark.anyio
@pytest.mark.parametrize("malformed", ["missing_fields", "wrong_id", "wrong_app", "invalid_state"])
async def test_malformed_post_response_preserves_request_identity_for_recovery(
    settings, target, monkeypatch, malformed
):
    task, context = target
    records, posts = {}, []

    async def api(cfg, grant, suffix, *, body=None, allow_missing=False):
        if suffix == "/context":
            return context
        if suffix.startswith("/builds/"):
            return records.get(suffix.rsplit("/", 1)[-1])
        assert suffix == "/builds"
        posts.append(body)
        record = {
            "id": body["request_id"], "app_id": "sample-app",
            "source_revision": body["source_revision"], "state": "queued",
            "release_id": None, "created_at": now().isoformat(), "updated_at": now().isoformat(),
        }
        records[record["id"]] = record
        if malformed == "missing_fields":
            return {"accepted": True}
        if malformed == "wrong_id":
            return {**record, "id": str(uuid4())}
        if malformed == "wrong_app":
            return {**record, "app_id": "another-app"}
        return {**record, "state": "invented-success"}

    monkeypatch.setattr(delivery, "api_request", api)
    args = delivery.Arguments(action="build")
    result = await delivery.execute(settings, task, args)
    assert result == {
        "state": "unknown", "request_id": posts[0]["request_id"], "next_action": "build_status"
    }
    recovered = await delivery.execute(settings, task, args)
    assert recovered["id"] == result["request_id"] and recovered["state"] == "queued"
    assert len(posts) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["failed", "running", "unknown"])
async def test_explicit_retry_only_replaces_a_confirmed_failed_build(
    settings, target, monkeypatch, state
):
    task, context = target
    previous_id, posts = str(uuid4()), []

    def record(ident, status):
        return {
            "id": ident,
            "app_id": "sample-app",
            "source_revision": context["source_revision"],
            "state": status,
            "release_id": None,
            "created_at": now().isoformat(),
            "updated_at": now().isoformat(),
        }

    async def api(cfg, grant, suffix, *, body=None, allow_missing=False):
        if suffix == "/context":
            return context
        if suffix == "/builds/" + previous_id:
            return record(previous_id, state)
        if suffix.startswith("/builds/"):
            assert allow_missing
            return None
        assert suffix == "/builds"
        posts.append(body)
        return record(body["request_id"], "queued")

    monkeypatch.setattr(delivery, "api_request", api)
    args = delivery.Arguments(action="build", retry_request_id=previous_id)
    if state == "failed":
        result = await delivery.execute(settings, task, args)
        assert result["state"] == "queued" and result["id"] != previous_id
        assert len(posts) == 1 and "retry_request_id" not in posts[0]
    else:
        with pytest.raises(ConsoleError, match="app_delivery_conflict"):
            await delivery.execute(settings, task, args)
        assert not posts


@pytest.mark.anyio
async def test_dirty_source_never_queues_build(settings, target, monkeypatch):
    task, context = target
    (Path(task.root) / "README.md").write_text("Uncommitted change")

    async def api(cfg, grant, suffix, **kwargs):
        assert suffix == "/context"
        return context

    monkeypatch.setattr(delivery, "api_request", api)
    with pytest.raises(ConsoleError, match="app_delivery_source_uncommitted"):
        await delivery.execute(settings, task, delivery.Arguments(action="build"))


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["queued", "running", "cleanup", "unknown"])
async def test_cutover_never_hides_an_unfinished_deployment(
    settings, target, monkeypatch, state
):
    task, context = target
    release_id, pending_id = str(uuid4()), str(uuid4())
    context["installation"]["release_id"] = release_id
    context["pending_deployment"] = {
        "id": pending_id,
        "release_id": release_id,
        "action": "deploy",
        "state": state,
    }

    async def api(cfg, grant, suffix, **kwargs):
        assert suffix == "/context" and not kwargs
        return context

    monkeypatch.setattr(delivery, "api_request", api)
    result = await delivery.execute(
        settings, task, delivery.Arguments(action="deploy", release_id=release_id)
    )
    assert result == {
        **context["pending_deployment"],
        "next_action": "deployment_status",
    }


@pytest.mark.anyio
async def test_delegated_context_cannot_redirect_target(settings, target, monkeypatch):
    task, context = target
    context["installation"]["id"] = str(uuid4())

    async def api(*args, **kwargs):
        return context

    monkeypatch.setattr(delivery, "api_request", api)
    with pytest.raises(ConsoleError, match="app_delivery_unavailable"):
        await delivery.execute(settings, task, delivery.Arguments(action="context"))


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["host", "child", "generation", "turn", "plan"])
async def test_native_delivery_requires_current_parent_execution(
    client, settings, target, monkeypatch, boundary
):
    task, _ = target
    with client.app.state.factory.begin() as db:
        row = db.get(Task, task.id)
        row.thread_id, row.turn_id, row.runtime_generation = "parent", "turn", "generation"
        row.status, row.stage = "running", "plan"
    responses = []

    async def respond(ident, value):
        responses.append(value)

    async def forbidden(*args):
        pytest.fail("Unauthorized delivery must not contact the platform")

    monkeypatch.setattr(delivery, "execute", forbidden)
    runtime = SimpleNamespace(
        settings=settings,
        factory=client.app.state.factory,
        executor="session",
        remote_task_id=None if boundary == "host" else task.id,
        rpc=SimpleNamespace(generation="generation", respond=respond),
        task_gate=lambda _: asyncio.Lock(),
        require_allowed_task=lambda _: None,
    )
    message = {
        "id": 1,
        "method": "item/tool/call",
        "params": {
            "callId": "native-call-1",
            "tool": delivery.TOOL_NAME,
            "threadId": "child" if boundary == "child" else "parent",
            "turnId": "old" if boundary == "turn" else "turn",
            "arguments": {"action": "build"},
        },
    }
    assert await delivery.handle(
        runtime, message, generation="old" if boundary == "generation" else "generation"
    )
    if boundary == "generation":
        assert responses == []
    else:
        assert not responses[0]["success"]
        assert json.loads(responses[0]["contentItems"][0]["text"]) == {
            "error": "app_delivery_denied"
        }


@pytest.mark.anyio
async def test_transport_keeps_grant_on_configured_origin_and_bounds_response(
    settings, target, monkeypatch
):
    task, _ = target
    client_class = httpx.AsyncClient
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://elsewhere.example.test"})

    def client(**options):
        assert options["trust_env"] is False and options["follow_redirects"] is False
        return client_class(**options, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(delivery.httpx, "AsyncClient", client)
    with pytest.raises(ConsoleError, match="app_delivery_unavailable"):
        await delivery.api_request(settings, delivery.grant_for(settings, task.context), "/context")
    assert len(calls) == 1 and calls[0].url.host == "platform.example.test"
    assert calls[0].headers["authorization"].startswith("Bearer synthetic-")


@pytest.mark.anyio
async def test_authorized_native_parent_creates_only_app_checkpoint(
    client, settings, target, monkeypatch
):
    task, context = target
    (Path(task.root) / "README.md").write_text("App edit for preview")
    operation_id = str(uuid4())
    with client.app.state.factory.begin() as db:
        row = db.get(Task, task.id)
        row.thread_id, row.turn_id, row.runtime_generation = "parent", "turn", "generation"
        row.status, row.stage, row.current_operation_id = "running", "implement", operation_id
        db.add(Operation(
            id=operation_id, task_id=task.id, kind="execute", state="accepted", digest="f" * 64
        ))
    responses, calls = [], []

    async def api(cfg, grant, suffix, **kwargs):
        calls.append(suffix)
        assert suffix == "/context" and not kwargs
        return context

    async def respond(ident, value):
        assert ident == 17
        responses.append(value)

    monkeypatch.setattr(delivery, "api_request", api)
    runtime = SimpleNamespace(
        settings=settings,
        factory=client.app.state.factory,
        executor="session",
        remote_task_id=task.id,
        rpc=SimpleNamespace(generation="generation", respond=respond),
        task_gate=lambda _: asyncio.Lock(),
        require_allowed_task=lambda _: None,
    )
    assert await delivery.handle(runtime, {
        "id": 17,
        "method": "item/tool/call",
        "params": {
            "callId": "native-checkpoint-call",
            "tool": delivery.TOOL_NAME,
            "threadId": "parent",
            "turnId": "turn",
            "arguments": {"action": "checkpoint"},
        },
    }, generation="generation")
    assert responses[0]["success"] is True
    result = json.loads(responses[0]["contentItems"][0]["text"])
    revision, _ = delivery.local_source(settings, task)
    assert result == {"created": True, "source_revision": revision}
    assert revision != context["source_revision"]
    assert calls == ["/context"]


def test_model_cannot_supply_host_commands_credentials_or_installation():
    for key in ("command", "source", "token", "installation_id", "success"):
        with pytest.raises(ValueError):
            delivery.Arguments.model_validate({"action": "build", key: "injected"})
