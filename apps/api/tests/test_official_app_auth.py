from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from company_admission_fixture import seed_company_app_access
from miy_api.api_registry import register_api_routers
from miy_api.app import localized_http_exception_handler
from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.auth.models import (
    AuditLog,
    AuthSession,
    CompanyAppControl,
    User,
    UserSystemRole,
    utcnow_naive,
)
from miy_api.domains.auth.security import hash_token, new_id
from miy_api.domains.docs.access_context import resolve_native_doc_access
from miy_api.domains.docs.models import NativeDoc, NativeDocGroupShare
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import (
    AppInstallationRecord,
    AppReleaseRecord,
    AppSession,
)
from miy_api.domains.official_apps.auth import (
    approve_binding,
    resolve_official_auth_context,
    revoke_binding,
)
from miy_api.domains.official_apps.models import OfficialAppBinding
from miy_api.domains.pms.access import resolve_pms_space_role
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    enqueue,
    execute,
)
from test_independent_apps import exchange, launch, manifest, setup_app


@pytest.fixture
def bound_official(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    app = setup_app(client)
    admin, headers, _, installation, _ = app
    response = client.put(
        "/api/v1/independent-apps/definitions",
        headers=headers,
        json={
            "definition": manifest() | {"ownership": "official"},
            "source_revision": "a" * 40,
            "expected_digest": app[2]["definition_digest"],
            "expected_source_revision": app[2]["source_revision"],
        },
    )
    assert response.status_code == 200, response.text
    release_id = build_release(response.json())
    request, _ = enqueue(client, app, release_id)
    assert execute(request, FakeRuntime()).state == "succeeded"
    installation = current_installation(installation["id"])
    login_token = "official-member-login-fixture"
    with get_session_factory()() as db:
        seed_company_app_access(db, app_ids=["docs", "pms"])
        actor = resolve_auth_context_from_token(db, admin["token"], update_last_seen=False)
        binding = approve_binding(
            db,
            actor,
            installation_id=installation["id"],
            expected_generation=installation["generation"],
            expected_release_id=release_id,
            expected_artifact="sha256:" + "a" * 64,
            logical_app_ids=frozenset({"docs", "pms"}),
        )
        user = User(
            id=new_id(),
            login_id="official-member",
            email="member@example.test",
            full_name="Official Member",
            password_hash="fixture",
        )
        group = Group(id=new_id(), source="local", name="Official group")
        db.add_all([user, group])
        db.flush()
        db.add(GroupMember(group_id=group.id, user_id=user.id))
        source = AuthSession(
            id=new_id(),
            user_id=user.id,
            token_hash=hash_token(login_token),
            expires_at=utcnow_naive() + timedelta(hours=1),
            last_seen_at=utcnow_naive() - timedelta(hours=1),
        )
        db.add(source)
        installed = db.get(AppInstallationRecord, installation["id"])
        installed.group_ids = [group.id]
        db.commit()
        result = dict(
            admin=admin,
            installation=installation,
            release_id=release_id,
            binding_id=binding.id,
            member_id=user.id,
            source_id=source.id,
            group_id=group.id,
            login_token=login_token,
        )
    exchanged = exchange(
        client, launch(client, {"Authorization": f"Bearer {login_token}"}, installation)
    )
    assert exchanged.status_code == 200, exchanged.text
    result["app_token"] = exchanged.json()["token"]
    yield result
    get_settings.cache_clear()


def test_binding_reuses_roles_and_acl_principal_without_authentication_writes(
    client, bound_official
):
    state = bound_official
    with get_session_factory()() as db:
        original = resolve_auth_context_from_token(db, state["login_token"], update_last_seen=False)
        before = original.session.last_seen_at
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lstrip().split()[0].upper())

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            delegated = resolve_official_auth_context(db, state["app_token"], logical_app_id="docs")
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert statements and set(statements) == {"SELECT"}
        assert delegated.user.id == original.user.id
        assert delegated.session.id == original.session.id
        assert delegated.system_roles == original.system_roles
        assert delegated.impersonator_user_id is None
        assert delegated.session.last_seen_at == before
        assert not db.new and not db.dirty and not db.deleted
        assert db.scalar(select(AuditLog).where(AuditLog.action == "official_app.binding.approve"))
        with pytest.raises(HTTPException):
            resolve_official_auth_context(db, state["login_token"], logical_app_id="docs")
        with pytest.raises(HTTPException):
            resolve_official_auth_context(db, state["app_token"], logical_app_id="files")
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {state['app_token']}"}
        ).status_code
        == 401
    )


