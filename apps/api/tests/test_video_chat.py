from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
import pytest

from test_meeting import (
    _auth_headers as _auth_headers,
    _bootstrap_admin_session as _bootstrap_admin_session,
    _create_company_user as _create_company_user,
    _login as _login,
)


@pytest.fixture(autouse=True)
def _clear_livekit_public_url(monkeypatch: pytest.MonkeyPatch):
    from miy_api.core.settings import get_settings

    monkeypatch.setenv("MIY_LIVEKIT_PUBLIC_URL", "")
    monkeypatch.setenv("MIY_VIDEO_CHAT_ROOM_PREFIX", "miy")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    assert len(parts) == 3
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))


def _create_video_session(client: TestClient, token: str, title: str) -> dict:
    response = client.post(
        "/api/v1/video-chat/sessions",
        headers=_auth_headers(token),
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_video_chat_session_create_list_and_join_token(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)

    session = _create_video_session(
        client,
        admin["token"],
        "LiveKit validation",
    )

    assert session["title"] == "LiveKit validation"
    assert session["status"] == "open"
    assert session["provider"] == "livekit"
    assert session["meeting_id"] is None
    assert session["room_name"].startswith("miy-")

    listed = client.get(
        "/api/v1/video-chat/sessions",
        headers=_auth_headers(admin["token"]),
    )
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [session["id"]]

    token_response = client.post(
        f"/api/v1/video-chat/sessions/{session['id']}/join-token",
        headers=_auth_headers(admin["token"]),
    )
    assert token_response.status_code == 200, token_response.text
    body = token_response.json()
    claims = _decode_jwt_payload(body["token"])
    assert body["livekit_url"] == "ws://127.0.0.1:7880"
    assert claims["iss"] == "devkey"
    assert body["identity"] == claims["sub"]
    assert claims["sub"].startswith(f"{admin['user']['id']}:")
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == session["room_name"]
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is True
    second = client.post(
        f"/api/v1/video-chat/sessions/{session['id']}/join-token",
        headers=_auth_headers(admin["token"]),
    )
    assert second.status_code == 200
    assert _decode_jwt_payload(second.json()["token"])["sub"] != claims["sub"]
    member = _create_company_user(
        client, admin["token"], email="video-member@miy.local", full_name="Video Member"
    )
    member_token = _login(client, member["user"]["email"], member["temporary_password"])
    refused = client.post(
        f"/api/v1/video-chat/sessions/{session['id']}/end",
        headers=_auth_headers(member_token),
    )
    assert refused.status_code == 403
    assert refused.headers["X-MIY-Error-Code"] == "video_chat.host_required"
    assert (
        client.get(
            f"/api/v1/video-chat/sessions/{session['id']}", headers=_auth_headers(admin["token"])
        ).json()["status"]
        == "open"
    )
    ended = client.post(
        f"/api/v1/video-chat/sessions/{session['id']}/end", headers=_auth_headers(admin["token"])
    )
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    denied = client.post(
        f"/api/v1/video-chat/sessions/{session['id']}/join-token",
        headers=_auth_headers(admin["token"]),
    )
    assert denied.status_code == 409
    assert denied.headers["X-MIY-Error-Code"] == "video_chat.session_closed"


def test_video_chat_join_token_prefers_configured_public_livekit_url(
    client: TestClient,
    monkeypatch,
) -> None:
    from miy_api.core.settings import get_settings

    monkeypatch.setenv("MIY_LIVEKIT_PUBLIC_URL", "wss://video.example.test")
    get_settings.cache_clear()
    try:
        admin = _bootstrap_admin_session(client)
        session = _create_video_session(client, admin["token"], "Public URL")

        token_response = client.post(
            f"/api/v1/video-chat/sessions/{session['id']}/join-token",
            headers={**_auth_headers(admin["token"]), "Host": "100.87.48.58:4200"},
        )

        assert token_response.status_code == 200, token_response.text
        assert token_response.json()["livekit_url"] == "wss://video.example.test"
    finally:
        get_settings.cache_clear()
