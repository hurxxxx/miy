from sqlalchemy import select

from dev_accounts import auth_headers, create_company_user_session, dev_login
from miy_api.core.db import get_session_factory
from miy_api.domains.groups.models import GroupMember
from miy_api.domains.groups.service import current_group_ids


def _auth_headers(token):
    return auth_headers(token)


def _bootstrap_admin_session(client):
    return dev_login(client)


def _group(client, headers, name="Review Group"):
    response = client.post("/api/v1/admin/groups", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _replace(client, headers, group_id, user_ids):
    return client.put(
        f"/api/v1/admin/groups/{group_id}/members", headers=headers, json={"user_ids": user_ids}
    )


def test_invalid_member_replace_is_atomic_and_valid_replace_deduplicates(client):
    member = create_company_user_session(
        client, login_id="atomic-member", email="atomic@example.test", full_name="Atomic Member"
    )
    admin = dev_login(client)
    headers = auth_headers(admin["token"])
    group = _group(client, headers)
    user_id = member["user"]["id"]
    response = _replace(client, headers, group["id"], [user_id, user_id])
    assert response.status_code == 200, response.text
    assert response.json()["user_ids"] == [user_id]
    response = _replace(client, headers, group["id"], ["missing-user"])
    assert response.status_code == 400, response.text
    response = client.get(f"/api/v1/admin/groups/{group['id']}/members", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["user_ids"] == [user_id]
    with get_session_factory()() as db:
        assert group["id"] in current_group_ids(db, user_id)
    response = client.patch(
        f"/api/v1/admin/groups/{group['id']}",
        headers=headers,
        json={"active": False},
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        assert group["id"] not in current_group_ids(db, user_id)
        assert (
            db.scalar(
                select(GroupMember).where(
                    GroupMember.group_id == group["id"],
                    GroupMember.user_id == user_id,
                )
            )
            is not None
        )