def test_docs_and_pms_source_acl_parity_and_group_revocation(client, bound_official):
    state = bound_official
    with get_session_factory()() as db:
        document = NativeDoc(
            id=new_id(), owner_id=state["admin"]["user"]["id"], title="Private fixture"
        )
        team = Team(id=new_id(), key="official-fixture", name="Private fixture")
        db.add_all([document, team])
        db.flush()
        share = NativeDocGroupShare(
            doc_id=document.id,
            group_id=state["group_id"],
            access_level="read",
            created_by_id=state["admin"]["user"]["id"],
        )
        pms_binding = SpaceGroupBinding(team_id=team.id, group_id=state["group_id"], role="member")
        db.add_all([share, pms_binding])
        db.commit()
        # Mount the real owned HTTP routers in a test-only application. The
        # product's inactive artifact remains closed; no service is started.
        api = FastAPI()
        api.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
        register_api_routers(api, get_settings(), composition="official")
        paths = [f"/api/v1/docs/items/{document.id}", f"/api/v1/pms/spaces/{team.id}/lists"]

        def http_parity(*, allowed):
            with TestClient(api) as official:
                for path in paths:
                    legacy = client.get(
                        path, headers={"Authorization": f"Bearer {state['login_token']}"}
                    )
                    delegated = official.get(
                        path, headers={"Authorization": f"Bearer {state['app_token']}"}
                    )
                    assert legacy.status_code == delegated.status_code
                    assert (delegated.status_code == 200) is allowed

        http_parity(allowed=True)
        original = resolve_auth_context_from_token(db, state["login_token"], update_last_seen=False)
        delegated = resolve_official_auth_context(db, state["app_token"], logical_app_id="docs")
        for user in (original.user, delegated.user):
            access = resolve_native_doc_access(db, document, user)
            assert access.can_view and not access.can_edit and not access.can_manage
            assert resolve_pms_space_role(db, user, team) == "member"
        # Retain app admission, revoke only the original resource ACLs.
        db.delete(share)
        db.delete(pms_binding)
        db.commit()
        http_parity(allowed=False)
        delegated = resolve_official_auth_context(db, state["app_token"], logical_app_id="pms")
        for user in (original.user, delegated.user):
            assert not resolve_native_doc_access(db, document, user).can_view
            assert resolve_pms_space_role(db, user, team) is None


