from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import select
from test_meeting import _auth_headers, _dev_login

from miy_api.core.db import get_session_factory
from miy_api.core.i18n import LocalizedApiMessage
from miy_api.core.llm_adapters import StreamChunk
from miy_api.domains.ai import agent as ai_agent
from miy_api.domains.ai import approvals as ai_approvals
from miy_api.domains.ai import router as ai_router
from miy_api.domains.ai import tool_service as ai_tool_service
from miy_api.domains.ai.registry import (
    AiCapabilityRegistry,
    ApprovalPreview,
    PreviewField,
)
from miy_api.domains.ai.tool_runtime import ToolCallExecution
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.conversations import service as conversations_service

pytestmark = pytest.mark.usefixtures("configured_local_llm_control_plane")


def _ai_path(suffix: str) -> str:
    return f"/api/v1/chatbot{suffix}"


def _legacy_ai_path(suffix: str) -> str:
    return f"/api/v1/workspaces/retired/chatbot{suffix}"


def _parse_sse(body: str) -> list[dict[str, Any]]:
    normalized = body.replace("\r\n", "\n")
    events: list[dict[str, Any]] = []
    for block in normalized.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        data_str: str | None = None
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_str = line[len("data:") :].strip()
        if data_str is None:
            continue
        events.append(json.loads(data_str))
    return events


_APPROVAL_TOOL_NAME = "test.approval_write"
_SECOND_APPROVAL_TOOL_NAME = "test.second_write"


class _ApprovalToolArgs(BaseModel):
    title: str


