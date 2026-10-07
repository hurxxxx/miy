from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

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


def test_receipt_does_not_restore_old_definition_or_installation_state(client, owner):
    data = payload()
    first = post(client, owner, data).json()
    current = AppDefinition.model_validate(data["definition"]).model_dump(mode="json")
    current["display"]["name"] = "Later edit"
    changed = client.put(
        BASE + "/definitions",
        headers=_auth_headers(owner["token"]),
        json={
            "definition": current,
            "source_revision": "b" * 40,
            "expected_digest": first["definition_digest"],
            "expected_source_revision": "a" * 40,
        },
    )
    assert changed.status_code == 200, changed.text
    updated = client.put(
        BASE + "/bootstrap-personal/installations/" + first["installation_id"],
        headers=_auth_headers(owner["token"]),
        json={
            "environment": "development",
            "origin": data["origin"],
            "enabled": True,
            "user_ids": [owner["user"]["id"]],
            "granted_permissions": ["identity:read"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert post(client, owner, data).json() == first
    assert read(client, owner, data["operation_id"]).json() == first
    with get_session_factory()() as db:
        assert db.get(AppDefinitionRecord, first["app_id"]).source_revision == "b" * 40
        install = db.get(AppInstallationRecord, first["installation_id"])
        assert install.generation == 2 and install.enabled


@pytest.mark.parametrize(
    "change",
    [
        {"source_revision": "b" * 40},
        {"origin": "https://other-bootstrap.test"},
        {"granted_permissions": []},
        {"definition": manifest("another-bootstrap")},
    ],
)
def test_same_operation_requires_exact_canonical_payload(client, owner, change):
    data = payload()
    assert post(client, owner, data).status_code == 201
    assert post(client, owner, data | change).status_code == 409


def test_grant_order_is_canonical_but_manifest_digest_keeps_existing_array_semantics(client, owner):
    definition = manifest() | {
        "runtime_profile": "web-api-postgres-v1",
        "requested_permissions": ["identity:read", "data:read", "data:write"],
    }
    data = payload(definition=definition, granted_permissions=["identity:read", "data:read"])
    receipt = post(client, owner, data).json()
    assert receipt["definition_digest"] == AppDefinition.model_validate(definition).content_digest()
    assert (
        post(client, owner, data | {"granted_permissions": ["data:read", "identity:read"]}).json()
        == receipt
    )
    reverse_manifest = definition | {
        "requested_permissions": list(reversed(definition["requested_permissions"]))
    }
    assert post(client, owner, data | {"definition": reverse_manifest}).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "production"},
        {"enabled": True},
        {"audience": "all"},
        {"user_ids": ["another-owner"]},
        {"owner_user_id": "another-owner"},
        {"group_ids": ["some-group"]},
        {"command": "create anything"},
        {"definition": manifest() | {"ownership": "official"}},
        {"granted_permissions": ["identity:read", "identity:read"]},
    ],
)
def test_admin_cannot_expand_bootstrap_policy(client, owner, change):
    assert post(client, owner, payload(**change)).status_code == 422


@pytest.mark.parametrize("origin", ["https://platform.test", "http://testserver"])
def test_platform_origin_is_not_an_app_origin(client, owner, origin):
    response = post(client, owner, payload(origin=origin))
    assert response.status_code == 422
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AppDefinitionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0


def test_configuration_permissions_and_static_ids_rollback_all_staged_rows(
    client, owner, monkeypatch
):
    assert post(client, owner, payload(definition=manifest("docs"))).status_code == 409
    assert post(client, owner, payload(granted_permissions=["data:read"])).status_code == 403
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", "[]")
    get_settings.cache_clear()
    assert post(client, owner, payload()).status_code == 503
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(AppDefinitionRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AppInstallationRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0
        assert db.get(CompanyAppControl, "bootstrap-personal") is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action.like("independent_app.%"))
            )
            == 0
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


def test_different_operation_never_adopts_existing_app_or_origin(client, owner):
    first = payload()
    receipt = post(client, owner, first).json()
    assert post(client, owner, first | {"operation_id": str(uuid4())}).status_code == 409
    conflict = payload(definition=manifest("second-bootstrap"))
    assert post(client, owner, conflict).status_code == 409
    with get_session_factory()() as db:
        assert db.get(AppDefinitionRecord, "second-bootstrap") is None
        assert db.get(CompanyAppControl, "second-bootstrap") is None
        assert db.scalar(select(func.count()).select_from(AppInstallationRecord)) == 1
    assert read(client, owner, first["operation_id"]).json() == receipt