@pytest.mark.parametrize(
    "revocation",
    [
        "binding",
        "app_session",
        "source_session",
        "user",
        "password",
        "installation_group",
        "logical_group",
        "suite_company",
        "logical_company",
        "identity_permission",
        "generation",
        "artifact",
        "proof",
        "origin",
        "impersonation",
    ],
)
def test_current_authority_is_rechecked_for_every_delegated_request(bound_official, revocation):
    state = bound_official
    # Keep one Session alive across an independently committed revocation so
    # stale ORM identity-map state cannot accidentally authorize the next call.
    with get_session_factory()() as reader:
        assert resolve_official_auth_context(reader, state["app_token"], logical_app_id="docs")
        with get_session_factory()() as db:
            installation = db.get(AppInstallationRecord, state["installation"]["id"])
            if revocation == "binding":
                actor = resolve_auth_context_from_token(
                    db, state["admin"]["token"], update_last_seen=False
                )
                revoke_binding(db, actor, state["binding_id"])
            elif revocation == "app_session":
                db.get(AppSession, hash_token(state["app_token"])).revoked_at = utcnow_naive()
            elif revocation == "source_session":
                db.get(AuthSession, state["source_id"]).revoked_at = utcnow_naive()
            elif revocation == "user":
                db.get(User, state["member_id"]).login_blocked = True
            elif revocation == "password":
                db.get(User, state["member_id"]).must_change_password = True
            elif revocation == "installation_group":
                db.delete(
                    db.scalar(select(GroupMember).where(GroupMember.user_id == state["member_id"]))
                )
            elif revocation == "logical_group":
                db.get(AppAccessPolicy, "docs").audience = "selected"
                # User's installation group has no logical Docs app grant.
                assert (
                    db.scalar(select(AppGroupGrant).where(AppGroupGrant.app_id == "docs")) is None
                )
            elif revocation in {"suite_company", "logical_company"}:
                db.get(
                    CompanyAppControl,
                    "sample-independent" if revocation == "suite_company" else "docs",
                ).enabled = False
            elif revocation == "identity_permission":
                installation.granted_permissions = []
            elif revocation == "generation":
                installation.generation += 1
            elif revocation == "artifact":
                release = db.get(AppReleaseRecord, state["release_id"])
                release.artifact = "sha256:" + "b" * 64
                # Even otherwise matching verified evidence cannot replace the
                # artifact approved in this generation's immutable binding.
                db.get(
                    AppBuildVerification, release.verification_id
                ).artifact_digest = release.artifact
            elif revocation == "proof":
                db.get(
                    AppBuildVerification,
                    db.get(AppReleaseRecord, state["release_id"]).verification_id,
                ).revoked_at = utcnow_naive()
            elif revocation == "origin":
                installation.origin = "https://changed.test"
            else:
                db.get(AuthSession, state["source_id"]).impersonator_user_id = state["admin"][
                    "user"
                ]["id"]
            db.commit()
        with pytest.raises(HTTPException) as denied:
            resolve_official_auth_context(reader, state["app_token"], logical_app_id="docs")
        assert denied.value.status_code in {401, 403}


def test_approval_requires_current_admin_and_exact_verified_official_generation(bound_official):
    state = bound_official
    with get_session_factory()() as db:
        member = resolve_auth_context_from_token(db, state["login_token"], update_last_seen=False)
        kwargs = dict(
            installation_id=state["installation"]["id"],
            expected_generation=state["installation"]["generation"],
            expected_release_id=state["release_id"],
            expected_artifact="sha256:" + "a" * 64,
            logical_app_ids=frozenset({"docs"}),
        )
        with pytest.raises(HTTPException):
            approve_binding(db, member, **kwargs)
        actor = resolve_auth_context_from_token(db, state["admin"]["token"], update_last_seen=False)
        for replacement in (
            {"expected_generation": 999},
            {"expected_artifact": "sha256:" + "b" * 64},
            {"logical_app_ids": frozenset({"unknown"})},
            {"logical_app_ids": frozenset({"home"})},
        ):
            with pytest.raises(HTTPException):
                approve_binding(db, actor, **(kwargs | replacement))
        # Same-generation scope replacement is not an update operation.
        with pytest.raises(HTTPException):
            approve_binding(db, actor, **kwargs)
        assert db.scalar(select(OfficialAppBinding)).logical_app_ids == ["docs", "pms"]
        # A valid identity session alone, without a core binding, is insufficient.
        db.delete(db.get(OfficialAppBinding, state["binding_id"]))
        db.commit()
        with pytest.raises(HTTPException):
            resolve_official_auth_context(db, state["app_token"], logical_app_id="docs")