def _approval_tool_handler(
    db: Any,
    principal: Any,
    user: Any,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    del db, principal, user
    title = str(arguments["title"])
    slug = title.lower().replace(" ", "-")
    return {
        "id": f"approval-{slug}",
        "title": title,
    }


def _approval_preview_builder(
    principal: Any,
    parsed_args: BaseModel | dict[str, Any],
) -> ApprovalPreview:
    del principal
    if isinstance(parsed_args, BaseModel):
        title = str(getattr(parsed_args, "title"))
    else:
        title = str(parsed_args.get("title") or "Untitled")
    return ApprovalPreview(
        title="Approval Test Write",
        summary="Creates an approval-gated test resource.",
        fields=(PreviewField(label="Title", value=title),),
    )


def _build_test_approval_registry(
    *,
    handler: Any = _approval_tool_handler,
    include_second_tool: bool = False,
) -> AiCapabilityRegistry:
    registry = AiCapabilityRegistry()
    registry.register_discoverability_predicate(
        predicate_id="test.enabled",
        predicate=lambda principal, entitlements: True,
    )
    registry.register_preview_builder(
        preview_builder_id="test.preview",
        builder=_approval_preview_builder,
    )
    registry.register_tool(
        name=_APPROVAL_TOOL_NAME,
        description="Approval-gated test write tool.",
        owner_domain="test",
        approval_required=True,
        handler=handler,
        args_model=_ApprovalToolArgs,
        mode="write",
        discoverability_predicate_id="test.enabled",
        preview_builder_id="test.preview",
        # owner_domain is a synthetic test value; pin the owner_app_id to
        # a registered company app so the registry validation passes.
        owner_app_id="chatbot",
    )
    if include_second_tool:
        registry.register_tool(
            name=_SECOND_APPROVAL_TOOL_NAME,
            description="Second approval-gated test write tool.",
            owner_domain="test",
            approval_required=True,
            handler=handler,
            args_model=_ApprovalToolArgs,
            mode="write",
            discoverability_predicate_id="test.enabled",
            preview_builder_id="test.preview",
            owner_app_id="chatbot",
        )
    registry.compile_capabilities()
    return registry


def _patch_test_approval_registry(
    monkeypatch: pytest.MonkeyPatch,
    registry: AiCapabilityRegistry,
) -> None:
    monkeypatch.setattr(ai_tool_service, "get_ai_capability_registry", lambda: registry)
    monkeypatch.setattr(ai_router, "get_ai_capability_registry", lambda: registry)


def _seed_pending_approval(
    client: TestClient,
    *,
    expires_at: datetime | None = None,
    tool_name: str = "pms.create_task",
    arguments_json: str = '{"title":"Approval issue"}',
    resource_preview: str = "Create PMS issue Approval issue",
    model_meta: dict[str, Any] | None = None,
) -> dict[str, str]:
    session = _dev_login(client, "delivery-hub-admin")

    with get_session_factory()() as db:
        user = load_user_graph(db, session["user"]["id"])
        assert user is not None

        conversation = conversations_service.create_conversation(
            db,
            user=user,
            title="approval test",
        )
        snapshot = ai_approvals.persist_snapshot_on_halt(
            db,
            conversation=conversation,
            requested_by_user=user,
            messages_json=[{"role": "user", "content": "create an issue"}],
            blocked_call_id="call-1",
            model_meta=model_meta
            or {
                "model": "local/current-moe-test-model",
                "provider": "local",
                "policy": "local_only",
                "chosen_pool": "local",
                "parallel_tool_calls": False,
                "temperature": 0.2,
                "max_output_tokens": 4096,
            },
        )
        approval = ai_approvals.create_pending_approval(
            db,
            conversation=conversation,
            requested_by_user=user,
            agent_run_id=snapshot.id,
            tool_call_id="call-1",
            tool_name=tool_name,
            arguments_json=arguments_json,
            resource_preview=resource_preview,
            expires_at=expires_at,
        )
        db.commit()

        return {
            "token": session["token"],
            "user_id": user.id,
            "conversation_id": conversation.id,
            "approval_id": approval.id,
            "agent_run_id": snapshot.id,
        }


def test_resume_allowed_app_ids_rejects_wider_scope() -> None:
    snapshot = ai_approvals.AgentRunSnapshot(
        id="snapshot-1",
        conversation_id="conversation-1",
        requested_by_user_id="user-1",
        blocked_call_id="call-1",
        model_meta={"scope": {"allowed_app_ids": ["pms"]}},
    )

    with pytest.raises(HTTPException) as exc_info:
        ai_approvals.resolve_resume_allowed_app_ids(snapshot, ["pms", "docs"])
    assert isinstance(exc_info.value.detail, LocalizedApiMessage)
    assert exc_info.value.detail.code == "ai.resume_scope_wider"


def test_chat_resume_replays_rejected_tool_without_running_handler(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_calls: list[dict[str, Any]] = []

    def handler(
        db: Any,
        principal: Any,
        user: Any,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del db, principal, user
        handler_calls.append(arguments)
        return {"id": "unexpected", "title": arguments["title"]}

    registry = _build_test_approval_registry(handler=handler)
    _patch_test_approval_registry(monkeypatch, registry)
    seed = _seed_pending_approval(
        client,
        tool_name=_APPROVAL_TOOL_NAME,
        resource_preview="Approval Test Write\nCreates an approval-gated test resource.\nTitle: Approval issue",
    )
    headers = _auth_headers(seed["token"])
    administrator = _dev_login(client, "administrator")
    assert (
        client.get(
            _ai_path(f"/runtime/runs/{seed['agent_run_id']}"),
            headers=_auth_headers(administrator["token"]),
        ).status_code
        == 404
    )
    other = _dev_login(client, "delivery-hub-member")
    forbidden = client.post(
        _ai_path(f"/approvals/{seed['approval_id']}/resolve"),
        headers=_auth_headers(other["token"]),
        json={"decision": "approved"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ai.approval_different_user"
    pending = client.get(_ai_path(f"/approvals/{seed['approval_id']}"), headers=headers)
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    assert (
        client.get(f"/api/v1/ai/approvals/{seed['approval_id']}", headers=headers).status_code
        == 404
    )

    async def fake_complete_chat_stream(*args: Any, **kwargs: Any):
        del kwargs
        messages = args[0].messages
        assistant_calls = [
            message
            for message in messages
            if message.get("role") == "assistant" and message.get("tool_calls")
        ]
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert len(assistant_calls) == 1
        assert len(tool_messages) == 1
        assert '"status": "rejected"' in tool_messages[0]["content"]
        yield (
            StreamChunk(kind="content", text="승인이 거절되어 실행하지 않았습니다."),
            None,
            None,
        )
        yield (
            StreamChunk(kind="done", finish_reason="stop"),
            None,
            None,
        )

    monkeypatch.setattr(
        ai_agent,
        "complete_resolved_gateway_chat_stream",
        fake_complete_chat_stream,
    )

    resolve_response = client.post(
        _ai_path(f"/approvals/{seed['approval_id']}/resolve"),
        headers=headers,
        json={"decision": "rejected", "reason": "not now"},
    )
    assert resolve_response.status_code == 200, resolve_response.text

    response = client.post(
        _ai_path("/chat/resume"),
        headers=headers,
        json={
            "conversation_id": seed["conversation_id"],
            "approval_id": seed["approval_id"],
        },
    )

    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert [event["type"] for event in events] == [
        "approval_resolved",
        "tool_result",
        "content_delta",
        "done",
    ]
    assert events[0]["data"] == {
        "approval_id": seed["approval_id"],
        "call_id": "call-1",
        "decision": "rejected",
        "reason": "not now",
    }
    assert events[1]["data"]["status"] == "rejected"
    assert events[2]["data"]["text"] == "승인이 거절되어 실행하지 않았습니다."
    assert not handler_calls

    with get_session_factory()() as db:
        approval = db.scalar(
            select(ai_approvals.AiToolApproval).where(
                ai_approvals.AiToolApproval.id == seed["approval_id"]
            )
        )
        snapshot = ai_approvals.load_snapshot(db, agent_run_id=seed["agent_run_id"])
        assert approval is not None
        assert approval.status == "rejected"
        assert json.loads(approval.execution_result_json or "{}") == {
            "status": "rejected",
            "reason": "not now",
        }
        assert snapshot.status == "completed"


def test_chat_resume_cancellation_after_tool_exec_does_not_rewind(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If cancel fires AFTER the approved tool executed, the snapshot must not
    rewind to awaiting_approval — otherwise a second resume would re-run the
    write and double its side effects.
    """
    seed = _seed_pending_approval(client)
    headers = _auth_headers(seed["token"])

    resolve_response = client.post(
        _ai_path(f"/approvals/{seed['approval_id']}/resolve"),
        headers=headers,
        json={"decision": "approved"},
    )
    assert resolve_response.status_code == 200, resolve_response.text

    def fake_execute_tool_call(*args: Any, **kwargs: Any) -> ToolCallExecution:
        del args, kwargs
        return ToolCallExecution(
            call_id="call-1",
            tool_name="pms.create_task",
            arguments_json='{"title":"ok"}',
            status="ok",
            response={"tool": "pms.create_task", "result": {"ok": True}},
        )

    def fake_iter_tool_call_events(*args: Any, **kwargs: Any):
        del args, kwargs
        raise asyncio.CancelledError

    monkeypatch.setattr(ai_agent, "execute_tool_call", fake_execute_tool_call)
    monkeypatch.setattr(ai_agent, "iter_tool_call_events", fake_iter_tool_call_events)

    response = client.post(
        _ai_path("/chat/resume"),
        headers=headers,
        json={
            "conversation_id": seed["conversation_id"],
            "approval_id": seed["approval_id"],
        },
    )

    assert response.status_code == 200, response.text

    with get_session_factory()() as db:
        approval = db.scalar(
            select(ai_approvals.AiToolApproval).where(
                ai_approvals.AiToolApproval.id == seed["approval_id"]
            )
        )
        snapshot = ai_approvals.load_snapshot(db, agent_run_id=seed["agent_run_id"])
        assert approval is not None
        # Tool already ran — snapshot must be completed (no re-execute path).
        assert snapshot.status == "completed"

    second_resume = client.post(
        _ai_path("/chat/resume"),
        headers=headers,
        json={
            "conversation_id": seed["conversation_id"],
            "approval_id": seed["approval_id"],
        },
    )
    assert second_resume.status_code == 410, second_resume.text
    assert second_resume.json()["code"] == "ai.agent_run_snapshot_not_resumable"
