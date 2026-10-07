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
from sqlalchemy.orm import Session

from company_admission_fixture import seed_company_app_access
from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuditLog, AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.files import selected_access, selected_storage, service as files_service
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFolder,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.independent_apps import files
from miy_api.domains.independent_apps.file_contracts import FileAuthorizeInput, FileSelectionContext
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


def test_selected_only_repeat_read_headers_and_no_root_authority(client, file_app):
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


def test_empty_selected_file_has_explicit_zero_length(client, file_app):
    with get_session_factory()() as db:
        db.get(FileManagerFile, file_app["file_id"]).size_bytes = 0
        db.commit()
    issued, _ = authorize(client, file_app)
    response = read(client, file_app, issued["read_grant"])
    assert response.status_code == 200 and response.content == b""
    assert response.headers["content-length"] == "0"


def test_other_app_session_same_user_installation_cannot_use_selected_claim(client, file_app):
    issued, proof = authorize(client, file_app)
    second = exchange(client, launch(client, file_app["headers"], file_app["installation"])).json()
    assert read(client, file_app, issued["read_grant"], token=second["token"]).status_code == 403
    assert read(client, file_app, proof["selection_request"]).status_code == 403
    assert file_app["opened"] == []


def test_host_requires_exact_original_miy_session_not_same_user_login(client, file_app):
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


@pytest.mark.parametrize(
    "boundary",
    [
        "session",
        "source_session",
        "account",
        "installation",
        "generation",
        "grant",
        "definition",
        "company",
        "files_app",
        "deleted",
        "replaced",
        "private_owner",
    ],
)
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


def test_changed_selected_version_and_missing_resource_share_access_denial(client, file_app):
    proof = prepare(client, file_app)
    listed = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"]).json()[
        "items"
    ][0]
    with get_session_factory()() as db:
        db.get(FileManagerFile, file_app["file_id"]).storage_key += "-changed"
        db.commit()
    changed = client.post(
        FILES + "/authorize-selection",
        json=proof
        | {
            "file_id": listed["file_id"],
            "expected_version": listed["version"],
        },
        headers=file_app["headers"],
    )
    missing = client.post(
        FILES + "/authorize-selection",
        json=proof
        | {
            "file_id": str(uuid4()),
            "expected_version": listed["version"],
        },
        headers=file_app["headers"],
    )
    assert changed.status_code == missing.status_code == 403
    assert (
        changed.json()["code"] == missing.json()["code"] == "independent_apps.file_access_invalid"
    )


@pytest.mark.parametrize("boundary", ["source_session", "grant", "source_acl", "replace", "expiry"])
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


def test_candidates_scan_hidden_rows_and_continue_from_last_scanned(client, file_app):
    with get_session_factory()() as db:
        original = db.get(FileManagerFile, file_app["file_id"])
        original.id = "ffffffff-ffff-4fff-afff-ffffffffffff"
        file_app["file_id"] = original.id
        for index in range(205):
            file_id = str(__import__("uuid").UUID(int=index + 1))
            db.add(
                FileManagerFile(
                    id=file_id,
                    owner_id=file_app["admin"]["user"]["id"],
                    filename="Hidden file",
                    content_type="text/plain",
                    size_bytes=1,
                    storage_key="hidden/" + file_id,
                    visibility="private",
                )
            )
        db.commit()
    proof = prepare(client, file_app)
    first = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"]).json()
    assert first["items"] == [] and first["incomplete"] and first["next_cursor"]
    second = client.post(
        FILES + "/candidates",
        json=proof | {"cursor": first["next_cursor"]},
        headers=file_app["headers"],
    ).json()
    assert [item["file_id"] for item in second["items"]] == [file_app["file_id"]]
    assert second["next_cursor"] is None and not second["incomplete"]


def test_private_parent_and_depth_limit_are_incomplete_without_disclosing_file(client, file_app):
    with get_session_factory()() as db:
        parent = None
        for _ in range(34):
            folder = FileManagerFolder(
                id=str(uuid4()),
                owner_id=file_app["owner"]["user"]["id"],
                name="Ancestor",
                visibility="private",
                parent_id=parent,
            )
            db.add(folder)
            db.flush()
            parent = folder.id
        db.get(FileManagerFile, file_app["file_id"]).folder_id = parent
        db.commit()
    proof = prepare(client, file_app)
    response = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [] and response.json()["incomplete"]
    with get_session_factory()() as db:
        db.get(FileManagerFile, file_app["file_id"]).folder_id = None
        db.commit()
    response = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"])
    assert len(response.json()["items"]) == 1 and not response.json()["incomplete"]


