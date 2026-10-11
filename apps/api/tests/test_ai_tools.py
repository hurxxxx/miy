from __future__ import annotations

import pytest
from dev_accounts import dev_login
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_pms_issues import _create_task_list

from miy_api.core.db import get_engine
from miy_api.core.principal import user_principal
from miy_api.core.settings import get_settings
from miy_api.domains.ai.registry import reset_ai_capability_registry
from miy_api.domains.ai.tool_service import execute_tool
from miy_api.domains.auth.models import AuditLog, CompanyAppControl, User


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tool_path(tool_name: str) -> str:
    return f"/api/v1/chatbot/tools/{tool_name}/invoke"


def _disable_platform_app(app_id: str) -> None:
    with Session(get_engine()) as session:
        control = session.scalar(
            select(CompanyAppControl).where(CompanyAppControl.app_id == app_id)
        )
        assert control is not None
        control.enabled = False
        session.add(control)
        session.commit()


def _tool_audit_rows() -> list[AuditLog]:
    with Session(get_engine()) as session:
        return list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.action == "llm_tool_call")
                .order_by(AuditLog.created_at.asc())
            ).all()
        )


def _reset_settings_and_registry() -> None:
    cache_clear = getattr(get_settings, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()
    reset_ai_capability_registry()


def test_pms_ai_write_rechecks_viewer_acl_after_external_approval(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MIY_AI_WRITE_TOOLS_ENABLED", "1")
    _reset_settings_and_registry()
    try:
        owner = _dev_login(client, "delivery-hub-admin")
        viewer = _dev_login(client, "knowledge-base-admin")
        task_list = _create_task_list(client, owner["token"])
        add_viewer_response = client.post(
            f"/api/v1/pms/spaces/{task_list['team_id']}/members",
            headers=_auth_headers(owner["token"]),
            json={"user_id": viewer["user"]["id"], "role": "viewer"},
        )
        assert add_viewer_response.status_code == 201, add_viewer_response.text
        task_response = client.post(
            f"/api/v1/pms/lists/{task_list['id']}/tasks",
            headers=_auth_headers(owner["token"]),
            json={"title": "Viewer cannot archive"},
        )
        assert task_response.status_code == 201, task_response.text
        task = task_response.json()

        with Session(get_engine()) as db:
            viewer_user = db.get(User, viewer["user"]["id"])
            assert viewer_user is not None
            with pytest.raises(HTTPException) as denied:
                execute_tool(
                    db,
                    principal=user_principal(
                        user_id=viewer_user.id,
                        source="test.pms.ai.viewer",
                    ),
                    user=viewer_user,
                    tool_name="pms.update_task",
                    arguments={"task_id": task["id"], "archived": True},
                    source="hermes-mcp",
                    externally_approved_call_id="approved-pms-viewer-archive",
                )
            assert denied.value.status_code == 403

        detail_response = client.get(
            f"/api/v1/pms/tasks/{task['id']}",
            headers=_auth_headers(owner["token"]),
        )
        assert detail_response.status_code == 200, detail_response.text
        assert detail_response.json()["task"]["archived"] is False
    finally:
        monkeypatch.delenv("MIY_AI_WRITE_TOOLS_ENABLED", raising=False)
        _reset_settings_and_registry()


def test_ai_tool_invoke_meeting_and_planner_write_tools_require_approval_when_enabled(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MIY_AI_WRITE_TOOLS_ENABLED", "1")
    _reset_settings_and_registry()
    try:
        session = _dev_login(client, "delivery-hub-admin")
        token = session["token"]

        meeting_response = client.post(
            _tool_path("meeting.create_meeting"),
            headers=_auth_headers(token),
            json={
                "arguments": {
                    "title": "AI gated meeting",
                    "start_at": "2026-05-10T01:00:00+00:00",
                    "end_at": "2026-05-10T02:00:00+00:00",
                }
            },
        )
        assert meeting_response.status_code == 409, meeting_response.text

        planner_response = client.post(
            _tool_path("planner.create_event"),
            headers=_auth_headers(token),
            json={
                "arguments": {
                    "title": "AI gated event",
                    "start_at": "2026-05-11T01:00:00+00:00",
                    "end_at": "2026-05-11T02:00:00+00:00",
                    "scope": "personal",
                }
            },
        )
        assert planner_response.status_code == 409, planner_response.text

        planner_update_response = client.post(
            _tool_path("planner.update_event"),
            headers=_auth_headers(token),
            json={
                "arguments": {
                    "event_id": "event-approval-target",
                    "title": "AI gated event update",
                }
            },
        )
        assert planner_update_response.status_code == 409, planner_update_response.text

        planner_delete_response = client.post(
            _tool_path("planner.delete_event"),
            headers=_auth_headers(token),
            json={"arguments": {"event_id": "event-approval-target"}},
        )
        assert planner_delete_response.status_code == 409, planner_delete_response.text
    finally:
        monkeypatch.delenv("MIY_AI_WRITE_TOOLS_ENABLED", raising=False)
        _reset_settings_and_registry()
