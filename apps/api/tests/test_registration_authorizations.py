from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
from threading import Event
from time import monotonic
from uuid import uuid4

from alembic import command
from fastapi import HTTPException
import pytest
from sqlalchemy import MetaData, Table, create_engine, delete, func, inspect, select, text
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import (
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.independent_apps import bootstrap, registration, service
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput
from miy_api.domains.independent_apps.bootstrap_models import AppBootstrapOperation
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps.registration_contracts import (
    RegistrationExchangeInput,
)
from miy_api.domains.independent_apps.registration_models import AppRegistrationAuthorization
from test_alembic_migrations import _migration_config
from test_independent_app_bootstrap import context, payload
from test_independent_apps import manifest
from test_organization_integrations import _auth_headers, _bootstrap_admin

BASE = "/api/v1/independent-apps/bootstrap-authorizations"
AUDIENCE = "https://workbench.test/workbench"
VERIFIER = "fixture-registration-verifier-" + "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


@pytest.fixture
def owner(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    monkeypatch.setenv("MIY_CODEX_CONSOLE_LAUNCH_URL", AUDIENCE)
    get_settings.cache_clear()
    actor = _bootstrap_admin(client)
    with get_session_factory()() as db:
        db.get(CompanyAppControl, "codex-console").enabled = True
        db.commit()
    yield actor
    get_settings.cache_clear()


@pytest.fixture
def enabled(owner, monkeypatch):
    monkeypatch.setenv("MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES", json.dumps([AUDIENCE]))
    get_settings.cache_clear()
    yield owner
    get_settings.cache_clear()


def consent(data=None, **changes):
    data = data or payload(granted_permissions=[])
    return {
        "schema_version": 1,
        "request_id": str(uuid4()),
        "operation_id": data["operation_id"],
        "audience": AUDIENCE,
        "code_challenge": CHALLENGE,
        "policy": {
            "app_id": data["definition"]["app_id"],
            "origin": data["origin"],
            "runtime_profile": data["definition"].get("runtime_profile", "web-api-v1"),
            "requested_permissions": data["definition"]["requested_permissions"],
        },
    } | changes


def issue(client, actor, data):
    return client.post(BASE, headers=_auth_headers(actor["token"]), json=data)


def exchange_data(issued, **changes):
    return {
        "schema_version": 1,
        "request_id": issued["request_id"],
        "audience": issued["audience"],
        "code": issued["code"],
        "code_verifier": VERIFIER,
    } | changes


def grant(client, actor, data):
    response = issue(client, actor, consent(data))
    assert response.status_code == 201, response.text
    code = response.json()
    response = client.post(BASE + "/exchange", json=exchange_data(code))
    assert response.status_code == 200, response.text
    return response.json()


def create(client, authorized, data):
    return client.post(
        BASE + f"/{authorized['id']}/bootstrap",
        json=data,
        headers=_auth_headers(authorized["token"]),
    )


def read(client, authorized):
    return client.get(
        BASE + f"/{authorized['id']}/receipt", headers=_auth_headers(authorized["token"])
    )


def no_registration():
    with get_session_factory()() as db:
        for model in (AppDefinitionRecord, AppInstallationRecord, AppBootstrapOperation):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(AppRegistrationAuthorization)
                .where(AppRegistrationAuthorization.payload_digest.is_not(None))
            )
            == 0
        )


