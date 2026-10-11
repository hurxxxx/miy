from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.models import AuditLog, AuthSession, CompanyAppControl, User, utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps import bootstrap, service
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput
from miy_api.domains.independent_apps.bootstrap_models import AppBootstrapOperation
from miy_api.domains.independent_apps.contracts import AppDefinition
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from test_independent_apps import manifest
from test_organization_integrations import _auth_headers, _bootstrap_admin

BASE = "/api/v1/independent-apps"


@pytest.fixture
def owner(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    yield admin
    get_settings.cache_clear()


def payload(**changes):
    return {
        "operation_id": str(uuid4()),
        "definition": manifest("bootstrap-personal"),
        "source_revision": "a" * 40,
        "origin": "https://bootstrap.test",
        "granted_permissions": ["identity:read"],
    } | changes


def context(db, owner):
    return resolve_auth_context_from_token(db, owner["token"], update_last_seen=False)


def post(client, owner, data):
    return client.post(BASE + "/bootstrap", headers=_auth_headers(owner["token"]), json=data)


def read(client, owner, operation):
    return client.get(BASE + "/bootstrap/" + operation, headers=_auth_headers(owner["token"]))


def other_owner():
    token = "bootstrap-other-" + str(uuid4())
    with get_session_factory()() as db:
        user = User(
            id=str(uuid4()),
            login_id="bootstrap-member",
            email="bootstrap-member@example.test",
            full_name="Bootstrap Member",
            password_hash="test fixture",
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(
            AuthSession(
                id=str(uuid4()),
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=utcnow_naive() + timedelta(hours=1),
            )
        )
        db.commit()
        return {"token": token, "user": {"id": user.id}}


def test_atomic_receipt_is_disabled_owner_only_and_recoverable_after_response_loss(client, owner):
    member = other_owner()
    data = payload()
    response = post(client, member, data)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {
        "operation_id",
        "app_id",
        "installation_id",
        "definition_digest",
        "source_revision",
        "created_at",
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert receipt["operation_id"] == data["operation_id"]
    assert (
        receipt["definition_digest"]
        == AppDefinition.model_validate(data["definition"]).content_digest()
    )
    assert receipt["created_at"].endswith("Z")
    # Discard the first response: a separate request can retrieve or replay it.
    assert read(client, member, data["operation_id"]).json() == receipt
    normalized = data | {
        "definition": AppDefinition.model_validate(data["definition"]).model_dump(mode="json")
    }
    assert post(client, member, normalized).json() == receipt
    with get_session_factory()() as db:
        install = db.get(AppInstallationRecord, receipt["installation_id"])
        assert (install.environment, install.enabled, install.state) == (
            "development",
            False,
            "disabled",
        )
        assert (install.audience, install.user_ids, install.group_ids) == (
            "selected",
            [member["user"]["id"]],
            [],
        )
        assert install.granted_permissions == ["identity:read"]
        assert (
            install.release_id is None and install.generation == 1 and install.runtime_ref is None
        )
        assert db.get(AppDefinitionRecord, receipt["app_id"]).owner_user_id == member["user"]["id"]
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 1
        actions = db.scalars(
            select(AuditLog.action).where(AuditLog.action.like("independent_app.%"))
        ).all()
        assert sorted(actions) == [
            "independent_app.definition.register",
            "independent_app.installation.configure",
        ]
    assert read(client, owner, data["operation_id"]).status_code == 404
    assert post(client, owner, data).status_code == 409
    catalog = client.get(BASE + "/catalog", headers=_auth_headers(member["token"])).json()
    assert catalog["items"][0]["installations"][0]["launchable"] is False
    candidate = {
        "definition_digest": receipt["definition_digest"],
        "source_revision": receipt["source_revision"],
        "artifact": "sha256:" + "b" * 64,
    }
    release = client.post(
        BASE + "/bootstrap-personal/releases",
        headers=_auth_headers(member["token"]),
        json=candidate,
    )
    assert release.status_code == 201, release.text
    assert release.json()["verification_id"] is None
    assert release.json()["verified_at"] is None
    assert (
        client.post(
            BASE + "/bootstrap-personal/releases",
            headers=_auth_headers(member["token"]),
            json=candidate | {"verified_at": "2026-01-01T00:00:00"},
        ).status_code
        == 422
    )


def test_late_failure_rolls_back_definition_installation_control_audit_and_receipt(
    client, owner, monkeypatch
):
    original = service.stage_installation

    def fail_after_flush(db, *args, **kwargs):
        result = original(db, *args, **kwargs)
        assert db.get(AppInstallationRecord, result.id) is not None
        raise RuntimeError("synthetic lost work before commit")

    monkeypatch.setattr(service, "stage_installation", fail_after_flush)
    data = BootstrapInput.model_validate(payload())
    with get_session_factory()() as db:
        actor = context(db, owner)
        with pytest.raises(RuntimeError, match="synthetic lost work"):
            bootstrap.create(db, data, actor, platform_origin="https://platform.test")
    with get_session_factory()() as db:
        assert db.get(AppDefinitionRecord, data.definition.app_id) is None
        assert db.get(CompanyAppControl, data.definition.app_id) is None
        assert db.scalar(select(func.count()).select_from(AppInstallationRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.like("independent_app.%"))
            )
            == 0
        )


@pytest.mark.parametrize("conflict", ["app"])
def test_concurrent_registration_has_one_completion_and_no_partial_loser(client, owner, conflict):
    first = payload()
    second = dict(first)
    if conflict == "payload":
        second["source_revision"] = "b" * 40
    elif conflict == "app":
        second["operation_id"] = str(uuid4())
        second["origin"] = "https://other-bootstrap.test"
    elif conflict == "origin":
        second["operation_id"] = str(uuid4())
        second["definition"] = manifest("second-bootstrap")
    start = Event()

    def run(data):
        with get_session_factory()() as db:
            actor = context(db, owner)
            assert start.wait(10)
            try:
                return bootstrap.create(
                    db,
                    BootstrapInput.model_validate(data),
                    actor,
                    platform_origin="https://platform.test",
                ).model_dump(mode="json")
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(run, data) for data in (first, second)]
        start.set()
        values = [future.result(timeout=15) for future in results]
    if conflict == "identical":
        assert isinstance(values[0], dict) and values[0] == values[1]
    else:
        assert sum(isinstance(value, dict) for value in values) == 1
        assert 409 in values
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 1
        assert db.scalar(select(func.count()).select_from(AppDefinitionRecord)) == 1
        assert db.scalar(select(func.count()).select_from(AppInstallationRecord)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.like("independent_app.%"))
            )
            == 2
        )