def test_only_current_non_impersonated_matching_owner_can_create_or_read(client, owner):
    data = payload()
    assert client.post(BASE + "/bootstrap", json=data).status_code == 401
    receipt = post(client, owner, data).json()
    second = other_owner()
    with get_session_factory()() as db:
        actor = context(db, owner)
        foreign = context(db, second)
        for action in ("create", "read"):
            with pytest.raises(HTTPException) as error:
                if action == "create":
                    bootstrap.create(
                        db,
                        BootstrapInput.model_validate(payload()),
                        replace(actor, user=foreign.user),
                        platform_origin="https://platform.test",
                    )
                else:
                    bootstrap.read(db, data["operation_id"], replace(actor, user=foreign.user))
            assert error.value.status_code == 403
        source = db.get(AuthSession, foreign.session.id)
        source.impersonator_user_id = owner["user"]["id"]
        db.commit()
    assert post(client, second, payload()).status_code == 403
    assert read(client, second, data["operation_id"]).status_code == 403
    with get_session_factory()() as db:
        source = context(db, owner).session
        source.revoked_at = utcnow_naive()
        db.commit()
    assert post(client, owner, data).status_code == 401
    assert read(client, owner, receipt["operation_id"]).status_code == 401


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE", "AUTOCOMMIT"])
def test_controller_requires_current_authority_and_one_atomic_transaction(client, owner, isolation):
    factory = get_session_factory()
    with factory().get_bind().connect().execution_options(isolation_level=isolation) as connection:
        with Session(connection) as db:
            actor = context(db, owner)
            with pytest.raises(HTTPException) as error:
                bootstrap.create(
                    db,
                    BootstrapInput.model_validate(payload()),
                    actor,
                    platform_origin="https://platform.test",
                )
            assert error.value.status_code == 403
            with pytest.raises(HTTPException) as error:
                bootstrap.read(db, str(uuid4()), actor)
            assert error.value.status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0


@pytest.mark.parametrize("conflict", ["identical", "payload", "app", "origin"])
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


@pytest.mark.parametrize("revocation", ["session", "user"])
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


@pytest.mark.parametrize("revocation", ["session", "user"])
def test_authority_revoked_after_resource_flush_rolls_back_everything(
    client, owner, monkeypatch, revocation
):
    original = service.stage_installation

    def revoke_after_flush(db, *args, **kwargs):
        result = original(db, *args, **kwargs)
        with get_session_factory()() as revoker:
            if revocation == "session":
                context(revoker, owner).session.revoked_at = utcnow_naive()
            else:
                revoker.get(User, owner["user"]["id"]).login_blocked = True
            revoker.commit()
        return result

    monkeypatch.setattr(service, "stage_installation", revoke_after_flush)
    data = BootstrapInput.model_validate(payload())
    with get_session_factory()() as db:
        actor = context(db, owner)
        with pytest.raises(HTTPException) as error:
            bootstrap.create(db, data, actor, platform_origin="https://platform.test")
        assert error.value.status_code in (401, 403)
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


def test_real_lock_timeout_is_localized_bounded_and_does_not_leave_partial_registration(
    client, owner, monkeypatch
):
    monkeypatch.setattr(bootstrap, "LOCK_TIMEOUT_MS", 150)
    data = payload()
    parsed = BootstrapInput.model_validate(data)
    with get_session_factory()() as blocker:
        blocker.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": bootstrap._lock_keys(parsed)[0]}
        )
        started = monotonic()
        response = post(client, owner, data)
        assert monotonic() - started < 3
        assert response.status_code == 503
        assert response.json()["code"] == "independent_apps.bootstrap_busy"
        assert "SQL" not in response.text and "pg_advisory" not in response.text
        with get_session_factory()() as db:
            actor = context(db, owner)
            prior = db.scalar(text("SHOW lock_timeout"))
            with pytest.raises(HTTPException) as error:
                bootstrap.create(db, parsed, actor, platform_origin="https://platform.test")
            assert error.value.status_code == 503
            assert db.scalar(text("SHOW lock_timeout")) == prior
            assert db.get(AppDefinitionRecord, parsed.definition.app_id) is None
            assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action.like("independent_app.%"))
                )
                == 0
            )
        blocker.rollback()
    # Same operation remains valid after the real blocking transaction releases.
    assert post(client, owner, data).status_code == 201


