from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Event
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuditLog, CompanyAppControl, User, utcnow_naive
from miy_api.domains.independent_apps import data_api, delivery, owner_preview, service
from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppBuildVerification,
    AppDeploymentRequest,
)
from miy_api.domains.independent_apps.models import (
    AppDefinitionRecord,
    AppInstallationRecord,
    AppReleaseRecord,
)
from miy_api.domains.independent_apps.owner_preview_contracts import OwnerPreviewPatch
from test_independent_app_bootstrap import context, other_owner, payload, post
from test_independent_app_delivery import FakeRuntime
from test_organization_integrations import _auth_headers, _bootstrap_admin

BASE = "/api/v1/independent-apps"
AUDIT = "independent_app.owner_preview.configure"


@pytest.fixture
def preview(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    member = other_owner()
    created = post(client, member, payload(granted_permissions=[]))
    assert created.status_code == 201, created.text
    receipt = created.json()
    url = f"{BASE}/{receipt['app_id']}/installations/{receipt['installation_id']}/owner-preview"
    yield member, admin, receipt, url
    get_settings.cache_clear()


def read(client, preview):
    member, _, _, url = preview
    return client.get(url, headers=_auth_headers(member["token"]))


def patch_data(snapshot, **changes):
    return {
        "expected_generation": snapshot["generation"],
        "expected_definition_digest": snapshot["definition_digest"],
        "expected_source_revision": snapshot["source_revision"],
        "enabled": True,
        "granted_permissions": ["identity:read"],
    } | changes


def patch(client, preview, data):
    member, _, _, url = preview
    return client.patch(url, headers=_auth_headers(member["token"]), json=data)


def audit_count(db):
    return db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == AUDIT))


def unchanged(receipt):
    with get_session_factory()() as db:
        installation = db.get(AppInstallationRecord, receipt["installation_id"])
        assert (
            installation.generation,
            installation.enabled,
            installation.granted_permissions,
        ) == (
            1,
            False,
            [],
        )
        assert audit_count(db) == 0


def configure(db, preview, data):
    member, _, receipt, _ = preview
    return owner_preview.configure(
        db,
        receipt["app_id"],
        receipt["installation_id"],
        OwnerPreviewPatch.model_validate(data),
        context(db, member),
        platform_origin="https://platform.test",
    )


def test_current_snapshot_enable_lost_response_noop_and_original_receipt_preserved(client, preview):
    member, _, receipt, _ = preview
    first = read(client, preview)
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    snapshot = first.json()
    assert set(snapshot) == {
        "schema_version",
        "app_id",
        "installation_id",
        "owner_user_id",
        "display_name",
        "origin",
        "generation",
        "definition_digest",
        "source_revision",
        "runtime_profile",
        "requested_permissions",
        "granted_permissions",
        "enabled",
        "company_enabled",
        "can_configure",
        "unavailable_reason",
    }
    assert snapshot["owner_user_id"] == member["user"]["id"]
    assert snapshot["can_configure"] and snapshot["company_enabled"]
    assert snapshot["unavailable_reason"] is None and not snapshot["enabled"]
    with get_session_factory()() as db:
        original = db.get(AppInstallationRecord, receipt["installation_id"])
        fixed = (
            original.environment,
            original.origin,
            original.audience,
            original.user_ids,
            original.group_ids,
            original.release_id,
            original.runtime_ref,
        )
    assert patch(client, preview, patch_data(snapshot)).status_code == 200
    # The response was not retained. Read current state; do not replay a mutation.
    current = read(client, preview).json()
    assert current["generation"] == 2 and current["enabled"]
    assert current["granted_permissions"] == ["identity:read"]
    assert patch(client, preview, patch_data(snapshot)).status_code == 409
    assert patch(client, preview, patch_data(current)).json() == current
    with get_session_factory()() as db:
        install = db.get(AppInstallationRecord, receipt["installation_id"])
        assert fixed == (
            install.environment,
            install.origin,
            install.audience,
            install.user_ids,
            install.group_ids,
            install.release_id,
            install.runtime_ref,
        )
        assert install.state == "configured" and audit_count(db) == 1
        audit = db.scalar(select(AuditLog).where(AuditLog.action == AUDIT))
        assert audit.actor_user_id == member["user"]["id"]
        assert audit.payload == {
            "app_id": receipt["app_id"],
            "installation_id": receipt["installation_id"],
            "definition_digest": receipt["definition_digest"],
            "source_revision": receipt["source_revision"],
            "before": {"generation": 1, "enabled": False, "granted_permissions": []},
            "after": {"generation": 2, "enabled": True, "granted_permissions": ["identity:read"]},
        }
    old = client.get(
        BASE + "/bootstrap/" + receipt["operation_id"], headers=_auth_headers(member["token"])
    )
    assert old.json() == receipt
    catalog = client.get(BASE + "/catalog", headers=_auth_headers(member["token"])).json()
    assert catalog["items"][0]["installations"][0]["launchable"]


