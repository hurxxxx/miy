from fastapi.testclient import TestClient


def test_account_setup_admission_logout_then_signup_without_business_membership(
    client: TestClient,
) -> None:
    status_response = client.get("/api/v1/auth/bootstrap-status")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "requires_setup": True,
        "dev_admin_login_available": True,
        "dev_login_accounts": [],
    }

    unauthenticated = client.get("/api/v1/retrieval/sources")
    assert unauthenticated.status_code == 401

    setup_response = client.post(
        "/api/v1/auth/setup",
        json={
            "full_name": "miy Admin",
            "email": "admin@miy.local",
            "password": "supersecret123",
        },
    )
    assert setup_response.status_code == 201
    auth_payload = setup_response.json()
    assert "platform_admin" in auth_payload["user"]["system_roles"]
    assert auth_payload["user"]["theme_preference"] == "system"
    assert auth_payload["user"]["locale"] == "ko-KR"
    assert auth_payload["user"]["time_zone"] == "Asia/Seoul"
    assert auth_payload["user"]["date_format"] == "korean"
    assert auth_payload["user"]["app_bar_layout"] == {
        "pinned_app_ids": ["pms", "docs", "whiteboard"],
    }
    assert "default_workspace_id" not in auth_payload["user"]
    assert auth_payload["user"]["login_id"] == "admin"
    assert "workspaces" not in auth_payload["user"]
    _assert_user_has_no_business_memberships(auth_payload["user"]["id"])
    assert "workspace_roles" not in auth_payload["user"]
    assert "app_access" not in auth_payload["user"]
    token = auth_payload["token"]

    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "admin@miy.local"

    denied_retrieval_response = client.get(
        "/api/v1/retrieval/sources",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied_retrieval_response.status_code == 403

    from dev_accounts import configure_company_app_access
    from miy_api.core.db import get_session_factory

    with get_session_factory()() as db:
        configure_company_app_access(db)
    retrieval_response = client.get(
        "/api/v1/retrieval/sources",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retrieval_response.status_code == 200
    assert isinstance(retrieval_response.json()["sources"], list)

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_response.status_code == 204

    expired_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert expired_response.status_code == 401

    signup_response = client.post(
        "/api/v1/auth/signup",
        json={
            "full_name": "New Member",
            "login_id": "new-member",
            "email": "NEW@miy.local",
            "password": "memberpass123",
            "password_confirm": "memberpass123",
        },
    )
    assert signup_response.status_code == 201, signup_response.text
    signup_body = signup_response.json()
    assert signup_body["user"]["login_id"] == "new-member"
    assert signup_body["user"]["email"] == "new@miy.local"
    assert signup_body["user"]["system_roles"] == []
    assert "workspaces" not in signup_body["user"]
    _assert_user_has_no_business_memberships(signup_body["user"]["id"])

    login_response = client.post(
        "/api/v1/auth/login",
        json={"login_id": "new-member", "password": "memberpass123"},
    )
    assert login_response.status_code == 200, login_response.text


def test_generic_request_validation_error_preserves_dynamic_constraints(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Accept-Language": "en-US"},
        json={"login_id": "admin", "password": "short"},
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"] == "Request validation failed."
    assert body["code"] == "validation.request_invalid"
    assert body["validation"][0]["loc"] == ["body", "password"]
    assert body["validation"][0]["type"] == "string_too_short"
    assert body["validation"][0]["message"] == "Value is too short. Minimum length: 8"


def test_session_revocation_and_password_rotation_reject_previous_credentials(
    client: TestClient,
) -> None:
    token = _bootstrap_admin(client)

    sessions_response = client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sessions_response.status_code == 200
    session_id = sessions_response.json()["items"][0]["id"]
    assert sessions_response.json()["items"][0]["is_current"] is True

    revoke_response = client.post(
        f"/api/v1/auth/sessions/{session_id}/revoke",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_response.status_code == 204

    revoked_me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoked_me_response.status_code == 401

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "login_id": "admin",
            "password": "supersecret123",
        },
    )
    assert login_response.status_code == 200
    replacement_token = login_response.json()["token"]

    password_response = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {replacement_token}"},
        json={
            "current_password": "supersecret123",
            "new_password": "newsupersecret123",
            "new_password_confirm": "newsupersecret123",
        },
    )
    assert password_response.status_code == 204

    old_login_response = client.post(
        "/api/v1/auth/login",
        json={
            "login_id": "admin",
            "password": "supersecret123",
        },
    )
    assert old_login_response.status_code == 401

    new_login_response = client.post(
        "/api/v1/auth/login",
        json={
            "login_id": "admin",
            "password": "newsupersecret123",
        },
    )
    assert new_login_response.status_code == 200


def _bootstrap_admin(client: TestClient) -> str:
    from test_meeting import _bootstrap_admin_session

    return _bootstrap_admin_session(client)["token"]


def _assert_user_has_no_business_memberships(user_id: str) -> None:
    from sqlalchemy import select
    from miy_api.core.db import get_session_factory
    from miy_api.domains.pms.space_models import TeamMember
    from miy_api.domains.groups.models import GroupMember

    with get_session_factory()() as db:
        assert db.scalar(select(TeamMember.id).where(TeamMember.user_id == user_id)) is None
        assert db.scalar(select(GroupMember.user_id).where(GroupMember.user_id == user_id)) is None


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"login_id": email.split("@", 1)[0].lower(), "password": password},
    )
    assert response.status_code == 200
    return response.json()["token"]


