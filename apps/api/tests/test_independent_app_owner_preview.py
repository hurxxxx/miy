from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import event, func, select, text

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import AuditLog, User, utcnow_naive
from miy_api.domains.independent_apps import delivery, owner_preview
from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.delivery_models import (
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


@pytest.mark.parametrize("change", ["definition"])
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