def test_owner_consent_exchange_and_same_operation_recovery(client, enabled):
    with get_session_factory()() as db:
        deadline = utcnow_naive() + timedelta(seconds=60)
        context(db, enabled).session.expires_at = deadline
        db.commit()
    data = payload(granted_permissions=[])
    requested = consent(data)
    response = issue(client, enabled, requested)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    code = response.json()
    assert code["expires_at"] == code["code_expires_at"] == deadline.isoformat() + "Z"
    wrong = client.post(BASE + "/exchange", json=exchange_data(code, code_verifier="x" * 43))
    assert wrong.status_code in (401, 403)
    assert code["code"] not in wrong.text and VERIFIER not in wrong.text
    assert code["callback_url"] == AUDIENCE + "/api/registration-authorizations/callback"
    assert code["code_expires_at"].endswith("Z") and code["expires_at"].endswith("Z")
    assert code["code"].startswith("miyrc_") and len(code["code"]) == 49
    assert code["actor_user_id"] == enabled["user"]["id"]
    assert issue(client, enabled, requested).status_code == 409
    response = client.post(BASE + "/exchange", json=exchange_data(code))
    assert response.status_code == 200, response.text
    authorized = response.json()
    assert authorized["expires_at"] == code["expires_at"]
    assert "code" not in authorized and "callback_url" not in authorized
    assert len(authorized["token"]) == 49 and authorized["token"].startswith("miyrg_")
    assert client.post(BASE + "/exchange", json=exchange_data(code)).status_code == 401
    assert read(client, authorized).status_code == 404
    response = create(client, authorized, data)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert read(client, authorized).json() == receipt
    assert create(client, authorized, data).json() == receipt
    with get_session_factory()() as db:
        row = db.get(AppRegistrationAuthorization, authorized["id"])
        assert row.consumed_at is not None and row.payload_digest.startswith("sha256:")
        assert row.code_hash != code["code"] and row.token_hash != authorized["token"]
        install = db.get(AppInstallationRecord, receipt["installation_id"])
        assert (install.enabled, install.environment, install.granted_permissions) == (
            False,
            "development",
            [],
        )
        assert install.user_ids == [enabled["user"]["id"]] and install.group_ids == []
        row.expires_at = utcnow_naive() - timedelta(seconds=1)
        db.commit()
    assert read(client, authorized).status_code == 401
    renewed = grant(client, enabled, data)
    assert read(client, renewed).json() == receipt
    assert create(client, renewed, data).json() == receipt
    assert create(client, renewed, data | {"source_revision": "b" * 40}).status_code == 409
    assert create(client, renewed, data | {"operation_id": str(uuid4())}).status_code == 403


@pytest.mark.parametrize("phase,revocation", [("exchange", "session"), ("bootstrap", "grant")])
def test_current_authority_is_required_at_every_step(
    client, enabled, monkeypatch, phase, revocation
):
    data = payload(granted_permissions=[])
    code = issue(client, enabled, consent(data)).json()
    authorized = (
        client.post(BASE + "/exchange", json=exchange_data(code)).json()
        if phase == "bootstrap"
        else None
    )
    with get_session_factory()() as db:
        row = db.get(AppRegistrationAuthorization, code["id"])
        if revocation == "session":
            db.get(AuthSession, row.source_session_id).revoked_at = utcnow_naive()
        elif revocation == "session_expiry":
            db.get(AuthSession, row.source_session_id).expires_at = utcnow_naive() - timedelta(
                seconds=1
            )
        elif revocation == "role":
            db.execute(delete(UserSystemRole).where(UserSystemRole.user_id == row.actor_user_id))
        elif revocation == "user":
            db.get(User, row.actor_user_id).status = "inactive"
        elif revocation == "blocked":
            db.get(User, row.actor_user_id).login_blocked = True
        elif revocation == "password":
            db.get(User, row.actor_user_id).must_change_password = True
        elif revocation == "admission":
            db.get(CompanyAppControl, "codex-console").enabled = False
        elif revocation == "grant":
            row.revoked_at = utcnow_naive()
        elif revocation == "expired":
            row.expires_at = utcnow_naive() - timedelta(seconds=1)
        elif revocation == "impersonation":
            db.get(AuthSession, row.source_session_id).impersonator_user_id = row.actor_user_id
        db.commit()
    if revocation == "audience":
        monkeypatch.setenv("MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES", "[]")
        get_settings.cache_clear()
    response = (
        client.post(BASE + "/exchange", json=exchange_data(code))
        if phase == "exchange"
        else create(client, authorized, data)
    )
    assert response.status_code in (401, 403), response.text
    no_registration()