@pytest.mark.parametrize(
    "actor", ["admin", "no_auth", "metadata", "registration", "app", "delivery"]
)
def test_other_admin_and_non_login_credentials_never_gain_owner_authority(client, preview, actor):
    _, admin, receipt, url = preview
    data = patch_data(read(client, preview).json())
    headers = (
        {}
        if actor == "no_auth"
        else _auth_headers(
            admin["token"] if actor == "admin" else f"miy-{actor}-synthetic-not-login"
        )
    )
    expected = 404 if actor == "admin" else 401
    assert client.get(url, headers=headers).status_code == expected
    assert client.patch(url, headers=headers, json=data).status_code == expected
    unchanged(receipt)


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://changed.test"},
        {"environment": "production"},
        {"audience": "all"},
        {"user_ids": []},
        {"source_revision": "b" * 40},
        {"release_id": str(uuid4())},
        {"runtime_ref": "changed"},
        {"expected_generation": True},
        {"expected_generation": 1.0},
        {"expected_generation": 0},
        {"enabled": "true"},
        {"granted_permissions": ["identity:read", "identity:read"]},
        {"granted_permissions": ["platform:admin"]},
    ],
)
def test_patch_rejects_unowned_fields_and_coercive_inputs(client, preview, change):
    assert (
        patch(client, preview, patch_data(read(client, preview).json(), **change)).status_code
        == 422
    )
    unchanged(preview[2])


def test_unrequested_known_permission_is_denied(client, preview):
    data = patch_data(read(client, preview).json(), granted_permissions=["data:write"])
    assert patch(client, preview, data).status_code == 403
    unchanged(preview[2])


@pytest.mark.parametrize(
    "boundary", ["official", "production", "broadcast", "other_user", "duplicate_owner", "group"]
)
def test_legacy_non_self_boundaries_are_not_normalized_by_owner_preview(client, preview, boundary):
    member, admin, receipt, _ = preview
    data = patch_data(read(client, preview).json())
    with get_session_factory()() as db:
        install = db.get(AppInstallationRecord, receipt["installation_id"])
        if boundary == "official":
            definition = db.get(AppDefinitionRecord, receipt["app_id"])
            definition.manifest = dict(definition.manifest, ownership="official")
        elif boundary == "production":
            install.environment = "production"
        elif boundary == "broadcast":
            install.audience = "all"
        elif boundary == "other_user":
            install.user_ids = [member["user"]["id"], admin["user"]["id"]]
        elif boundary == "duplicate_owner":
            install.user_ids = [member["user"]["id"]] * 2
        else:
            install.group_ids = ["legacy-group"]
        db.commit()
    assert read(client, preview).status_code == 404
    assert patch(client, preview, data).status_code == 404
    unchanged(receipt)


def test_impersonated_owner_is_refused_even_with_live_admin(client, preview):
    member, admin, receipt, _ = preview
    data = patch_data(read(client, preview).json())
    with get_session_factory()() as db:
        context(db, member).session.impersonator_user_id = admin["user"]["id"]
        db.commit()
    assert read(client, preview).status_code == 403
    assert patch(client, preview, data).status_code == 403
    unchanged(receipt)


def release(db, receipt):
    definition = db.get(AppDefinitionRecord, receipt["app_id"])
    value = AppReleaseRecord(
        id=str(uuid4()),
        app_id=definition.app_id,
        definition_digest=definition.definition_digest,
        definition_snapshot=definition.manifest,
        source_revision=definition.source_revision,
        artifact="sha256:" + "f" * 64,
    )
    db.add(value)
    db.flush()
    return value