def test_unrelated_database_errors_are_not_hidden_as_retryable_registration(
    client, owner, monkeypatch
):
    from sqlalchemy.exc import ProgrammingError

    original = service.stage_installation

    def malformed_query(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.execute(text("SELECT * FROM bootstrap_nonexistent_fixture_relation"))

    monkeypatch.setattr(service, "stage_installation", malformed_query)
    data = BootstrapInput.model_validate(payload())
    with get_session_factory()() as db:
        actor = context(db, owner)
        with pytest.raises(ProgrammingError) as error:
            bootstrap.create(db, data, actor, platform_origin="https://platform.test")
        assert error.value.orig.sqlstate == "42P01"
        assert db.get(AppDefinitionRecord, data.definition.app_id) is None
        assert db.scalar(select(func.count()).select_from(AppInstallationRecord)) == 0
        assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0


@pytest.mark.migration
def test_bootstrap_migration_preserves_existing_registration_on_upgrade_and_downgrade(postgres_dsn):
    from alembic import command
    import sqlalchemy as sa
    from test_alembic_migrations import _migration_config
    from miy_api.core.model_registry import import_all_models

    config = _migration_config(postgres_dsn)
    command.upgrade(config, "official_writer_roles_20261006")
    engine = sa.create_engine(postgres_dsn)
    import_all_models()
    try:
        with Session(engine) as db:
            user = User(
                id=str(uuid4()),
                login_id="bootstrap-migration",
                email="bootstrap-migration@example.test",
                full_name="Migration owner",
                password_hash="fixture",
            )
            db.add(user)
            db.flush()
            definition = AppDefinitionRecord(
                app_id="preexisting-personal",
                owner_user_id=user.id,
                manifest=manifest("preexisting-personal"),
                definition_digest="sha256:" + "a" * 64,
                source_revision="a" * 40,
            )
            db.add(definition)
            db.flush()
            installation = AppInstallationRecord(
                id=str(uuid4()),
                app_id=definition.app_id,
                environment="development",
                origin="https://preexisting.test",
                enabled=False,
                user_ids=[user.id],
                state="disabled",
            )
            db.add(installation)
            db.flush()
            identities = (user.id, definition.app_id, installation.id)
            db.commit()
        command.upgrade(config, "independent_bootstrap_20261006")
        operation_id = str(uuid4())
        with Session(engine) as db:
            # A synthetic completed receipt exercises the exact FK dependency order.
            db.add(
                AppBootstrapOperation(
                    operation_id=operation_id,
                    owner_user_id=identities[0],
                    app_id=identities[1],
                    installation_id=identities[2],
                    payload_digest="sha256:" + "b" * 64,
                    definition_digest="sha256:" + "a" * 64,
                    source_revision="a" * 40,
                )
            )
            db.commit()
        columns = {
            column["name"]
            for column in sa.inspect(engine).get_columns("independent_app_bootstrap_operations")
        }
        assert columns == set(AppBootstrapOperation.__table__.columns.keys())
        assert {
            fk["referred_table"]
            for fk in sa.inspect(engine).get_foreign_keys("independent_app_bootstrap_operations")
        } == {"users", "independent_app_definitions", "independent_app_installations"}
        command.downgrade(config, "official_writer_roles_20261006")
        assert "independent_app_bootstrap_operations" not in sa.inspect(engine).get_table_names()
        with Session(engine) as db:
            assert db.get(User, identities[0]) is not None
            assert db.get(AppDefinitionRecord, identities[1]).source_revision == "a" * 40
            assert db.get(AppInstallationRecord, identities[2]).origin == "https://preexisting.test"
        command.upgrade(config, "independent_bootstrap_20261006")
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(AppBootstrapOperation)) == 0
            assert db.get(AppDefinitionRecord, identities[1]) is not None
            assert db.get(AppInstallationRecord, identities[2]) is not None
    finally:
        engine.dispose()