def test_request_body_and_versions_are_bounded_before_parsing(client, file_app):
    bad = request_payload(file_app) | {"schema_version": True}
    assert (
        client.post(
            FILES + "/selection-request", json=bad, headers=_auth_headers(file_app["token"])
        ).status_code
        == 422
    )
    response = client.post(
        FILES + "/selection-request", content=b" " * 8193, headers=_auth_headers(file_app["token"])
    )
    assert (
        response.status_code == 413
        and response.json()["code"] == "independent_apps.file_request_invalid"
    )


def test_missing_new_signing_key_disables_only_file_feature(client, file_app, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_FILE_SELECTION_SIGNING_KEY", "")
    get_settings.cache_clear()
    response = client.post(
        FILES + "/selection-request",
        json=request_payload(file_app),
        headers=_auth_headers(file_app["token"]),
    )
    assert response.status_code == 503
    assert response.json()["code"] == "independent_apps.file_picker_unavailable"
    assert (
        client.get(
            BASE + "/session",
            params={
                "installation_id": file_app["installation"]["id"],
                "audience": "https://sample.test",
            },
            headers=_auth_headers(file_app["token"]),
        ).status_code
        == 200
    )


@pytest.mark.parametrize("kind", ["hidden", "deleted", "cycle"])
def test_native_ancestor_denial_matches_original_files_acl(client, file_app, kind):
    with get_session_factory()() as db:
        folder = FileManagerFolder(
            id=str(uuid4()),
            owner_id=file_app["admin"]["user"]["id"]
            if kind == "hidden"
            else file_app["owner"]["user"]["id"],
            name="Hidden ancestor",
            visibility="private",
            deleted_at=utcnow_naive() if kind == "deleted" else None,
        )
        db.add(folder)
        db.flush()
        if kind == "cycle":
            folder.parent_id = folder.id
        db.get(FileManagerFile, file_app["file_id"]).folder_id = folder.id
        db.commit()
        owner = db.get(User, file_app["owner"]["user"]["id"])
        with pytest.raises(HTTPException):
            files_service.require_file_access(db, user=owner, file_id=file_app["file_id"])
        with pytest.raises(selected_access.SelectedFileDenied):
            selected_access.selected_file(db, user_id=owner.id, file_id=file_app["file_id"])
    proof = prepare(client, file_app)
    response = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"])
    assert response.status_code == 200
    assert response.json()["items"] == [] and not response.json()["incomplete"]


@pytest.mark.parametrize(
    "policy", ["cohort", "user", "company", "unresolved", "empty", "missing", "different_user"]
)
def test_company_corpus_policy_matches_original_source_and_current_grant(client, file_app, policy):
    created = client.post(
        "/api/v1/files/corpora",
        headers=_auth_headers(file_app["admin"]["token"]),
        json={"name": "Synthetic corpus"},
    )
    assert created.status_code == 201, created.text
    corpus_id = created.json()["id"]
    with get_session_factory()() as db:
        corpus = db.get(FileManagerCorpus, corpus_id)
        file = db.get(FileManagerFile, file_app["file_id"])
        file.corpus_id = corpus_id
        if policy != "cohort":
            corpus.source_managed = True
            corpus.authorization_mode = "explicit_grants"
            if policy != "missing":
                db.add(
                    FileManagerFileSourceMetadata(
                        file_id=file.id,
                        corpus_id=corpus_id,
                        external_id="synthetic",
                        external_id_sha256="1" * 64,
                        source_kind="synthetic",
                        source_id="synthetic",
                        source_id_sha256="2" * 64,
                        content_checksum="3" * 64,
                        acl_resolved=policy != "unresolved",
                    )
                )
            if policy in {"user", "company", "unresolved", "different_user"}:
                db.add(
                    FileManagerFileAccessGrant(
                        id=str(uuid4()),
                        file_id=file.id,
                        grant_key="synthetic",
                        grant_type="company" if policy == "company" else "user",
                        target_id=None
                        if policy == "company"
                        else file_app["admin" if policy == "different_user" else "owner"]["user"][
                            "id"
                        ],
                    )
                )
        db.commit()
        owner = db.get(User, file_app["owner"]["user"]["id"])
        permitted = policy in {"cohort", "user", "company"}
        if permitted:
            assert files_service.require_file_access(db, user=owner, file_id=file.id).id == file.id
            assert (
                selected_access.selected_file(db, user_id=owner.id, file_id=file.id).file_id
                == file.id
            )
        else:
            with pytest.raises(HTTPException):
                files_service.require_file_access(db, user=owner, file_id=file.id)
            with pytest.raises(selected_access.SelectedFileDenied):
                selected_access.selected_file(db, user_id=owner.id, file_id=file.id)
        # Existing company-corpus admin read remains source policy, not a new
        # override for native personal files (covered separately).
        assert (
            selected_access.selected_file(
                db, user_id=file_app["admin"]["user"]["id"], file_id=file.id
            ).file_id
            == file.id
        )
    proof = prepare(client, file_app)
    listed = client.post(FILES + "/candidates", json=proof, headers=file_app["headers"]).json()
    assert bool(listed["items"]) == permitted
    if policy == "user":
        issued, _ = authorize(client, file_app, proof)
        with get_session_factory()() as db:
            db.delete(
                db.scalar(
                    select(FileManagerFileAccessGrant).where(
                        FileManagerFileAccessGrant.file_id == file_app["file_id"]
                    )
                )
            )
            db.commit()
        assert read(client, file_app, issued["read_grant"]).status_code == 403
        assert file_app["opened"] == []


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_new_control_surface_rejects_stale_or_nontransactional_snapshot(
    client, file_app, isolation
):
    factory = get_session_factory()
    engine = factory.kw["bind"]
    with engine.connect().execution_options(isolation_level=isolation) as connection:
        with Session(connection) as db:
            if isolation != "AUTOCOMMIT":
                db.execute(text("SELECT 1"))
            with pytest.raises(HTTPException) as caught:
                files.selection_request(
                    db,
                    FileSelectionContext.model_validate(request_payload(file_app)),
                    token=file_app["token"],
                )
            assert caught.value.status_code == 403


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


def test_installed_snapshot_cannot_gain_new_permission_from_current_definition(client, file_app):
    from test_independent_app_delivery import build_release

    app = file_app
    previous = client.put(
        BASE + "/definitions",
        headers=app["headers"],
        json={
            "definition": manifest(),
            "source_revision": "b" * 40,
            "expected_digest": app["definition"]["definition_digest"],
            "expected_source_revision": "a" * 40,
        },
    )
    assert previous.status_code == 200, previous.text
    release_id = build_release(previous.json(), revision="b" * 40)
    updated = client.put(
        BASE + "/definitions",
        headers=app["headers"],
        json={
            "definition": manifest() | {"requested_permissions": PERMISSIONS},
            "source_revision": "c" * 40,
            "expected_digest": previous.json()["definition_digest"],
            "expected_source_revision": "b" * 40,
        },
    )
    assert updated.status_code == 200, updated.text
    with get_session_factory()() as db:
        install = db.get(AppInstallationRecord, app["installation"]["id"])
        install.release_id = release_id
        install.state = "ready"
        db.commit()
    response = client.post(
        FILES + "/selection-request", json=request_payload(app), headers=_auth_headers(app["token"])
    )
    assert response.status_code == 403, response.text


def test_picker_search_treats_percent_as_literal_and_key_rotation_revokes_claim(
    client, file_app, monkeypatch
):
    proof = prepare(client, file_app)
    assert (
        client.post(
            FILES + "/candidates", json=proof | {"query": "%"}, headers=file_app["headers"]
        ).json()["items"]
        == []
    )
    issued, _ = authorize(client, file_app, proof)
    monkeypatch.setenv("MIY_INDEPENDENT_APP_FILE_SELECTION_SIGNING_KEY", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    assert read(client, file_app, issued["read_grant"]).status_code == 403
    assert file_app["opened"] == []