@pytest.mark.parametrize(
    "reason",
    [
        "release",
        "runtime",
        "ready",
        "delivery_queued",
        "delivery_running",
        "delivery_unknown",
        "delivery_cleanup",
        "build_queued",
        "build_running",
        "build_unknown",
        "build_cleanup",
        "build_future",
        "verified",
        "company",
        "origins_missing",
        "same_origin",
        "malformed_origin",
    ],
)
def test_non_initial_or_blocked_configuration_is_read_only(client, preview, monkeypatch, reason):
    member, _, receipt, _ = preview
    data = patch_data(read(client, preview).json())
    expected = "already_deployed"
    with get_session_factory()() as db:
        install = db.get(AppInstallationRecord, receipt["installation_id"])
        if reason == "release":
            install.release_id = release(db, receipt).id
        elif reason == "runtime":
            install.runtime_ref = str(uuid4())
        elif reason == "ready":
            install.state = "ready"
        elif reason.startswith("delivery_"):
            source = context(db, member)
            db.add(
                AppDeploymentRequest(
                    id=str(uuid4()),
                    actor_user_id=source.user.id,
                    source_session_id=source.session.id,
                    installation_id=install.id,
                    release_id=release(db, receipt).id,
                    action="deploy",
                    request_hash="a" * 64,
                    expected_generation=1,
                    state=reason.removeprefix("delivery_"),
                )
            )
            expected = "delivery_in_progress"
        elif reason.startswith("build_") or reason == "verified":
            job = AppBuildJob(
                id=str(uuid4()),
                app_id=receipt["app_id"],
                source_revision=receipt["source_revision"],
                definition_digest=receipt["definition_digest"],
                state="succeeded" if reason == "verified" else reason.removeprefix("build_"),
            )
            db.add(job)
            db.flush()
            expected = "build_in_progress"
            if reason == "verified":
                db.add(
                    AppBuildVerification(
                        id=str(uuid4()),
                        build_job_id=job.id,
                        app_id=job.app_id,
                        source_revision=job.source_revision,
                        definition_digest=job.definition_digest,
                        source_archive_sha256="a" * 64,
                        artifact_digest="sha256:" + "b" * 64,
                        builder_profile_digest="sha256:" + "c" * 64,
                        target_environment="development",
                        checks={"test": 0},
                    )
                )
                expected = "already_verified"
        elif reason == "company":
            db.get(CompanyAppControl, receipt["app_id"]).enabled = False
            expected = "company_disabled"
        elif reason == "origins_missing":
            monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", "[]")
            get_settings.cache_clear()
            expected = "origin_configuration_required"
        else:
            install.origin = (
                "https://platform.test" if reason == "same_origin" else "https://broken.test/path"
            )
            expected = "invalid_origin"
        db.commit()
    current = read(client, preview)
    assert current.status_code == 200, current.text
    assert current.json()["unavailable_reason"] == expected and not current.json()["can_configure"]
    assert patch(client, preview, data).status_code == 409
    unchanged(receipt)


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_controls_require_read_committed_and_transaction(client, preview, isolation):
    member, _, receipt, _ = preview
    data = patch_data(read(client, preview).json())
    with (
        get_session_factory()()
        .get_bind()
        .connect()
        .execution_options(isolation_level=isolation) as connection
    ):
        with Session(connection) as db:
            with pytest.raises(HTTPException) as error:
                configure(db, preview, data)
            assert error.value.status_code == 403
            with pytest.raises(HTTPException) as error:
                owner_preview.read(
                    db,
                    receipt["app_id"],
                    receipt["installation_id"],
                    context(db, member),
                    platform_origin="https://platform.test",
                )
            assert error.value.status_code == 403
    unchanged(receipt)


def test_concurrent_generation_has_one_winner_and_no_duplicate_audit(client, preview):
    data = patch_data(read(client, preview).json())
    start = Event()

    def change():
        with get_session_factory()() as db:
            assert start.wait(5)
            try:
                return configure(db, preview, data).generation
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change) for _ in range(2)]
        start.set()
        assert sorted(future.result(timeout=10) for future in futures) == [2, 409]
    with get_session_factory()() as db:
        assert audit_count(db) == 1


@pytest.mark.parametrize("change", ["session", "account", "source", "definition"])
def test_current_authority_and_definition_are_rechecked_after_real_lock_wait(
    client, preview, change
):
    member, _, receipt, _ = preview
    data = OwnerPreviewPatch.model_validate(patch_data(read(client, preview).json()))
    ready = Event()
    pids = []

    def writer():
        with get_session_factory()() as db:
            actor = context(db, member)
            pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            try:
                owner_preview.configure(
                    db,
                    receipt["app_id"],
                    receipt["installation_id"],
                    data,
                    actor,
                    platform_origin="https://platform.test",
                )
                return 200
            except HTTPException as exc:
                return exc.status_code

    with get_session_factory()() as blocker:
        definition = blocker.scalar(
            select(AppDefinitionRecord)
            .where(AppDefinitionRecord.app_id == receipt["app_id"])
            .with_for_update()
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            try:
                assert ready.wait(5)
                with get_session_factory()() as revoker:
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        if revoker.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pids[0]}
                        ):
                            break
                    else:
                        pytest.fail("Writer did not reach PostgreSQL lock")
                    if change == "session":
                        context(revoker, member).session.revoked_at = utcnow_naive()
                    elif change == "account":
                        revoker.get(User, member["user"]["id"]).login_blocked = True
                    elif change == "source":
                        definition.source_revision = "b" * 40
                    else:
                        manifest = AppDefinition.model_validate(
                            definition.manifest | {"requested_permissions": []}
                        )
                        definition.manifest = manifest.model_dump(mode="json")
                        definition.definition_digest = manifest.content_digest()
                    revoker.commit()
            finally:
                blocker.commit()
            assert future.result(timeout=10) == (
                409 if change in {"source", "definition"} else 401 if change == "session" else 403
            )
    unchanged(receipt)


