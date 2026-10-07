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
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.core.registration_audience import registration_audience
from miy_api.core.settings import Settings, get_settings
from miy_api.domains.auth.models import (
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps import bootstrap, registration, service
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput
from miy_api.domains.independent_apps.bootstrap_models import AppBootstrapOperation
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps.registration_contracts import (
    RegistrationAuthorizationInput,
    RegistrationExchangeInput,
)
from miy_api.domains.independent_apps.registration_models import AppRegistrationAuthorization
from test_alembic_migrations import _migration_config
from test_independent_app_bootstrap import context, other_owner, payload
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
    data = payload(granted_permissions=[])
    requested = consent(data)
    response = issue(client, enabled, requested)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    code = response.json()
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


@pytest.mark.parametrize(
    "change",
    [
        {"code_verifier": "b" * 43},
        {"request_id": str(uuid4())},
        {"code": "miyrc_" + "b" * 43},
        {"code": "miyrg_" + "a" * 43},
        {"code_verifier": "!" * 43},
        {"audience": "https://other.test"},
    ],
)
def test_exchange_rejects_wrong_binding_without_consuming_correct_code(
    client, enabled, change, monkeypatch
):
    code = issue(client, enabled, consent()).json()
    if "audience" in change:
        # Both deployments are configured: authorization for one cannot be
        # redeemed at the other even with the correct code and verifier.
        monkeypatch.setenv(
            "MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES", json.dumps([AUDIENCE, change["audience"]])
        )
        get_settings.cache_clear()
    rejected = client.post(BASE + "/exchange", json=exchange_data(code, **change))
    assert rejected.status_code in (401, 403)
    assert code["code"] not in rejected.text and VERIFIER not in rejected.text
    assert client.post(BASE + "/exchange", json=exchange_data(code)).status_code == 200


@pytest.mark.parametrize("phase", ["exchange", "bootstrap"])
@pytest.mark.parametrize(
    "revocation",
    [
        "session",
        "session_expiry",
        "role",
        "user",
        "blocked",
        "password",
        "admission",
        "grant",
        "expired",
        "audience",
        "impersonation",
    ],
)
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


def test_revocation_is_owner_only_and_credentials_do_not_cross_endpoints(client, enabled):
    data = payload(granted_permissions=[])
    authorized = grant(client, enabled, data)
    foreign = other_owner()
    assert (
        client.delete(
            BASE + f"/{authorized['id']}", headers=_auth_headers(foreign["token"])
        ).status_code
        == 404
    )
    assert issue(client, {"token": authorized["token"]}, consent()).status_code == 401
    assert create(client, authorized | {"token": enabled["token"]}, data).status_code == 401
    assert create(client, authorized | {"id": str(uuid4())}, data).status_code == 401
    assert (
        client.delete(
            BASE + f"/{authorized['id']}", headers=_auth_headers(enabled["token"])
        ).status_code
        == 204
    )
    assert create(client, authorized, data).status_code == 401
    no_registration()


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://different.test"},
        {"operation_id": str(uuid4())},
        {"granted_permissions": ["identity:read"]},
        {"definition": manifest("other-app")},
        {"definition": manifest("bootstrap-personal") | {"requested_permissions": []}},
        {"definition": manifest("bootstrap-personal") | {"runtime_profile": "web-api-postgres-v1"}},
    ],
)
def test_registration_cannot_widen_fixed_consent(client, enabled, change):
    data = payload(granted_permissions=[])
    authorized = grant(client, enabled, data)
    assert create(client, authorized, data | change).status_code == 403
    no_registration()


