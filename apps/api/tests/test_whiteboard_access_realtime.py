from __future__ import annotations

import asyncio

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from dev_accounts import dev_login
from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import CompanyAppControl, User, AuthSession
from miy_api.domains.whiteboard.router import _authorize_whiteboard_collab_access


def _setup(client: TestClient):
    owner = dev_login(client, "delivery-hub-admin")
    viewer = dev_login(client, "delivery-hub-member")
    headers = {"Authorization": f"Bearer {owner['token']}"}
    response = client.post("/api/v1/whiteboard/items", headers=headers, json={"title": "Board"})
    assert response.status_code == 201, response.text
    return owner, viewer, headers, response.json()["id"]


def _capture(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    events: list[tuple[str, dict]] = []
    globals_sent = []
    monkeypatch.setattr(client.app.state.app_realtime, "publish", lambda *args: events.append(args))
    monkeypatch.setattr(
        client.app.state.app_realtime, "publish_user", lambda *args: globals_sent.append(args)
    )
    return events, globals_sent


def _assert_event(events, globals_sent, board_id: str):
    assert events == [
        (
            f"whiteboard.access:{board_id}",
            {"type": "whiteboard.access.changed", "data": {"whiteboard_id": board_id}},
        )
    ]
    assert globals_sent == []
    events.clear()


@pytest.mark.parametrize("revocation", ["source"])
def test_collab_frame_authorizer_rechecks_current_rights_without_waiting_for_monitor(
    client: TestClient, revocation: str
):
    _, viewer, headers, board_id = _setup(client)
    share_path = f"/api/v1/whiteboard/items/{board_id}/sharing/users/{viewer['user']['id']}"
    response = client.put(share_path, headers=headers, json={"access_level": "edit"})
    assert response.status_code == 200, response.text

    def authorize():
        asyncio.run(_authorize_whiteboard_collab_access(item_id=board_id, token=viewer["token"]))

    authorize()
    if revocation == "source":
        response = client.put(share_path, headers=headers, json={"access_level": "read"})
        assert response.status_code == 200, response.text
    else:
        with get_session_factory()() as db:
            if revocation == "app":
                db.get(CompanyAppControl, "whiteboard").enabled = False
            elif revocation == "user":
                db.get(User, viewer["user"]["id"]).login_blocked = True
            else:
                for session in db.scalars(
                    select(AuthSession).where(AuthSession.user_id == viewer["user"]["id"])
                ):
                    db.delete(session)
            db.commit()
    with pytest.raises(HTTPException) as exc:
        authorize()
    assert exc.value.status_code in (401, 403, 404)


def test_acl_change_commits_only_board_invalidation(client, monkeypatch):
    _, viewer, headers, board_id = _setup(client)
    events, globals_sent = _capture(client, monkeypatch)
    path = f"/api/v1/whiteboard/items/{board_id}/sharing/users/{viewer['user']['id']}"
    denied = client.put(
        path, headers={"Authorization": f"Bearer {viewer['token']}"}, json={"access_level": "edit"}
    )
    assert denied.status_code == 404 and events == [] and globals_sent == []
    assert client.put(path, headers=headers, json={"access_level": "edit"}).status_code == 200
    _assert_event(events, globals_sent, board_id)

    def committed(topic, event):
        from miy_api.domains.whiteboard.models import WhiteboardUserShare

        with get_session_factory()() as db:
            assert (
                db.scalar(
                    select(WhiteboardUserShare).where(
                        WhiteboardUserShare.whiteboard_id == board_id,
                        WhiteboardUserShare.user_id == viewer["user"]["id"],
                    )
                )
                is None
            )
        events.append((topic, event))

    monkeypatch.setattr(client.app.state.app_realtime, "publish", committed)
    assert client.delete(path, headers=headers).status_code == 200
    _assert_event(events, globals_sent, board_id)
