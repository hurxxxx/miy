from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import CompanyAppControl

from test_meeting import _auth_headers, _bootstrap_admin_session, _create_company_user, _login


def _set_company_app_control(app_id: str, enabled: bool) -> None:
    with get_session_factory()() as db:
        row = db.scalar(select(CompanyAppControl).where(CompanyAppControl.app_id == app_id))
        assert row is not None
        row.enabled = enabled
        db.add(row)
        db.commit()


def _create_planner_event(
    client: TestClient,
    token: str,
    *,
    title: str = "출장",
    start: str,
    end: str,
    all_day: bool = False,
    location: str = "",
    description: str = "",
) -> dict:
    response = client.post(
        "/api/v1/planner/events",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": description,
            "location": location,
            "allDay": all_day,
            "start": start,
            "end": end,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_company_meeting(
    client: TestClient,
    token: str,
    *,
    title: str = "Sync",
    attendees: list[dict] | None = None,
    start_at: datetime,
    end_at: datetime,
) -> dict:
    response = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(token),
        json={
            "title": title,
            "agenda": "Discuss schedule.",
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "attendees": attendees or [],
            "task_ids": [],
            "doc_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_planner_event_owner_only_access(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)
    admin_token = admin["token"]
    member = _create_company_user(
        client,
        admin_token,
        email="planner-member@miy.local",
        full_name="Planner Member",
    )
    member_token = _login(client, member["user"]["email"], member["temporary_password"])

    created = _create_planner_event(
        client,
        admin_token,
        start="2026-05-04T01:00:00+00:00",
        end="2026-05-04T02:00:00+00:00",
    )

    forbidden_get = client.get(
        f"/api/v1/planner/events/{created['id']}",
        headers=_auth_headers(member_token),
    )
    assert forbidden_get.status_code == 404

    forbidden_patch = client.patch(
        f"/api/v1/planner/events/{created['id']}",
        headers=_auth_headers(member_token),
        json={"title": "가로채기"},
    )
    assert forbidden_patch.status_code == 404

    forbidden_delete = client.delete(
        f"/api/v1/planner/events/{created['id']}",
        headers=_auth_headers(member_token),
    )
    assert forbidden_delete.status_code == 404

    available = client.get(
        "/api/v1/meeting/availability",
        headers=_auth_headers(member_token),
        params=[
            ("user_ids", admin["user"]["id"]),
            ("from", "2026-05-04T00:00:00+00:00"),
            ("to", "2026-05-05T00:00:00+00:00"),
        ],
    )
    assert available.status_code == 200, available.text
    blocks = [
        block
        for block in available.json()["items"][0]["blocks"]
        if block["sourceType"] == "planner_event"
    ]
    assert len(blocks) == 1
    assert blocks[0]["masked"] is True
    assert blocks[0]["title"] is None and blocks[0]["location"] is None