@pytest.mark.parametrize("revocation", ["session"])
def test_current_owner_is_rechecked_after_waiting_for_registration_locks(client, owner, revocation):
    data = BootstrapInput.model_validate(payload())
    started = Event()
    backend = []

    def register():
        with get_session_factory()() as db:
            actor = context(db, owner)
            backend.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            try:
                bootstrap.create(db, data, actor, platform_origin="https://platform.test")
            except HTTPException as exc:
                return exc.status_code
            return 201

    with get_session_factory()() as blocker:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": bootstrap._lock_keys(data)[0]}
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(register)
            try:
                assert started.wait(5)
                deadline = monotonic() + 5
                with get_session_factory()() as observer:
                    while monotonic() < deadline:
                        if (
                            observer.scalar(
                                text("SELECT cardinality(pg_blocking_pids(:pid))"),
                                {"pid": backend[0]},
                            )
                            > 0
                        ):
                            break
                    else:
                        pytest.fail("Registration did not reach the real PostgreSQL lock")
                    if revocation == "session":
                        context(observer, owner).session.revoked_at = utcnow_naive()
                    else:
                        observer.get(User, owner["user"]["id"]).login_blocked = True
                    observer.commit()
            finally:
                blocker.rollback()
            assert future.result(timeout=10) in (401, 403)
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0
        assert db.get(AppDefinitionRecord, data.definition.app_id) is None