def _create_direct_user(
    *,
    email: str,
    full_name: str,
    password: str = "supersecret123",
    is_admin: bool = False,
    system_roles: tuple[str, ...] = (),
) -> tuple[str, str]:

    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.models import AuthSession, User, UserSystemRole
    from miy_api.domains.auth.security import (
        hash_password,
        issue_session_token,
        new_id,
        normalize_email,
    )

    session_token = issue_session_token(ttl_hours=1)
    user_id = new_id()
    db = get_session_factory()()
    try:
        db.add(
            User(
                id=user_id,
                login_id=normalize_email(email).split("@", 1)[0],
                email=normalize_email(email),
                full_name=full_name,
                display_name=full_name,
                password_hash=hash_password(password),
                status="active",
            )
        )
        for role in {*(system_roles or ()), *(("platform_admin",) if is_admin else ())}:
            db.add(
                UserSystemRole(
                    id=new_id(),
                    user_id=user_id,
                    role=role,
                )
            )
        db.add(
            AuthSession(
                id=new_id(),
                user_id=user_id,
                token_hash=session_token.token_hash,
                expires_at=session_token.expires_at,
            )
        )
        db.commit()
    finally:
        db.close()

    return user_id, session_token.plain_text


def _create_pms_task_list(
    client: TestClient,
    token: str,
    *,
    key: str,
    name: str,
) -> dict[str, object]:
    space = client.post(
        "/api/v1/pms/spaces", headers={"Authorization": f"Bearer {token}"}, json={"name": name}
    )
    assert space.status_code == 201, space.text
    response = client.post(
        "/api/v1/pms/lists",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "team_id": space.json()["id"],
            "key": key,
            "name": name,
            "description": f"{name} description",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_pms_task(
    client: TestClient,
    token: str,
    list_id: str,
    *,
    title: str,
    parent_id: str | None = None,
    status: str = "todo",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": title,
            "description": f"{title} description",
            "status": status,
            "priority": "medium",
            "parent_id": parent_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_pms_space_owner_has_no_company_group_administration(client: TestClient) -> None:
    _bootstrap_admin(client)
    user_id, token = _create_direct_user(email="space-owner@example.test", full_name="Space Owner")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/api/v1/pms/spaces", headers=headers, json={"name": "Project Space"})
    assert response.status_code == 201, response.text
    assert response.json()["current_user_role"] == "owner"
    denied = client.post(
        "/api/v1/admin/groups", headers=headers, json={"name": "Unauthorised company group"}
    )
    assert denied.status_code == 403, denied.text
    denied = client.get("/api/v1/admin/users", headers=headers)
    assert denied.status_code == 403, denied.text


def test_company_app_grant_does_not_grant_other_apps(client: TestClient) -> None:
    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant

    _bootstrap_admin(client)
    user_id, token = _create_direct_user(
        email="selected-user@example.test", full_name="Selected User"
    )
    with get_session_factory()() as db:
        for app_id in ("docs", "whiteboard"):
            db.get(AppAccessPolicy, app_id).audience = "selected"
        db.add(AppUserGrant(app_id="docs", user_id=user_id))
        db.commit()
    headers = {"Authorization": f"Bearer {token}"}
    allowed = client.get("/api/v1/docs/hub", headers=headers)
    denied = client.get("/api/v1/whiteboard/hub", headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert denied.status_code == 403, denied.text


def test_pms_space_creator_becomes_owner_and_last_manager_is_protected(client: TestClient) -> None:
    _bootstrap_admin(client)
    creator_id, creator_token = _create_direct_user(
        email="space-creator@miy.local",
        full_name="Space Creator",
    )

    create_space_response = client.post(
        "/api/v1/pms/spaces",
        headers={"Authorization": f"Bearer {creator_token}"},
        json={"name": "Operations", "description": "Owner bootstrap"},
    )
    assert create_space_response.status_code == 201
    space = create_space_response.json()

    members_response = client.get(
        f"/api/v1/pms/spaces/{space['id']}/members",
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert members_response.status_code == 200
    assert members_response.json()["items"][0]["user_id"] == creator_id
    assert members_response.json()["items"][0]["role"] == "owner"

    demote_response = client.patch(
        f"/api/v1/pms/spaces/{space['id']}/members/{creator_id}",
        headers={"Authorization": f"Bearer {creator_token}"},
        json={"role": "member"},
    )
    assert demote_response.status_code == 409

    remove_response = client.delete(
        f"/api/v1/pms/spaces/{space['id']}/members/{creator_id}",
        headers={"Authorization": f"Bearer {creator_token}"},
    )
    assert remove_response.status_code == 409


def test_platform_admin_reads_business_space_without_implicit_write_role(
    client: TestClient,
) -> None:
    owner_token = _bootstrap_admin(client)
    task_list = _create_pms_task_list(
        client, owner_token, key="READADMIN", name="Read administrator test"
    )
    _, admin_token = _create_direct_user(
        email="reader-admin@example.test", full_name="Read Admin", system_roles=("platform_admin",)
    )
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.get(f"/api/v1/pms/lists/{task_list['id']}", headers=headers)
    assert response.status_code == 200, response.text
    response = client.patch(
        f"/api/v1/pms/lists/{task_list['id']}", headers=headers, json={"name": "Unauthorized edit"}
    )
    assert response.status_code == 403, response.text


def test_app_grant_removal_revokes_existing_session_without_deleting_account(
    client: TestClient,
) -> None:
    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant

    _bootstrap_admin(client)
    user_id, token = _create_direct_user(email="revoked-app@example.test", full_name="Revoked App")
    with get_session_factory()() as db:
        db.get(AppAccessPolicy, "docs").audience = "selected"
        db.add(AppUserGrant(app_id="docs", user_id=user_id))
        db.commit()
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/docs/hub", headers=headers)
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        db.delete(db.get(AppUserGrant, ("docs", user_id)))
        db.commit()
    denied = client.get("/api/v1/docs/hub", headers=headers)
    assert denied.status_code == 403, denied.text
    current = client.get("/api/v1/auth/me", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["id"] == user_id