@pytest.mark.parametrize("revocation", ["session", "account", "company"])
def test_postflush_revoke_rolls_back_configuration_and_audit(client, preview, revocation):
    member, _, receipt, _ = preview
    data = patch_data(read(client, preview).json())

    def revoke(db, flush_context):
        with get_session_factory()() as revoker:
            if revocation == "session":
                context(revoker, member).session.revoked_at = utcnow_naive()
            elif revocation == "account":
                revoker.get(User, member["user"]["id"]).login_blocked = True
            else:
                revoker.get(CompanyAppControl, receipt["app_id"]).enabled = False
            revoker.commit()

    with get_session_factory()() as db:
        event.listen(db, "after_flush_postexec", revoke, once=True)
        with pytest.raises(HTTPException) as error:
            configure(db, preview, data)
        assert error.value.status_code in {401, 403, 409}
    unchanged(receipt)


def test_real_lock_timeout_rolls_back_and_restores_local_setting(client, preview, monkeypatch):
    receipt = preview[2]
    data = patch_data(read(client, preview).json())
    monkeypatch.setattr(owner_preview, "LOCK_TIMEOUT_MS", 150)
    with get_session_factory()() as blocker:
        blocker.scalar(
            select(AppInstallationRecord)
            .where(AppInstallationRecord.id == receipt["installation_id"])
            .with_for_update()
        )
        started = monotonic()
        response = patch(client, preview, data)
        assert monotonic() - started < 3
        assert response.status_code == 503
        assert response.json()["code"] == "independent_apps.preview_busy"
        assert "SELECT" not in response.text
        with get_session_factory()() as db:
            prior = db.scalar(text("SHOW lock_timeout"))
            with pytest.raises(HTTPException):
                configure(db, preview, data)
            assert db.scalar(text("SHOW lock_timeout")) == prior
    unchanged(receipt)


def test_unrelated_database_error_is_not_hidden(client, preview):
    from sqlalchemy.exc import ProgrammingError

    data = patch_data(read(client, preview).json())

    def fail(db, flush_context):
        db.execute(text("SELECT * FROM owner_preview_missing_fixture_relation"))

    with get_session_factory()() as db:
        event.listen(db, "after_flush_postexec", fail, once=True)
        with pytest.raises(ProgrammingError) as error:
            configure(db, preview, data)
        assert error.value.orig.sqlstate == "42P01"
    unchanged(preview[2])


def test_noop_keeps_sessions_but_real_change_revokes_launches_and_sessions(client, preview):
    member, _, receipt, _ = preview
    first = patch(client, preview, patch_data(read(client, preview).json())).json()
    headers = _auth_headers(member["token"])
    verifier = "v" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    launch_body = {"installation_id": receipt["installation_id"], "code_challenge": challenge}
    first_code = client.post(BASE + "/launch", headers=headers, json=launch_body).json()["code"]
    second_code = client.post(BASE + "/launch", headers=headers, json=launch_body).json()["code"]
    exchange_body = {
        "installation_id": receipt["installation_id"],
        "code": first_code,
        "code_verifier": verifier,
    }
    app_token = client.post(
        BASE + "/exchange", headers={"Origin": first["origin"]}, json=exchange_body
    ).json()["token"]
    assert patch(client, preview, patch_data(first)).json() == first
    with get_session_factory()() as db:
        assert (
            service.app_identity(
                db,
                token=app_token,
                installation_id=receipt["installation_id"],
                audience=first["origin"],
            ).user_id
            == member["user"]["id"]
        )
    changed = patch(client, preview, patch_data(first, enabled=False)).json()
    assert changed["generation"] == 3 and not changed["enabled"]
    assert (
        client.post(
            BASE + "/exchange",
            headers={"Origin": first["origin"]},
            json=exchange_body | {"code": second_code},
        ).status_code
        == 401
    )
    with get_session_factory()() as db:
        with pytest.raises(HTTPException) as error:
            service.app_identity(
                db,
                token=app_token,
                installation_id=receipt["installation_id"],
                audience=first["origin"],
            )
        assert error.value.status_code == 401