def test_permission_policy_is_set_but_source_digest_keeps_manifest_order(client, enabled):
    definition = manifest("bootstrap-personal") | {
        "runtime_profile": "web-api-postgres-v1",
        "requested_permissions": ["identity:read", "data:read", "data:write"],
    }
    data = payload(definition=definition, granted_permissions=[])
    authorized = grant(client, enabled, data)
    assert authorized["policy"]["requested_permissions"] == sorted(
        definition["requested_permissions"]
    )
    assert create(client, authorized, data).status_code == 201
    changed = data | {
        "definition": definition
        | {"requested_permissions": list(reversed(definition["requested_permissions"]))}
    }
    assert create(client, authorized, changed).status_code == 409


@pytest.mark.parametrize("boundary", ["after_flush", "expiry_after_flush", "rollback"])
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


@pytest.mark.parametrize("revocation", ["session", "user", "admission", "expiry"])
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


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_registration_requires_atomic_current_authority_transaction(client, enabled, isolation):
    with (
        get_session_factory()()
        .get_bind()
        .connect()
        .execution_options(isolation_level=isolation) as connection
    ):
        with Session(connection) as db:
            actor = context(db, enabled)
            with pytest.raises(HTTPException) as error:
                registration.issue(
                    db, RegistrationAuthorizationInput.model_validate(consent()), actor
                )
            assert error.value.status_code == 403


def test_default_off_and_code_expiration_do_not_grant_implicit_authority(
    client, owner, monkeypatch
):
    monkeypatch.setenv("MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES", "[]")
    get_settings.cache_clear()
    assert issue(client, owner, consent()).status_code == 403
    monkeypatch.setenv("MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES", json.dumps([AUDIENCE]))
    get_settings.cache_clear()
    code = issue(client, owner, consent()).json()
    with get_session_factory()() as db:
        db.get(AppRegistrationAuthorization, code["id"]).code_expires_at = (
            utcnow_naive() - timedelta(seconds=1)
        )
        db.commit()
    assert client.post(BASE + "/exchange", json=exchange_data(code)).status_code == 401
    no_registration()


@pytest.mark.parametrize(
    "bad",
    [
        "https://workbench.test/",
        "https://workbench.test/a/../b",
        "https://workbench.test/a//b",
        "https://workbench.test/%2fother",
        "https://workbench.test/a?next=x",
        "https://workbench.test/a#code",
        "https://user@workbench.test",
        "http://remote.test",
        "/workbench",
        "https://WORKBENCH.test",
        "https://workbench.test/path.with.dot",
        "https://workbench.test/path:colon",
        "https://workbench.test/path;semicolon",
    ],
)
def test_audience_has_one_exact_callback_path(bad):
    with pytest.raises(ValueError):
        registration_audience(bad)


def test_typed_settings_and_wire_reject_ambiguous_policy():
    assert registration_audience(AUDIENCE) == AUDIENCE
    assert registration_audience("http://127.0.0.1:19365") == "http://127.0.0.1:19365"
    settings = Settings(_env_file=None, codex_console_registration_audiences=[AUDIENCE])
    assert settings.codex_console_registration_audiences == [AUDIENCE]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, codex_console_registration_audiences=[AUDIENCE, AUDIENCE])
    value = consent()
    for changed in (
        value | {"schema_version": True},
        value | {"enabled": True},
        value | {"policy": value["policy"] | {"requested_permissions": ["identity:read"] * 2}},
        value | {"policy": value["policy"] | {"requested_permissions": ["data:write"]}},
    ):
        with pytest.raises(ValidationError):
            RegistrationAuthorizationInput.model_validate(changed)


def test_code_and_grant_deadlines_are_capped_by_the_original_session(client, enabled):
    with get_session_factory()() as db:
        actor = context(db, enabled)
        deadline = utcnow_naive() + timedelta(seconds=60)
        actor.session.expires_at = deadline
        db.commit()
    code = issue(client, enabled, consent()).json()
    assert code["expires_at"] == code["code_expires_at"] == deadline.isoformat() + "Z"
    token = client.post(BASE + "/exchange", json=exchange_data(code)).json()
    assert token["expires_at"] == code["expires_at"]