@pytest.mark.parametrize("revocation", ["session", "role"])
def test_approval_rechecks_authority_after_waiting_for_installation_lock(
    bound_official, revocation
):
    state = bound_official
    with get_session_factory()() as db:
        db.delete(db.get(OfficialAppBinding, state["binding_id"]))
        db.commit()
    waiting = Event()

    def approve():
        with get_session_factory()() as db:
            context = resolve_auth_context_from_token(
                db, state["admin"]["token"], update_last_seen=False
            )
            result = approve_binding(
                db,
                context,
                installation_id=state["installation"]["id"],
                expected_generation=state["installation"]["generation"],
                expected_release_id=state["release_id"],
                expected_artifact="sha256:" + "a" * 64,
                logical_app_ids=frozenset({"docs"}),
            )
            db.commit()
            return result.id

    def before_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if "independent_app_installations" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with get_session_factory()() as blocker:
        blocker.scalar(
            select(AppInstallationRecord)
            .where(AppInstallationRecord.id == state["installation"]["id"])
            .with_for_update()
        )
        event.listen(blocker.bind, "before_cursor_execute", before_lock)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(approve)
                try:
                    assert waiting.wait(5), "approval never reached its installation lock"
                    assert not pending.done()
                    with get_session_factory()() as revoked:
                        if revocation == "session":
                            source = revoked.scalar(
                                select(AuthSession).where(
                                    AuthSession.token_hash == hash_token(state["admin"]["token"])
                                )
                            )
                            source.revoked_at = utcnow_naive()
                        else:
                            revoked.execute(
                                delete(UserSystemRole).where(
                                    UserSystemRole.user_id == state["admin"]["user"]["id"],
                                    UserSystemRole.role == "platform_admin",
                                )
                            )
                        revoked.commit()
                finally:
                    blocker.rollback()
                with pytest.raises(HTTPException) as denied:
                    pending.result(timeout=5)
                assert denied.value.status_code in {401, 403}
        finally:
            event.remove(blocker.bind, "before_cursor_execute", before_lock)
    with get_session_factory()() as db:
        assert db.scalar(select(OfficialAppBinding)) is None


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
@pytest.mark.parametrize("operation", ["approve", "revoke", "resolve"])
def test_official_authority_refuses_revoked_snapshot_isolation(
    bound_official, isolation, operation
):
    state = bound_official
    if operation == "approve":
        with get_session_factory()() as db:
            db.delete(db.get(OfficialAppBinding, state["binding_id"]))
            db.commit()
    with get_session_factory()() as stale:
        # Pin a genuine older PostgreSQL snapshot, not just the ORM identity map.
        stale.execute(text("SET TRANSACTION ISOLATION LEVEL " + isolation))
        context = resolve_auth_context_from_token(
            stale, state["admin"]["token"], update_last_seen=False
        )
        with get_session_factory()() as revoked:
            if operation == "resolve":
                revoked.get(OfficialAppBinding, state["binding_id"]).revoked_at = utcnow_naive()
            else:
                revoked.execute(
                    delete(UserSystemRole).where(
                        UserSystemRole.user_id == state["admin"]["user"]["id"],
                        UserSystemRole.role == "platform_admin",
                    )
                )
            revoked.commit()
        with pytest.raises(HTTPException) as denied:
            if operation == "approve":
                approve_binding(
                    stale,
                    context,
                    installation_id=state["installation"]["id"],
                    expected_generation=state["installation"]["generation"],
                    expected_release_id=state["release_id"],
                    expected_artifact="sha256:" + "a" * 64,
                    logical_app_ids=frozenset({"docs"}),
                )
            elif operation == "revoke":
                revoke_binding(stale, context, state["binding_id"])
                stale.flush()
            else:
                resolve_official_auth_context(stale, state["app_token"], logical_app_id="docs")
        assert denied.value.status_code == 403
        assert not stale.new and not stale.dirty and not stale.deleted
    with get_session_factory()() as db:
        binding = db.get(OfficialAppBinding, state["binding_id"])
        if operation == "approve":
            assert binding is None
        elif operation == "revoke":
            assert binding.revoked_at is None
            assert (
                db.scalar(select(AuditLog).where(AuditLog.action == "official_app.binding.revoke"))
                is None
            )


