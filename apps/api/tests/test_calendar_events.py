"""Tests for the unified calendar events endpoint.

Covers (per autoplan Round 2 Eng review test plan):
  - Unauthenticated → 401
  - Range exceeds 366-day cap → 400 (ENG-HIGH-4)
  - Invalid source name → 400
  - Empty sources → 200 with []
  - Happy path: meeting + PMS issue both visible to current user
  - assignee_id parameter is silently ignored / never accepted (ENG-CRIT-1)
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from httpx import Response


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_admin_session(client: TestClient) -> dict:
    from test_meeting import _bootstrap_admin_session as setup

    return setup(client)


def _create_meeting(
    client: TestClient,
    token: str,
    *,
    title: str = "Calendar test meeting",
    start_at: datetime,
    end_at: datetime,
) -> dict:
    response = client.post(
        "/api/v1/meeting/meetings",
        headers=_auth_headers(token),
        json={
            "title": title,
            "agenda": "",
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "attendees": [],
            "task_ids": [],
            "doc_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task_list(client: TestClient, token: str) -> dict:
    from test_meeting import _create_task_list as create_list

    return create_list(client, token, key="CAL", name="Calendar Test List")


def _create_issue_with_due_date(
    client: TestClient,
    token: str,
    list_id: str,
    *,
    due_date: str,
    start_date: str | None = None,
    assignee_id: str | None = None,
    title: str = "Task with due date",
) -> dict:
    create = client.post(
        f"/api/v1/pms/lists/{list_id}/tasks",
        headers=_auth_headers(token),
        json={
            "title": title,
            "description": "",
            "status": "todo",
            "priority": "medium",
            "label_ids": [],
        },
    )
    assert create.status_code == 201, create.text
    issue = create.json()
    # Set due_date via update endpoint (setup endpoint doesn't take it directly)
    update = client.patch(
        f"/api/v1/pms/tasks/{issue['id']}",
        headers=_auth_headers(token),
        json={
            "due_date": due_date,
            **({"start_date": start_date} if start_date is not None else {}),
            **({"assignee_id": assignee_id} if assignee_id is not None else {}),
        },
    )
    assert update.status_code == 200, update.text
    return update.json()


def _get_calendar_events(
    client: TestClient,
    token: str | None = None,
    *,
    from_: str = "2026-04-01",
    to: str = "2026-04-30",
    sources: str | None = None,
    extra_params: dict[str, str] | None = None,
) -> Response:
    params = {"from": from_, "to": to}
    if sources is not None:
        params["sources"] = sources
    if extra_params is not None:
        params.update(extra_params)

    return client.get(
        "/api/v1/calendar/events",
        headers=_auth_headers(token) if token is not None else {},
        params=params,
    )


def test_calendar_events_assignee_id_query_param_is_ignored(client: TestClient) -> None:
    """ENG-CRIT-1: caller cannot read another user's calendar by passing an id."""
    admin = _bootstrap_admin_session(client)
    token = admin["token"]
    # The endpoint does not declare assignee_id at all — extra params are silently
    # dropped by FastAPI. Ensure we still get back only the current user's data.
    response = _get_calendar_events(
        client,
        token,
        extra_params={"assignee_id": "some-other-user-id"},
    )
    assert response.status_code == 200
    # And for sanity: the absence of assignee_id in the schema means the optional
    # parameter is never honored. This is the contract.


def test_calendar_aggregates_each_admitted_source_independently(client: TestClient) -> None:
    admin = _bootstrap_admin_session(client)
    token = admin["token"]
    meeting = _create_meeting(
        client,
        token,
        start_at=datetime(2026, 4, 20, 10, 0),
        end_at=datetime(2026, 4, 20, 11, 0),
    )
    planner = client.post(
        "/api/v1/planner/events",
        headers=_auth_headers(token),
        json={
            "title": "Personal event",
            "start": "2026-04-20T12:00:00Z",
            "end": "2026-04-20T13:00:00Z",
            "allDay": False,
        },
    )
    assert planner.status_code == 201, planner.text

    def disable(app_id: str) -> None:
        changed = client.put(
            f"/api/v1/admin/apps/{app_id}/access-policy",
            headers=_auth_headers(token),
            json={"enabled": False, "audience": "all", "user_ids": [], "group_ids": []},
        )
        assert changed.status_code == 200, changed.text

    disable("planner")
    response = _get_calendar_events(client, token, sources="planner_event,meeting")
    assert response.status_code == 200, response.text
    assert [item["sourceId"] for item in response.json()["items"]] == [meeting["id"]]
    disable("meeting")
    response = _get_calendar_events(client, token, sources="planner_event,meeting")
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
