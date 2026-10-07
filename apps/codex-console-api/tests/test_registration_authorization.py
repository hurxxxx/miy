"""Synthetic first-registration authority, never actual platform registration."""

import hashlib
import json
import os
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from conftest import PASSWORD
from test_app_sources import app_checkout as app_checkout
from test_app_sources import bind, command
from test_registration_draft import project

from codex_console import auth, registration_source, registration_tools
from codex_console import registration as reg
from codex_console.errors import ConsoleError
from codex_console.models import (
    RegistrationIntent,
    Task,
    WebSession,
    database,
    now,
)
from codex_console.storage import database_path

TOKEN = "miyrg_" + "t" * 43
CODE = "miyrc_" + "c" * 43
ORIGIN = "https://preview.example.test"


def test_registration_policy_supports_explicit_selected_file_permission_without_defaults():
    from pydantic import ValidationError

    policy = dict(app_id="file-app", origin=ORIGIN, runtime_profile="web-api-v1")
    all_permissions = ["identity:read", "data:read", "data:write", "files:read-selected"]
    assert (
        reg.Policy(**policy, requested_permissions=all_permissions).requested_permissions
        == all_permissions
    )
    assert reg.Policy(**policy, requested_permissions=["identity:read"]).requested_permissions == [
        "identity:read"
    ]
    with pytest.raises(ValidationError):
        reg.Policy(**policy, requested_permissions=["files:read-all"])
    with pytest.raises(ValidationError):
        reg.Policy(**policy, requested_permissions=[*all_permissions, "identity:read"])