@pytest.mark.parametrize("operation", ["approve", "revoke", "resolve"])
def test_official_authority_refuses_autocommit(bound_official, operation):
    state = bound_official
    with get_session_factory()() as normal:
        if operation == "approve":
            normal.delete(normal.get(OfficialAppBinding, state["binding_id"]))
            normal.commit()
        context = resolve_auth_context_from_token(
            normal, state["admin"]["token"], update_last_seen=False
        )
        engine = normal.get_bind().execution_options(isolation_level="AUTOCOMMIT")
        normal.expunge_all()
    with engine.connect() as connection, Session(bind=connection) as db:
        assert connection.connection.driver_connection.autocommit is True
        with pytest.raises(HTTPException) as denied:
            if operation == "approve":
                approve_binding(
                    db,
                    context,
                    installation_id=state["installation"]["id"],
                    expected_generation=state["installation"]["generation"],
                    expected_release_id=state["release_id"],
                    expected_artifact="sha256:" + "a" * 64,
                    logical_app_ids=frozenset({"docs"}),
                )
            elif operation == "revoke":
                revoke_binding(db, context, state["binding_id"])
            else:
                resolve_official_auth_context(db, state["app_token"], logical_app_id="docs")
        assert denied.value.status_code == 403
        assert not db.new and not db.dirty and not db.deleted
    with get_session_factory()() as db:
        binding = db.get(OfficialAppBinding, state["binding_id"])
        if operation == "approve":
            assert binding is None
        else:
            assert binding.revoked_at is None
        assert (
            db.scalar(select(AuditLog).where(AuditLog.action == "official_app.binding.revoke"))
            is None
        )


@pytest.mark.parametrize("revocation", ["session", "role"])
def test_binding_revoke_rechecks_admin_after_binding_lock_wait(bound_official, revocation):
    state = bound_official
    waiting = Event()

    def revoke():
        with get_session_factory()() as db:
            context = resolve_auth_context_from_token(
                db, state["admin"]["token"], update_last_seen=False
            )
            revoke_binding(db, context, state["binding_id"])
            db.commit()

    def before_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if "official_app_bindings" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with get_session_factory()() as blocker:
        blocker.scalar(
            select(OfficialAppBinding)
            .where(OfficialAppBinding.id == state["binding_id"])
            .with_for_update()
        )
        event.listen(blocker.bind, "before_cursor_execute", before_lock)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(revoke)
                try:
                    assert waiting.wait(5), "revocation never reached its binding lock"
                    assert not pending.done()
                    with get_session_factory()() as revoked:
                        if revocation == "session":
                            source = revoked.scalar(
                                select(AuthSession).where(
                                    AuthSession.token_hash == hash_token(state["admin"]["token"])
                                )
                            )
                            source.revoked_at = utcnow_naive()
                        else:
                            revoked.execute(
                                delete(UserSystemRole).where(
                                    UserSystemRole.user_id == state["admin"]["user"]["id"],
                                    UserSystemRole.role == "platform_admin",
                                )
                            )
                        revoked.commit()
                finally:
                    blocker.rollback()
                with pytest.raises(HTTPException) as denied:
                    pending.result(timeout=5)
                assert denied.value.status_code in {401, 403}
        finally:
            event.remove(blocker.bind, "before_cursor_execute", before_lock)
    with get_session_factory()() as db:
        assert db.get(OfficialAppBinding, state["binding_id"]).revoked_at is None
        assert (
            db.scalar(select(AuditLog).where(AuditLog.action == "official_app.binding.revoke"))
            is None
        )