@pytest.mark.parametrize("change", [{"granted_permissions": ["identity:read"]}])
def test_registration_cannot_widen_fixed_consent(client, enabled, change):
    data = payload(granted_permissions=[])
    authorized = grant(client, enabled, data)
    assert create(client, authorized, data | change).status_code == 403
    no_registration()


@pytest.mark.parametrize("boundary", ["after_flush"])
def test_late_source_revocation_and_failure_roll_back_grant_and_resources(
    client, enabled, monkeypatch, boundary
):
    data = payload(granted_permissions=[])
    authorized = grant(client, enabled, data)
    original = service.stage_installation

    def late(db, *args, **kwargs):
        result = original(db, *args, **kwargs)
        if boundary == "rollback":
            raise RuntimeError("fixture precommit failure")
        if boundary == "expiry_after_flush":
            now = utcnow_naive() + timedelta(minutes=10)
            monkeypatch.setattr(registration, "utcnow_naive", lambda: now)
            return result
        with get_session_factory()() as separate:
            row = separate.get(AppRegistrationAuthorization, authorized["id"])
            separate.get(AuthSession, row.source_session_id).revoked_at = utcnow_naive()
            separate.commit()
        return result

    monkeypatch.setattr(service, "stage_installation", late)
    if boundary != "rollback":
        assert create(client, authorized, data).status_code == 401
    else:
        with get_session_factory()() as db, pytest.raises(RuntimeError, match="fixture precommit"):
            registration.create(
                db,
                authorized["id"],
                "Bearer " + authorized["token"],
                BootstrapInput.model_validate(data),
                platform_origin="https://platform.test",
            )
        monkeypatch.setattr(service, "stage_installation", original)
    no_registration()
    if boundary == "rollback":
        assert create(client, authorized, data).status_code == 201


@pytest.mark.parametrize("phase", ["exchange", "bootstrap"])
def test_concurrent_consumption_has_exactly_one_code_or_one_immutable_receipt(
    client, enabled, phase
):
    data = payload(granted_permissions=[])
    code = issue(client, enabled, consent(data)).json()
    authorized = (
        client.post(BASE + "/exchange", json=exchange_data(code)).json()
        if phase == "bootstrap"
        else None
    )
    start = Event()

    def run():
        with get_session_factory()() as db:
            assert start.wait(5)
            try:
                if phase == "exchange":
                    return registration.exchange(
                        db, RegistrationExchangeInput.model_validate(exchange_data(code))
                    ).id
                return registration.create(
                    db,
                    authorized["id"],
                    "Bearer " + authorized["token"],
                    BootstrapInput.model_validate(data),
                    platform_origin="https://platform.test",
                ).operation_id
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run), pool.submit(run)]
        start.set()
        results = [future.result(timeout=10) for future in pending]
    if phase == "exchange":
        assert results.count(401) == 1 and sum(not isinstance(item, int) for item in results) == 1
    else:
        assert str(results[0]) == data["operation_id"] == str(results[1])
        with get_session_factory()() as db:
            assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 1


