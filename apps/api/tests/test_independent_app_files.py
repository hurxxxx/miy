from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
import secrets
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text

from company_admission_fixture import seed_company_app_access
from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuditLog, AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.files import selected_storage
from miy_api.domains.files.models import (
    FileManagerFile,
)
from miy_api.domains.independent_apps import files
from miy_api.domains.independent_apps.file_contracts import FileAuthorizeInput
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppSession,
)
from test_independent_app_bootstrap import context, other_owner
from test_independent_apps import exchange, launch, manifest
from test_organization_integrations import _auth_headers, _bootstrap_admin

BASE = "/api/v1/independent-apps"
FILES = BASE + "/_files"
PERMISSIONS = ["identity:read", "files:read-selected"]


@pytest.fixture
def file_app(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    monkeypatch.setenv("MIY_INDEPENDENT_APP_FILE_SELECTION_SIGNING_KEY", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    owner = other_owner()
    headers = _auth_headers(owner["token"])
    definition = client.put(
        BASE + "/definitions",
        headers=headers,
        json={
            "definition": manifest() | {"requested_permissions": PERMISSIONS},
            "source_revision": "a" * 40,
        },
    )
    assert definition.status_code == 200, definition.text
    result = client.post(
        BASE + "/sample-independent/installations",
        headers=headers,
        json={
            "environment": "development",
            "origin": "https://sample.test",
            "enabled": True,
            "user_ids": [owner["user"]["id"]],
            "granted_permissions": PERMISSIONS,
        },
    )
    assert result.status_code == 201, result.text
    installation = result.json()
    session = exchange(client, launch(client, headers, installation))
    assert session.status_code == 200, session.text
    with get_session_factory()() as db:
        seed_company_app_access(db, ("files",))
        file_id = str(uuid4())
        db.add(
            FileManagerFile(
                id=file_id,
                owner_id=owner["user"]["id"],
                filename="Selected synthetic file.txt",
                content_type="text/plain",
                size_bytes=4,
                storage_key="synthetic/" + file_id,
                visibility="private",
            )
        )
        db.commit()
    opened = []

    async def read(config, *, storage_key, expected_size):
        opened.append((storage_key, expected_size))
        return b"data" if expected_size else b""

    monkeypatch.setattr(selected_storage, "read_selected_object", read)
    yield {
        "owner": owner,
        "admin": admin,
        "headers": headers,
        "installation": installation,
        "token": session.json()["token"],
        "file_id": file_id,
        "opened": opened,
        "definition": definition.json(),
    }
    get_settings.cache_clear()


def request_payload(app):
    return {
        "schema_version": 1,
        "installation_id": app["installation"]["id"],
        "audience": "https://sample.test",
        "selection_id": str(uuid4()),
    }


def prepare(client, app):
    payload = request_payload(app)
    response = client.post(
        FILES + "/selection-request", json=payload, headers=_auth_headers(app["token"])
    )
    assert response.status_code == 200, response.text
    return payload | {"selection_request": response.json()["selection_request"]}


def authorize(client, app, proof=None):
    proof = proof or prepare(client, app)
    response = client.post(FILES + "/candidates", json=proof, headers=app["headers"])
    assert response.status_code == 200, response.text
    file = next(row for row in response.json()["items"] if row["file_id"] == app["file_id"])
    result = client.post(
        FILES + "/authorize-selection",
        json=proof
        | {
            "file_id": file["file_id"],
            "expected_version": file["version"],
        },
        headers=app["headers"],
    )
    assert result.status_code == 200, result.text
    return result.json(), proof


def read(client, app, grant, *, token=None):
    return client.get(
        FILES + "/content",
        params={
            "installation_id": app["installation"]["id"],
            "audience": "https://sample.test",
        },
        headers=_auth_headers(token or app["token"]) | {"X-MIY-Selected-File": grant},
    )


@pytest.mark.parametrize("boundary", ["source_session"])
def test_live_revocation_before_read_denies_without_opening_storage(client, file_app, boundary):
    issued, _ = authorize(client, file_app)
    with get_session_factory()() as db:
        session = db.get(AppSession, hash_token(file_app["token"]))
        install = db.get(AppInstallationRecord, session.installation_id)
        file = db.get(FileManagerFile, file_app["file_id"])
        if boundary == "session":
            session.revoked_at = utcnow_naive()
        elif boundary == "source_session":
            db.get(AuthSession, session.source_session_id).revoked_at = utcnow_naive()
        elif boundary == "account":
            db.get(User, file_app["owner"]["user"]["id"]).login_blocked = True
        elif boundary == "installation":
            install.enabled = False
        elif boundary == "generation":
            install.generation += 1
        elif boundary == "grant":
            install.granted_permissions = ["identity:read"]
        elif boundary == "definition":
            definition = db.get(AppDefinitionRecord, install.app_id)
            definition.manifest = definition.manifest | {"requested_permissions": ["identity:read"]}
        elif boundary == "company":
            db.get(CompanyAppControl, install.app_id).enabled = False
        elif boundary == "files_app":
            db.get(CompanyAppControl, "files").enabled = False
        elif boundary == "deleted":
            file.deleted_at = utcnow_naive()
        elif boundary == "replaced":
            file.storage_key += "-replacement"
        elif boundary == "private_owner":
            file.owner_id = file_app["admin"]["user"]["id"]
        db.commit()
    assert read(client, file_app, issued["read_grant"]).status_code in {401, 403}
    assert file_app["opened"] == []


@pytest.mark.parametrize("boundary", ["replace"])
def test_whole_body_is_not_returned_when_authority_changes_during_io(
    client, file_app, monkeypatch, boundary
):
    issued, _ = authorize(client, file_app)

    async def changed(config, *, storage_key, expected_size):
        with get_session_factory()() as db:
            app = db.get(AppSession, hash_token(file_app["token"]))
            if boundary == "source_session":
                db.get(AuthSession, app.source_session_id).revoked_at = utcnow_naive()
            elif boundary == "grant":
                db.get(AppInstallationRecord, app.installation_id).granted_permissions = [
                    "identity:read"
                ]
            elif boundary == "source_acl":
                db.get(FileManagerFile, file_app["file_id"]).owner_id = file_app["admin"]["user"][
                    "id"
                ]
            elif boundary == "replace":
                db.get(FileManagerFile, file_app["file_id"]).storage_key += "-changed"
            elif boundary == "expiry":
                app.expires_at = utcnow_naive() - timedelta(seconds=1)
            db.commit()
        return b"data"

    monkeypatch.setattr(selected_storage, "read_selected_object", changed)
    response = read(client, file_app, issued["read_grant"])
    assert response.status_code in {401, 403}
    assert response.content != b"data"


def test_live_source_session_revoked_while_audit_insert_waits_rolls_back_approval(client, file_app):
    proof = prepare(client, file_app)
    listed = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"]).json()[
        "items"
    ][0]
    data = FileAuthorizeInput.model_validate(
        proof | {"file_id": listed["file_id"], "expected_version": listed["version"]}
    )
    factory = get_session_factory()
    engine = factory.kw["bind"]
    started = Event()
    state = {}

    def approve():
        with factory() as db:
            actor = context(db, file_app["owner"])
            state["pid"] = db.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            with pytest.raises(HTTPException) as caught:
                files.authorize(db, data, actor)
            assert caught.value.status_code == 401

    with engine.connect() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute(text("LOCK TABLE audit_logs IN SHARE MODE"))
        future = pool.submit(approve)
        assert started.wait(2)
        deadline = time.monotonic() + 0.8
        with engine.connect() as observer:
            while not observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": state["pid"]}
            ):
                assert time.monotonic() < deadline
                time.sleep(0.005)
        with factory() as db:
            session = db.get(AppSession, hash_token(file_app["token"]))
            db.get(AuthSession, session.source_session_id).revoked_at = utcnow_naive()
            db.commit()
        blocker.commit()
        future.result(timeout=2)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "independent_app.file.selected")
            )
            == 0
        )