def test_fresh_source_login_can_only_recover_its_owners_original_operation(client, enabled):
    data = payload(granted_permissions=[])
    original = grant(client, enabled, data)
    receipt = create(client, original, data).json()
    fresh_token = "registration-fresh-fixture-" + str(uuid4())
    with get_session_factory()() as db:
        row = db.get(AppRegistrationAuthorization, original["id"])
        db.get(AuthSession, row.source_session_id).revoked_at = utcnow_naive()
        db.add(
            AuthSession(
                id=str(uuid4()),
                user_id=row.actor_user_id,
                token_hash=hash_token(fresh_token),
                expires_at=utcnow_naive() + timedelta(hours=1),
            )
        )
        db.commit()
    assert read(client, original).status_code == 401
    renewed = grant(client, enabled | {"token": fresh_token}, data)
    assert read(client, renewed).json() == receipt
    assert create(client, renewed, data).json() == receipt
    with get_session_factory()() as db:
        row = db.get(AppRegistrationAuthorization, renewed["id"])
        assert row.payload_digest is None and row.consumed_at is None
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 1


def test_valid_metadata_key_and_identity_code_never_become_registration_authority(client, enabled):
    from miy_api.domains.integrations.platform_api_keys import issue_platform_api_key

    with get_session_factory()() as db:
        key = issue_platform_api_key(
            db,
            name="Registration read-only fixture",
            scopes=["app-catalog:read"],
            actor_user_id=enabled["user"]["id"],
        )
        token = key.secret.get_secret_value()
        db.commit()
    assert issue(client, {"token": token}, consent()).status_code == 401
    legacy = client.post(
        "/api/v1/auth/codex-console-session-links", headers=_auth_headers(enabled["token"])
    )
    assert legacy.status_code == 200, legacy.text
    code = issue(client, enabled, consent()).json()
    assert (
        client.post(
            BASE + "/exchange", json=exchange_data(code, code=legacy.json()["code"])
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/codex-console-session-links/exchange", json={"code": code["code"]}
        ).status_code
        == 401
    )
    assert client.post(BASE + "/exchange", json=exchange_data(code)).status_code == 200
    no_registration()


def test_locked_grant_has_bounded_failure_then_same_id_can_resume(client, enabled, monkeypatch):
    data = payload(granted_permissions=[])
    authorized = grant(client, enabled, data)
    monkeypatch.setattr(bootstrap, "LOCK_TIMEOUT_MS", 100)
    with get_session_factory()() as blocker:
        blocker.scalar(
            select(AppRegistrationAuthorization)
            .where(AppRegistrationAuthorization.id == authorized["id"])
            .with_for_update()
        )
        started = monotonic()
        response = create(client, authorized, data)
        assert monotonic() - started < 3
        assert (
            response.status_code == 503
            and response.json()["code"] == "independent_apps.bootstrap_busy"
        )
        assert authorized["token"] not in response.text
        no_registration()
        blocker.rollback()
    assert create(client, authorized, data).status_code == 201


@pytest.mark.migration
def test_authorization_migration_preserves_existing_receipts_and_has_nullable_tokens(postgres_dsn):
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "official_planner_writer_20261006")
    engine = create_engine(postgres_dsn)
    try:
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
            installation = AppInstallationRecord(
                id=str(uuid4()),
                app_id=definition.app_id,
                environment="development",
                origin="https://migration.test",
                enabled=False,
                user_ids=[user.id],
                state="disabled",
            )
            db.add(installation)
            db.flush()
            operation = AppBootstrapOperation(
                operation_id=str(uuid4()),
                owner_user_id=user.id,
                app_id=definition.app_id,
                installation_id=installation.id,
                payload_digest="sha256:" + "b" * 64,
                definition_digest=definition.definition_digest,
                source_revision=definition.source_revision,
            )
            db.add(operation)
            db.flush()
            expected = (operation.operation_id, user.id, installation.id, operation.payload_digest)
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