@pytest.mark.parametrize("revocation", ["expiry"])
def test_after_advisory_wait_rechecks_source_and_clock(client, enabled, revocation):
    data = BootstrapInput.model_validate(payload(granted_permissions=[]))
    authorized = grant(client, enabled, data.model_dump(mode="json"))
    started = Event()
    backend = []
    if revocation == "expiry":
        with get_session_factory()() as db:
            db.get(AppRegistrationAuthorization, authorized["id"]).expires_at = (
                utcnow_naive() + timedelta(seconds=1)
            )
            db.commit()

    def run():
        with get_session_factory()() as db:
            backend.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            try:
                registration.create(
                    db,
                    authorized["id"],
                    "Bearer " + authorized["token"],
                    data,
                    platform_origin="https://platform.test",
                )
                return 201
            except HTTPException as exc:
                return exc.status_code

    with get_session_factory()() as blocker, ThreadPoolExecutor(max_workers=1) as pool:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": bootstrap._lock_keys(data)[0]}
        )
        future = pool.submit(run)
        try:
            assert started.wait(5)
            deadline = monotonic() + 3
            with get_session_factory()() as observer:
                while monotonic() < deadline:
                    if (
                        observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": backend[0]}
                        )
                        > 0
                    ):
                        break
                else:
                    pytest.fail("No real advisory lock wait")
                if revocation != "expiry":
                    row = observer.get(AppRegistrationAuthorization, authorized["id"])
                    if revocation == "session":
                        observer.get(AuthSession, row.source_session_id).revoked_at = utcnow_naive()
                    elif revocation == "user":
                        observer.get(User, row.actor_user_id).login_blocked = True
                    else:
                        observer.get(CompanyAppControl, "codex-console").enabled = False
                    observer.commit()
                else:
                    observer.execute(text("SELECT pg_sleep(1.1)"))
        finally:
            blocker.rollback()
        assert future.result(timeout=10) == (403 if revocation in {"user", "admission"} else 401)
    no_registration()


@pytest.mark.migration
def test_authorization_migration_preserves_existing_receipts_and_has_nullable_tokens(postgres_dsn):
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "official_planner_writer_20261006")
    engine = create_engine(postgres_dsn)
    try:
        # Seed the selected historical schema without future ORM metadata.
        installations = Table("independent_app_installations", MetaData(), autoload_with=engine)
        with Session(engine) as db:
            user = User(
                id=str(uuid4()),
                login_id="registration-migration",
                email="registration-migration@example.test",
                full_name="Fixture owner",
                password_hash="fixture",
            )
            db.add(user)
            db.flush()
            definition = AppDefinitionRecord(
                app_id="migration-personal",
                owner_user_id=user.id,
                manifest=manifest("migration-personal"),
                definition_digest="sha256:" + "a" * 64,
                source_revision="a" * 40,
            )
            db.add(definition)
            db.flush()
            installation_id = str(uuid4())
            db.execute(
                installations.insert().values(
                    id=installation_id,
                    app_id=definition.app_id,
                    environment="development",
                    origin="https://migration.test",
                    enabled=False,
                    audience="selected",
                    user_ids=[user.id],
                    group_ids=[],
                    granted_permissions=[],
                    release_id=None,
                    state="disabled",
                    generation=1,
                    runtime_ref=None,
                )
            )
            db.flush()
            operation = AppBootstrapOperation(
                operation_id=str(uuid4()),
                owner_user_id=user.id,
                app_id=definition.app_id,
                installation_id=installation_id,
                payload_digest="sha256:" + "b" * 64,
                definition_digest=definition.definition_digest,
                source_revision=definition.source_revision,
            )
            db.add(operation)
            db.flush()
            expected = (operation.operation_id, user.id, installation_id, operation.payload_digest)
            db.commit()
        command.upgrade(config, "registration_auth_20261007")
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns(AppRegistrationAuthorization.__tablename__)
        }
        assert set(columns) == set(AppRegistrationAuthorization.__table__.columns.keys())
        actual_indexes = inspect(engine).get_indexes(AppRegistrationAuthorization.__tablename__)
        assert {
            item["name"] for item in actual_indexes if not item.get("duplicates_constraint")
        } == {item.name for item in AppRegistrationAuthorization.__table__.indexes}
        assert columns["token_hash"]["nullable"] and columns["payload_digest"]["nullable"]
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT operation_id, owner_user_id, installation_id, payload_digest FROM independent_app_bootstrap_operations"
                    )
                ).one()
                == expected
            )
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM independent_app_registration_authorizations")
                )
                == 0
            )
        command.downgrade(config, "official_planner_writer_20261006")
        assert AppRegistrationAuthorization.__tablename__ not in inspect(engine).get_table_names()
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT operation_id, owner_user_id, installation_id, payload_digest FROM independent_app_bootstrap_operations"
                    )
                ).one()
                == expected
            )
        command.upgrade(config, "registration_auth_20261007")
    finally:
        engine.dispose()