def test_late_queue_waits_on_fk_then_old_generation_fails_before_runtime_work(client, preview):
    member, _, receipt, _ = preview
    data = patch_data(read(client, preview).json())
    with get_session_factory()() as db:
        release_id = release(db, receipt).id
        session_id = context(db, member).session.id
        db.commit()
    request_id = str(uuid4())
    held, finish, queue_started = Event(), Event(), Event()
    pids = []

    def hold_after_flush(db, flush_context):
        held.set()
        assert finish.wait(5)

    def configure_settings():
        with get_session_factory()() as db:
            event.listen(db, "after_flush_postexec", hold_after_flush, once=True)
            return configure(db, preview, data).generation

    def queue():
        with get_session_factory()() as db:
            pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            db.add(
                AppDeploymentRequest(
                    id=request_id,
                    actor_user_id=member["user"]["id"],
                    source_session_id=session_id,
                    installation_id=receipt["installation_id"],
                    release_id=release_id,
                    action="deploy",
                    request_hash="b" * 64,
                    expected_generation=1,
                    state="queued",
                )
            )
            queue_started.set()
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        settings_future = pool.submit(configure_settings)
        assert held.wait(5)
        queue_future = pool.submit(queue)
        try:
            assert queue_started.wait(5)
            with get_session_factory()() as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    if observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pids[0]}
                    ):
                        break
                else:
                    pytest.fail("Late queue did not wait on the installation FK lock")
            assert not queue_future.done()
        finally:
            finish.set()
        assert settings_future.result(timeout=10) == 2
        queue_future.result(timeout=10)
    runtime = FakeRuntime()
    with get_session_factory()() as db:
        result = delivery.execute_deployment(db, request_id, runtime)
        assert (result.state, result.failure_code) == ("failed", "authority_changed")
    assert runtime.active is None and runtime.candidates == {} and runtime.activations == []


@pytest.mark.parametrize("state", ["failed", "succeeded"])
def test_terminal_build_without_live_verification_does_not_block_initial_setup(
    client, preview, state
):
    receipt = preview[2]
    with get_session_factory()() as db:
        db.add(
            AppBuildJob(
                id=str(uuid4()),
                app_id=receipt["app_id"],
                source_revision=receipt["source_revision"],
                definition_digest=receipt["definition_digest"],
                state=state,
            )
        )
        db.commit()
    snapshot = read(client, preview).json()
    assert snapshot["can_configure"]
    assert patch(client, preview, patch_data(snapshot)).status_code == 200


def test_data_permissions_are_explicit_and_do_not_assert_installed_data_release(client, preview):
    member, _, receipt, _ = preview
    with get_session_factory()() as db:
        definition = db.get(AppDefinitionRecord, receipt["app_id"])
        manifest = AppDefinition.model_validate(
            definition.manifest
            | {
                "runtime_profile": "web-api-postgres-v1",
                "requested_permissions": ["identity:read", "data:read", "data:write"],
            }
        )
        definition.manifest = manifest.model_dump(mode="json")
        definition.definition_digest = manifest.content_digest()
        db.commit()
    snapshot = read(client, preview).json()
    assert snapshot["runtime_profile"] == "web-api-postgres-v1"
    grants = ["identity:read", "data:write", "data:read"]
    response = patch(client, preview, patch_data(snapshot, granted_permissions=grants))
    assert response.status_code == 200, response.text
    assert response.json()["granted_permissions"] == sorted(grants)
    assert (
        patch(
            client, preview, patch_data(response.json(), granted_permissions=list(reversed(grants)))
        ).json()
        == response.json()
    )
    verifier = "v" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    code = client.post(
        BASE + "/launch",
        headers=_auth_headers(member["token"]),
        json={"installation_id": receipt["installation_id"], "code_challenge": challenge},
    ).json()["code"]
    token = client.post(
        BASE + "/exchange",
        headers={"Origin": snapshot["origin"]},
        json={
            "installation_id": receipt["installation_id"],
            "code": code,
            "code_verifier": verifier,
        },
    ).json()["token"]
    with get_session_factory()() as db:
        with pytest.raises(HTTPException) as error:
            data_api.identity(
                installation_id=receipt["installation_id"],
                audience=snapshot["origin"],
                authorization="Bearer " + token,
                db=db,
            )
        assert error.value.status_code == 403
        assert audit_count(db) == 1
        installation = db.get(AppInstallationRecord, receipt["installation_id"])
        assert installation.release_id is None and installation.runtime_ref is None