@pytest.fixture
def target(client, settings, app_checkout):
    row = project(client)
    assert bind(client, app_checkout).status_code == 200
    settings.registration_authorization_enabled = True
    settings.miy_api_origin = "https://platform.example.test"
    settings.sso_subjects = {settings.miy_api_origin: uuid4()}
    response = client.post(
        "/api/tasks",
        json={
            "title": "First registration",
            "context": {"purpose": "registration", "project_id": row["id"], "app_id": "sample-app"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def start(client, target):
    response = client.post(
        f"/api/tasks/{target['id']}/registration/authorize", json={"origin": ORIGIN}
    )
    assert response.status_code == 200, response.text
    return response.json()


def exchange_value(settings, row):
    return {
        "schema_version": 1,
        "id": str(uuid4()),
        "request_id": row.request_id,
        "operation_id": row.operation_id,
        "actor_user_id": row.actor_user_id,
        "audience": row.audience,
        "policy": row.policy,
        "expires_at": (now() + timedelta(seconds=250)).isoformat(),
        "token": TOKEN,
    }


def connect(client, settings, target, monkeypatch):
    started = start(client, target)
    with client.app.state.factory() as db:
        row = db.get(RegistrationIntent, target["id"])
        value = exchange_value(settings, row)

    async def api(cfg, suffix, **kwargs):
        assert suffix == "/exchange"
        verifier = kwargs["body"]["code_verifier"]
        query = parse_qs(urlsplit(started["authorization_url"]).query)
        import base64

        assert (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
            == query["code_challenge"][0]
        )
        return value

    monkeypatch.setattr(reg, "api", api)
    response = client.post(
        reg.CALLBACK,
        data={"request_id": value["request_id"], "code": CODE},
        headers={"origin": settings.miy_api_origin, "cookie": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/?task=" + target["id"]
    return value


def receipt(body):
    return {
        "operation_id": body["operation_id"],
        "app_id": body["definition"]["app_id"],
        "installation_id": str(uuid4()),
        "definition_digest": "sha256:"
        + hashlib.sha256(
            json.dumps(body["definition"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_revision": body["source_revision"],
        "created_at": now().isoformat(),
    }


def execute(client, settings, target, action):
    return client.portal.call(
        lambda: registration_tools.execute(
            settings,
            client.app.state.factory,
            target["id"],
            action,
            check=lambda: reg.session_gate(
                client.app.state.factory, target["id"], client.cookies[auth.COOKIE]
            ),
        )
    )


def test_disabled_and_bound_project_required(client, settings, app_checkout):
    assert (
        client.post(
            "/api/tasks", json={"title": "denied", "context": {"purpose": "registration"}}
        ).status_code
        == 503
    )
    settings.registration_authorization_enabled = True
    settings.miy_api_origin = "https://platform.example.test"
    settings.sso_subjects = {settings.miy_api_origin: uuid4()}
    assert (
        client.post(
            "/api/tasks", json={"title": "denied", "context": {"purpose": "registration"}}
        ).status_code
        == 403
    )


def test_callback_cross_site_without_cookie_keeps_secrets_out_of_database_and_api(
    client, settings, target, monkeypatch
):
    value = connect(client, settings, target, monkeypatch)
    response = client.get(f"/api/tasks/{target['id']}/registration")
    assert response.json()["authorization_state"] == "ready"
    with client.app.state.factory() as db:
        row = db.get(RegistrationIntent, target["id"])
        assert reg.secret(settings, row.request_id, "token") == TOKEN
        vault = database_path(settings.database_url).parent / "registration-credentials"
        assert vault.stat().st_mode & 0o777 == 0o700
        assert (vault / (row.request_id + ".token")).stat().st_mode & 0o777 == 0o600
        assert not (vault / (row.request_id + ".verifier")).exists()
        assert TOKEN not in repr(row.__dict__)
        assert CODE not in repr(row.__dict__)
    assert TOKEN not in response.text and CODE not in response.text
    assert TOKEN not in client.get(f"/api/tasks/{target['id']}").text
    assert (
        client.post(
            reg.CALLBACK,
            data={"request_id": value["request_id"], "code": CODE},
            headers={"origin": settings.miy_api_origin},
            follow_redirects=False,
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "origin", ["null", "https://evil.example", "https://platform.example.test.evil"]
)
def test_callback_exact_origin_and_other_paths_keep_csrf(client, settings, target, origin):
    started = start(client, target)
    request_id = parse_qs(urlsplit(started["authorization_url"]).query)["request_id"][0]
    assert (
        client.post(
            reg.CALLBACK, data={"request_id": request_id, "code": CODE}, headers={"origin": origin}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/tasks", json={"title": "cross site"}, headers={"origin": settings.miy_api_origin}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/tasks/{target['id']}/registration/authorize",
            json={"origin": ORIGIN},
            headers={"x-csrf-token": ""},
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "change", ["actor", "audience", "policy", "operation", "expired", "token", "version"]
)
def test_exchange_invalid_identity_fails_closed(client, settings, target, monkeypatch, change):
    start(client, target)
    with client.app.state.factory() as db:
        row = db.get(RegistrationIntent, target["id"])
        value = exchange_value(settings, row)
    if change == "version":
        value["schema_version"] = True
    elif change == "actor":
        value["actor_user_id"] = str(uuid4())
    elif change == "audience":
        value["audience"] = "https://elsewhere.example"
    elif change == "policy":
        value["policy"] = {**value["policy"], "origin": "https://elsewhere.example"}
    elif change == "operation":
        value["operation_id"] = str(uuid4())
    elif change == "expired":
        value["expires_at"] = (now() - timedelta(seconds=1)).isoformat()
    else:
        value["token"] = "not-a-registration-grant"

    async def api(*args, **kwargs):
        return value

    monkeypatch.setattr(reg, "api", api)
    response = client.post(
        reg.CALLBACK,
        data={"request_id": value["request_id"], "code": CODE},
        headers={"origin": settings.miy_api_origin},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (
        client.get(f"/api/tasks/{target['id']}/registration").json()["authorization_state"]
        == "failed"
    )
    assert (
        list((database_path(settings.database_url).parent / "registration-credentials").iterdir())
        == []
    )


def test_logout_revokes_current_task_and_new_login_cannot_inherit(
    client, settings, target, monkeypatch
):
    value = connect(client, settings, target, monkeypatch)
    operation = value["operation_id"]
    assert client.delete("/api/session").status_code == 200
    vault = database_path(settings.database_url).parent / "registration-credentials"
    assert list(vault.iterdir()) == []
    result = client.post("/api/session", json={"password": PASSWORD})
    assert result.status_code == 200
    client.headers["x-csrf-token"] = client.cookies[auth.CSRF_COOKIE]
    for suffix, body in [
        ("messages", {"operation_id": str(uuid4()), "text": "plan"}),
        ("implement", {"operation_id": str(uuid4()), "text": "register"}),
    ]:
        result = client.post(f"/api/tasks/{target['id']}/{suffix}", json=body)
        assert result.status_code == 403, result.text
    assert (
        client.get(f"/api/tasks/{target['id']}/registration").json()["authorization_state"]
        == "other_session"
    )
    assert start(client, target)["status"]["operation_id"] == operation


def test_register_response_loss_and_source_drift_read_same_receipt(
    client, settings, target, app_checkout, monkeypatch
):
    connect(client, settings, target, monkeypatch)
    posts = []
    saved = {}

    async def api(cfg, suffix, *, body=None, **kwargs):
        if suffix.endswith("/receipt"):
            return saved.get("receipt")
        posts.append(body)
        saved["receipt"] = receipt(body)
        raise ConsoleError("registration_unavailable", 503)

    monkeypatch.setattr(reg, "api", api)
    first = execute(client, settings, target, "register")
    assert first["state"] == "unknown" and len(posts) == 1
    (app_checkout / "README.md").write_text("dirty after submission")
    result = client.post(f"/api/tasks/{target['id']}/registration/receipt")
    assert result.status_code == 200, result.text
    assert (
        result.json()["receipt"]
        == reg.Receipt.model_validate(saved["receipt"]).model_dump(mode="json")
        and len(posts) == 1
    )
    # Reconnect even after root metadata disappears, to read only this historical body.
    command(app_checkout, "remote", "set-url", "origin", "https://example.test/changed.git")
    assert start(client, target)["status"]["operation_id"] == first["operation_id"]


def test_missing_receipt_never_automatically_resubmits_or_changes_payload(
    client, settings, target, app_checkout, monkeypatch
):
    connect(client, settings, target, monkeypatch)
    posts = []

    async def api(cfg, suffix, *, body=None, **kwargs):
        if suffix.endswith("/receipt"):
            return None
        posts.append(body)
        raise ConsoleError("registration_unavailable", 503)

    monkeypatch.setattr(reg, "api", api)
    execute(client, settings, target, "register")
    assert execute(client, settings, target, "status")["state"] == "not_observed"
    (app_checkout / "README.md").write_text("different")
    command(app_checkout, "add", "README.md")
    command(app_checkout, "commit", "-m", "new source")
    with pytest.raises(ConsoleError, match="registration_request_frozen"):
        execute(client, settings, target, "register")
    assert len(posts) == 1


def test_immutable_receipt_mismatch_after_post_is_unknown(client, settings, target, monkeypatch):
    connect(client, settings, target, monkeypatch)

    async def api(cfg, suffix, *, body=None, **kwargs):
        if suffix.endswith("/receipt"):
            return None
        return {**receipt(body), "source_revision": "f" * 40}

    monkeypatch.setattr(reg, "api", api)
    assert execute(client, settings, target, "register")["state"] == "unknown"
    with client.app.state.factory() as db:
        row = db.get(RegistrationIntent, target["id"])
        assert row.state == "unknown" and row.request_body and row.receipt is None


def test_three_factories_and_restart_share_only_private_credentials(
    client, settings, target, monkeypatch
):
    value = connect(client, settings, target, monkeypatch)
    engines = []
    try:
        for _ in range(3):
            engine, factory = database(settings.database_url)
            engines.append(engine)
            with factory() as db:
                row = db.get(RegistrationIntent, target["id"])
                assert row.grant_id == value["id"]
                assert reg.secret(settings, row.request_id, "token") == TOKEN
    finally:
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize("damage", ["mode", "symlink", "hardlink", "vault-symlink"])
def test_credential_files_fail_closed_without_deleting_foreign_target(settings, tmp_path, damage):
    request_id = str(uuid4())
    reg.secret(settings, request_id, "token", TOKEN)
    vault = database_path(settings.database_url).parent / "registration-credentials"
    path = vault / (request_id + ".token")
    foreign = tmp_path / "foreign"
    foreign.write_text("preserve")
    if damage == "mode":
        path.chmod(0o644)
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(foreign)
    elif damage == "hardlink":
        path.unlink()
        os.link(foreign, path)
    else:
        renamed = vault.with_name("old-vault")
        vault.rename(renamed)
        vault.symlink_to(renamed, target_is_directory=True)
    with pytest.raises((ConsoleError, OSError, ValueError)):
        reg.secret(settings, request_id, "token")
    reg.cleanup(settings, request_id)
    assert foreign.read_text() == "preserve"


def test_task_worktree_snapshot_uses_its_commit_and_never_base_checkout(
    client, settings, target, app_checkout
):
    original = command(app_checkout, "rev-parse", "HEAD")
    worktree = settings.worktree_root / f"codex-{target['id']}"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    command(app_checkout, "worktree", "add", "-b", "registration-worktree", str(worktree))
    (worktree / "README.md").write_text("Task-only source")
    command(worktree, "add", "README.md")
    command(worktree, "commit", "-m", "task source")
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        task.root = str(worktree)
        task.worktree_owned = True
    draft = registration_source.snapshot(settings, client.app.state.factory, target["id"])
    assert draft.source_revision == command(worktree, "rev-parse", "HEAD") != original
    assert command(app_checkout, "rev-parse", "HEAD") == original
    (worktree / "README.md").write_text("pending")
    with pytest.raises(ConsoleError, match="app_source_dirty"):
        registration_source.snapshot(settings, client.app.state.factory, target["id"])
    assert command(app_checkout, "rev-parse", "HEAD") == original


@pytest.mark.parametrize(
    "origin",
    [
        "https://Example.test",
        "https://example.test:443",
        "https://example.test/",
        "https://user@example.test",
        "http://remote.test",
        "https://example.test\n",
        "https://example.test?",
    ],
)
def test_origin_is_canonical_before_authorization_url(origin):
    with pytest.raises(ValueError):
        reg.Begin(origin=origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test",
        "https://example.test:8443",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
    ],
)
def test_exact_development_origins_remain_supported(origin):
    assert reg.Begin(origin=origin).origin == origin


@pytest.mark.parametrize("boundary", ["logout", "new-request", "task-started", "generation"])
def test_exchange_rechecks_authority_after_network(client, settings, target, monkeypatch, boundary):
    start(client, target)
    with client.app.state.factory() as db:
        value = exchange_value(settings, db.get(RegistrationIntent, target["id"]))

    async def api(*args, **kwargs):
        with client.app.state.factory.begin() as db:
            row = db.get(RegistrationIntent, target["id"])
            task = db.get(Task, target["id"])
            if boundary == "logout":
                db.delete(db.get(WebSession, row.web_session_hash))
            elif boundary == "new-request":
                row.request_id = str(uuid4())
            elif boundary == "task-started":
                task.status = "running"
            else:
                task.runtime_generation = str(uuid4())
        return value

    monkeypatch.setattr(reg, "api", api)
    response = client.post(
        reg.CALLBACK,
        data={"request_id": value["request_id"], "code": CODE},
        headers={"origin": settings.miy_api_origin},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with client.app.state.factory() as db:
        assert db.get(RegistrationIntent, target["id"]).authorization_state != "ready"
    assert (
        list((database_path(settings.database_url).parent / "registration-credentials").iterdir())
        == []
    )


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["host", "child", "generation", "turn", "plan", "session"])
async def test_native_registration_uses_current_root_turn_and_implementation(
    client, settings, target, monkeypatch, boundary
):
    import asyncio
    from types import SimpleNamespace

    from codex_console.models import Operation

    connect(client, settings, target, monkeypatch)
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        operation_id = str(uuid4())
        db.add(
            Operation(
                id=operation_id,
                task_id=task.id,
                kind="execute",
                state="accepted",
                digest="a" * 64,
                display_text="Register this app",
            )
        )
        task.current_operation_id = operation_id
        task.thread_id, task.turn_id, task.runtime_generation = "parent", "turn", "generation"
        task.status, task.stage = "running", "plan" if boundary == "plan" else "implement"
        if boundary == "session":
            row = db.get(RegistrationIntent, task.id)
            db.delete(db.get(WebSession, row.web_session_hash))
    responses = []

    async def respond(ident, value):
        responses.append(value)

    async def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized native action reached transport")

    monkeypatch.setattr(reg, "api", forbidden)
    runtime = SimpleNamespace(
        settings=settings,
        factory=client.app.state.factory,
        executor="session",
        remote_task_id=None if boundary == "host" else target["id"],
        rpc=SimpleNamespace(generation="generation", respond=respond),
        task_gate=lambda _: asyncio.Lock(),
        require_allowed_task=lambda _: None,
    )
    message = {
        "id": 1,
        "method": "item/tool/call",
        "params": {
            "callId": "call1",
            "tool": registration_tools.TOOL_NAME,
            "threadId": "child" if boundary == "child" else "parent",
            "turnId": "old" if boundary == "turn" else "turn",
            "arguments": {"action": "register"},
        },
    }
    assert await registration_tools.handle(
        runtime, message, generation="old" if boundary == "generation" else "generation"
    )
    assert not responses if boundary == "generation" else not responses[0]["success"]


def test_native_action_arguments_cannot_accept_credentials_manifest_or_paths():
    for key in ("token", "manifest", "origin", "source_revision", "command", "operation_id"):
        with pytest.raises(ValueError):
            registration_tools.Arguments(action="register", **{key: "injected"})


def test_active_task_cannot_rebind_registration_to_new_session(client, settings, target):
    first = start(client, target)
    with client.app.state.factory.begin() as db:
        db.get(Task, target["id"]).status = "running"
    response = client.post(
        f"/api/tasks/{target['id']}/registration/authorize", json={"origin": ORIGIN}
    )
    assert response.status_code == 409 and response.json()["code"] == "task_busy"
    assert (
        client.get(f"/api/tasks/{target['id']}/registration").json()["operation_id"]
        == first["status"]["operation_id"]
    )


def test_turn_owner_rechecks_current_session_inside_write_transaction(client, settings, target):
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        row = db.get(RegistrationIntent, task.id)
        previous = row.web_session_hash
        row.web_session_hash = "b" * 64
        db.add(
            WebSession(
                token_hash=row.web_session_hash,
                csrf_hash="c" * 64,
                expires_at=now() + timedelta(hours=1),
            )
        )
    with client.app.state.factory.begin() as db:
        with pytest.raises(ConsoleError, match="registration_session_changed"):
            reg.turn_owner(db, db.get(Task, target["id"]), previous)


def _read_credential_process(configuration, task_id, result):
    from codex_console.config import Settings

    settings = Settings(**configuration, _env_file=None)
    engine, factory = database(settings.database_url)
    try:
        with factory() as db:
            row = db.get(RegistrationIntent, task_id)
            value = reg.secret(settings, row.request_id, "token")
            result.put((row.operation_id, hashlib.sha256(value.encode()).hexdigest()))
    finally:
        engine.dispose()


def test_three_processes_read_persisted_authority_after_restart(
    client, settings, target, monkeypatch
):
    import multiprocessing

    value = connect(client, settings, target, monkeypatch)
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Queue()
    config = {
        "database_url": settings.database_url,
        "origin": settings.origin,
        "workspace": settings.workspace,
        "worktree_root": settings.worktree_root,
        "web_dist": settings.web_dist,
        "attachment_cache": settings.attachment_cache,
    }
    workers = [
        ctx.Process(target=_read_credential_process, args=(config, target["id"], result))
        for _ in range(3)
    ]
    for worker in workers:
        worker.start()
    try:
        for _ in workers:
            assert result.get(timeout=20) == (
                value["operation_id"],
                hashlib.sha256(TOKEN.encode()).hexdigest(),
            )
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)


@pytest.mark.anyio
@pytest.mark.parametrize("native_state", ["idle", "active"])
@pytest.mark.parametrize("revoke", [False, True])
async def test_uncertain_native_reconnect_checks_session_after_read(
    client, settings, target, monkeypatch, native_state, revoke
):
    from types import SimpleNamespace

    from codex_console.models import Operation

    runtime = client.app.state.runtime.for_task(target["id"])
    operation_id = str(uuid4())
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        task.thread_id, task.turn_id, task.runtime_generation = "parent", "turn", "old-generation"
        task.status, task.stage, task.permissions = "uncertain", "plan", "read-only"
        task.current_operation_id = operation_id
        db.add(
            Operation(
                id=operation_id,
                task_id=task.id,
                kind="plan",
                state="uncertain",
                digest="a" * 64,
                display_text="synthetic plan",
            )
        )
        session_hash = db.get(RegistrationIntent, task.id).web_session_hash

    async def call(method, params):
        assert method == "thread/read"
        if revoke:
            with client.app.state.factory.begin() as db:
                db.delete(db.get(WebSession, session_hash))
        return {
            "thread": {
                "id": "parent",
                "cwd": target["root"],
                "status": {"type": native_state},
                "turns": [{"id": "turn", "status": "inProgress", "items": []}]
                if native_state == "active"
                else [],
            }
        }

    rpc = SimpleNamespace(generation="new-generation", call=call)
    runtime.rpc = rpc

    async def authenticated():
        return rpc

    monkeypatch.setattr(runtime, "authenticated_rpc", authenticated)
    recovered = []

    async def recover(task_id, *, expected_submission=None, registration_session_hash=None):
        with client.app.state.factory() as db:
            reg.turn_owner(db, db.get(Task, task_id), registration_session_hash)
        recovered.append(registration_session_hash)

    monkeypatch.setattr(runtime, "recover", recover)
    try:
        if revoke:
            with pytest.raises(ConsoleError, match="registration_session_changed"):
                await runtime.prepare_submission(
                    target["id"], registration_session_hash=session_hash
                )
        else:
            result = await runtime.prepare_submission(
                target["id"], registration_session_hash=session_hash
            )
            assert result == ("turn" if native_state == "active" else False)
            assert recovered == ([session_hash] if native_state == "idle" else [])
        with client.app.state.factory() as db:
            task = db.get(Task, target["id"])
            assert task.status == (
                "running" if native_state == "active" and not revoke else "uncertain"
            )
    finally:
        runtime.rpc = None


def test_sqlite_0007_upgrade_preserves_sessions_and_tasks_without_inheriting_grants(tmp_path):
    from sqlalchemy import inspect

    from codex_console.cli import migrate

    url = "sqlite+pysqlite:///" + str(tmp_path / "old.sqlite3")
    migrate(url, "console_sqlite_0007")
    engine, factory = database(url)
    try:
        with factory.begin() as db:
            task = Task(
                title="Existing task", root=str(tmp_path), context={"purpose": "development"}
            )
            db.add(task)
            db.add(
                WebSession(
                    token_hash="a" * 64, csrf_hash="b" * 64, expires_at=now() + timedelta(hours=1)
                )
            )
            db.flush()
            task_id = task.id
    finally:
        engine.dispose()
    migrate(url)
    engine, factory = database(url)
    try:
        assert "console_registration_intents" in inspect(engine).get_table_names()
        with factory() as db:
            assert db.get(Task, task_id).title == "Existing task"
            assert db.get(WebSession, "a" * 64)
            assert db.get(RegistrationIntent, task_id) is None
    finally:
        engine.dispose()


@pytest.mark.anyio
async def test_authorized_native_checkpoint_register_and_status_use_one_operation(
    client, settings, target, app_checkout, monkeypatch
):
    import asyncio
    from types import SimpleNamespace

    from codex_console.models import Operation

    connect(client, settings, target, monkeypatch)
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        operation_id = str(uuid4())
        db.add(
            Operation(
                id=operation_id,
                task_id=task.id,
                kind="execute",
                state="accepted",
                digest="a" * 64,
                display_text="Register this app",
            )
        )
        task.current_operation_id = operation_id
        task.thread_id, task.turn_id, task.runtime_generation = "parent", "turn", "generation"
        task.status, task.stage = "running", "implement"
        assert [item["name"] for item in registration_tools.specs(task)] == [
            registration_tools.TOOL_NAME
        ]
    responses = []

    async def respond(ident, value):
        responses.append(value)

    runtime = SimpleNamespace(
        settings=settings,
        factory=client.app.state.factory,
        executor="session",
        remote_task_id=target["id"],
        rpc=SimpleNamespace(generation="generation", respond=respond),
        task_gate=lambda _: asyncio.Lock(),
        require_allowed_task=lambda task: registration_source.app_sources.require_task_source(
            settings, task
        ),
    )
    saved = {}
    posts = []

    async def api(cfg, suffix, *, body=None, **kwargs):
        if suffix.endswith("/receipt"):
            return saved.get("receipt")
        posts.append(body)
        saved["receipt"] = receipt(body)
        return saved["receipt"]

    monkeypatch.setattr(reg, "api", api)
    (app_checkout / "README.md").write_text("Authorized source checkpoint")

    async def action(name):
        message = {
            "id": 1,
            "method": "item/tool/call",
            "params": {
                "callId": "native1",
                "tool": registration_tools.TOOL_NAME,
                "threadId": "parent",
                "turnId": "turn",
                "arguments": {"action": name},
            },
        }
        await registration_tools.handle(runtime, message, generation="generation")
        assert responses[-1]["success"], responses[-1]
        return json.loads(responses[-1]["contentItems"][0]["text"])

    checkpoint = await action("checkpoint")
    assert checkpoint["created"] is True
    result = await action("register")
    assert result["state"] == "registered"
    assert result["receipt"]["source_revision"] == checkpoint["source_revision"]
    assert (await action("status"))["receipt"] == result["receipt"]
    assert len(posts) == 1
    assert TOKEN not in json.dumps(responses) and CODE not in json.dumps(responses)


@pytest.mark.parametrize("native_state", ["idle", "active", "notLoaded", "systemError"])
def test_new_session_can_only_recover_inactive_registration_without_inheriting_grant(
    client, settings, target, monkeypatch, native_state
):
    from types import SimpleNamespace

    connect(client, settings, target, monkeypatch)
    runtime = client.app.state.runtime.for_task(target["id"])
    with client.app.state.factory.begin() as db:
        row = db.get(RegistrationIntent, target["id"])
        db.get(WebSession, row.web_session_hash).expires_at = now() - timedelta(seconds=1)
        task = db.get(Task, target["id"])
        task.status, task.thread_id, task.turn_id = "uncertain", "existing", "turn"
        saved = {
            key: getattr(row, key)
            for key in (
                "web_session_hash",
                "request_id",
                "operation_id",
                "grant_id",
                "request_body",
            )
        }
    result = client.post("/api/session", json={"password": PASSWORD})
    assert result.status_code == 200
    client.headers["x-csrf-token"] = client.cookies[auth.CSRF_COOKIE]
    rpc = SimpleNamespace(generation="fixture", connected=True)
    monkeypatch.setattr(runtime, "rpc", rpc)

    async def authenticated():
        return rpc

    async def ensure(task_id, rpc, *, revalidate=None):
        if revalidate:
            with client.app.state.factory() as db:
                revalidate(db, db.get(Task, task_id))
        return {
            "thread": {
                "id": "existing",
                "cwd": target["root"],
                "status": {"type": native_state},
                "turns": [],
            },
            "cwd": target["root"],
            "sandbox": {"type": "readOnly"},
        }

    monkeypatch.setattr(runtime, "authenticated_rpc", authenticated)
    monkeypatch.setattr(runtime, "ensure_thread", ensure)
    response = client.post(f"/api/tasks/{target['id']}/recover", json={})
    assert response.status_code == (200 if native_state == "idle" else 409), response.text
    with client.app.state.factory() as db:
        row = db.get(RegistrationIntent, target["id"])
        assert {key: getattr(row, key) for key in saved} == saved
        assert reg.secret(settings, row.request_id, "token") == TOKEN
        assert db.get(Task, target["id"]).status == (
            "interrupted" if native_state == "idle" else "uncertain"
        )
    assert (
        client.post(
            f"/api/tasks/{target['id']}/messages",
            json={"operation_id": str(uuid4()), "text": "resume"},
        ).status_code
        == 403
    )
    if native_state == "idle":
        fresh = connect(client, settings, target, monkeypatch)
        assert fresh["operation_id"] == saved["operation_id"]
        assert fresh["id"] != saved["grant_id"]
        with client.app.state.factory() as db:
            reg.turn_owner(db, db.get(Task, target["id"]), auth.digest(client.cookies[auth.COOKIE]))
            assert db.get(RegistrationIntent, target["id"]).authorization_state == "ready"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changed", ["rpc", "generation", "disconnected", "task-root", "turn", "session"]
)
async def test_real_ensure_thread_guards_registration_recovery_before_persistence(
    client, settings, target, monkeypatch, changed
):
    from types import SimpleNamespace

    from codex_console import remote_environments
    from codex_console.models import Agent

    runtime = client.app.state.runtime.for_task(target["id"])
    with client.app.state.factory.begin() as db:
        task = db.get(Task, target["id"])
        task.status, task.thread_id, task.turn_id = "uncertain", "existing", "turn"
        task.model = "previous-model"
        session_hash = db.get(RegistrationIntent, task.id).web_session_hash
        environments = remote_environments.selectors(task)

    async def configuration(*args):
        return {}

    monkeypatch.setattr(runtime, "configuration", configuration)

    async def call(method, params):
        assert method == "thread/resume" and params["sandbox"] == "read-only"
        if changed == "rpc":
            runtime.rpc = SimpleNamespace(generation="replacement", connected=True)
        elif changed == "generation":
            rpc.generation = "replacement"
        elif changed == "disconnected":
            rpc.connected = False
        else:
            with client.app.state.factory.begin() as db:
                task = db.get(Task, target["id"])
                if changed == "task-root":
                    task.root = str(settings.workspace)
                elif changed == "turn":
                    task.turn_id = "new-turn"
                else:
                    db.delete(db.get(WebSession, session_hash))
        return {
            "modelProvider": "openai",
            "model": "must-not-persist",
            "cwd": target["root"],
            "sandbox": {"type": "readOnly"},
            "thread": {
                "id": "existing",
                "cwd": target["root"],
                "environments": environments,
                "status": {"type": "idle"},
                "turns": [],
            },
        }

    rpc = SimpleNamespace(generation="original", connected=True, call=call)
    runtime.rpc = rpc

    async def authenticated():
        return rpc

    monkeypatch.setattr(runtime, "authenticated_rpc", authenticated)
    try:
        with pytest.raises(ConsoleError):
            await runtime.recover(target["id"], registration_session_hash=session_hash)
        with client.app.state.factory() as db:
            task = db.get(Task, target["id"])
            assert task.status == "uncertain" and task.model == "previous-model"
            assert db.get(Agent, "existing") is None
    finally:
        runtime.rpc = None


@pytest.mark.anyio
async def test_success_response_null_is_not_interpreted_as_missing_receipt(settings, monkeypatch):
    import httpx

    settings.registration_authorization_enabled = True
    settings.miy_api_origin = "https://platform.example.test"
    settings.sso_subjects = {settings.miy_api_origin: uuid4()}
    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(
            **kwargs, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=None))
        )

    monkeypatch.setattr(reg.httpx, "AsyncClient", client)
    with pytest.raises(ConsoleError, match="registration_unavailable"):
        await reg.api(settings, "/" + str(uuid4()) + "/receipt", token=TOKEN, missing=True)


@pytest.mark.parametrize("failure", ["unavailable", "unsupported"])
def test_failed_exchange_returns_to_owned_task_and_requires_explicit_reconnect(
    client, settings, target, monkeypatch, failure
):
    started = start(client, target)
    request_id = parse_qs(urlsplit(started["authorization_url"]).query)["request_id"][0]
    calls = []

    async def api(*args, **kwargs):
        calls.append(1)
        raise ConsoleError("registration_" + failure, 503 if failure == "unavailable" else 404)

    monkeypatch.setattr(reg, "api", api)
    response = client.post(
        reg.CALLBACK,
        data={"request_id": request_id, "code": CODE},
        headers={"origin": settings.miy_api_origin},
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == "/?task=" + target["id"]
    assert (
        client.get(f"/api/tasks/{target['id']}/registration").json()["authorization_state"]
        == "failed"
    )
    assert (
        client.post(
            reg.CALLBACK,
            data={"request_id": request_id, "code": CODE},
            headers={"origin": settings.miy_api_origin},
            follow_redirects=False,
        ).status_code
        == 403
    )
    assert len(calls) == 1
    assert start(client, target)["status"]["operation_id"] == started["status"]["operation_id"]