def test_selected_claim_stays_bound_to_original_app_and_source_session(client, file_app):
    app = file_app
    issued, _ = authorize(client, app)
    assert set(issued["file"]) == {"file_id", "name", "content_type", "size_bytes", "version"}
    assert len(issued["file"]["version"]) == 64
    for _ in range(2):
        response = read(client, app, issued["read_grant"])
        assert response.status_code == 200, response.text
        assert response.content == b"data"
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-length"] == "4"
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["content-disposition"].startswith("attachment;")
    assert len(app["opened"]) == 2
    assert client.get("/api/v1/files", headers=_auth_headers(app["token"])).status_code == 401
    assert (
        client.get(
            "/api/v1/content",
            headers=_auth_headers(app["token"])
            | {
                "X-MIY-Content-Grant": issued["read_grant"],
            },
        ).status_code
        == 403
    )
    assert read(client, app, issued["read_grant"], token=app["owner"]["token"]).status_code == 401
    assert (
        read(client, app, issued["read_grant"], token=hash_token(app["token"])).status_code == 401
    )
    second = exchange(client, launch(client, file_app["headers"], file_app["installation"])).json()
    opened = len(file_app["opened"])
    assert read(client, file_app, issued["read_grant"], token=second["token"]).status_code == 403
    assert len(file_app["opened"]) == opened
    proof = prepare(client, file_app)
    replacement = secrets.token_urlsafe(32)
    with get_session_factory()() as db:
        db.add(
            AuthSession(
                id=str(uuid4()),
                user_id=file_app["owner"]["user"]["id"],
                token_hash=hash_token(replacement),
                expires_at=utcnow_naive() + timedelta(hours=1),
            )
        )
        db.commit()
    assert (
        client.post(
            FILES + "/candidates", json=proof, headers=_auth_headers(replacement)
        ).status_code
        == 403
    )
    assert (
        client.post(
            FILES + "/candidates", json=proof, headers=_auth_headers(file_app["admin"]["token"])
        ).status_code
        == 403
    )
    assert (
        client.post(
            FILES + "/candidates", json=proof, headers=_auth_headers(file_app["token"])
        ).status_code
        == 401
    )
