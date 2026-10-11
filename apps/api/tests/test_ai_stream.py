"""Route-level tests for admitted company users and personal AI chat streams."""

from __future__ import annotations

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from hermes_route_stub import hermes_route_stub  # noqa: F401
from openai import OpenAIError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_meeting import (
    _auth_headers,
    _bootstrap_admin_session,
    _create_company_user,
    _dev_login,
    _login,
)

from miy_api.core import llm as llm_core
from miy_api.core.db import get_engine, get_session_factory
from miy_api.core.llm_adapters import StreamChunk
from miy_api.core.settings import get_settings
from miy_api.domains.ai import agent as ai_agent
from miy_api.domains.ai import approvals as ai_approvals
from miy_api.domains.ai import router as ai_router
from miy_api.domains.ai.model_credentials import encrypt_api_key
from miy_api.domains.ai.model_settings_models import (
    AiModelCatalogEntry,
    AiModelPolicyDefault,
    AiModelProviderConfig,
)
from miy_api.domains.ai.registry import get_ai_capability_registry
from miy_api.domains.auth.models import AuditLog, User
from miy_api.domains.conversations.scope_registry import (
    ConversationScopeArtifact,
    ConversationScopeTurnContext,
)

pytestmark = pytest.mark.usefixtures("hermes_route_stub")


@pytest.fixture(autouse=True)
def _bridge_registered_client_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep route tests' fake clients while registered workloads pass exact config."""

    original_sync_getter = llm_core.get_pool_client
    original_sync_factory = llm_core._new_pool_client
    original_getter = llm_core.get_async_pool_client
    original_factory = llm_core._new_async_pool_client

    def sync_factory(config):  # type: ignore[no-untyped-def]
        current_getter = llm_core.get_pool_client
        if current_getter is original_sync_getter:
            return original_sync_factory(config)
        return current_getter(
            config.pool,
            external_provider=(config.provider if config.pool == "external" else None),
        )

    def factory(config):  # type: ignore[no-untyped-def]
        current_getter = llm_core.get_async_pool_client
        if current_getter is original_getter:
            return original_factory(config)
        return current_getter(
            config.pool,
            external_provider=(config.provider if config.pool == "external" else None),
        )

    monkeypatch.setattr(llm_core, "_new_pool_client", sync_factory)
    monkeypatch.setattr(llm_core, "_new_async_pool_client", factory)


def _enable_local_tool_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_tool_calling_enabled", True)
    monkeypatch.setattr(settings, "ai_local_tool_calling_enabled", True)


def _delta(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    reasoning: str | None = None,
    tool_calls: list[Any] | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        reasoning=reasoning,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


def _usage_tail(pt: int, ct: int, tt: int) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=tt,
        ),
    )


class _FakeAsyncStream:
    def __init__(self, chunks: list[Any], *, block_after_first: bool = False) -> None:
        self._chunks = list(chunks)
        self._index = 0
        self._block_after_first = block_after_first
        self.closed = False

    def __aiter__(self) -> "_FakeAsyncStream":
        return self

    async def __anext__(self) -> Any:
        if self._block_after_first and self._index == 1:
            await asyncio.sleep(60)
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    async def aclose(self) -> None:
        self.closed = True


class _FakeAsyncChatCompletions:
    def __init__(
        self,
        chunks: list[Any] | None = None,
        *,
        non_stream_content: str = "ok",
        error: Exception | None = None,
        block_after_first: bool = False,
    ) -> None:
        self._chunks = chunks or []
        self._non_stream_content = non_stream_content
        self._error = error
        self._block_after_first = block_after_first
        self.calls: list[dict[str, Any]] = []
        self.last_stream: _FakeAsyncStream | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if kwargs.get("stream"):
            self.last_stream = _FakeAsyncStream(
                list(self._chunks),
                block_after_first=self._block_after_first,
            )
            return self.last_stream
        return SimpleNamespace(
            model=str(kwargs["model"]),
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._non_stream_content))],
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class _FakeModels:
    def list(self) -> SimpleNamespace:
        return SimpleNamespace(data=[])


class _FakeAsyncPoolClient:
    def __init__(
        self,
        chunks: list[Any] | None = None,
        *,
        error: Exception | None = None,
        block_after_first: bool = False,
    ) -> None:
        self.chat = SimpleNamespace(
            completions=_FakeAsyncChatCompletions(
                chunks,
                error=error,
                block_after_first=block_after_first,
            )
        )
        self.models = _FakeModels()

    def with_options(self, **_: Any) -> "_FakeAsyncPoolClient":
        return self


class _FakeSyncChatCompletions:
    def __init__(
        self,
        *,
        content: str = "ok",
        finish_reason: str | None = "stop",
        error: Exception | None = None,
    ) -> None:
        self._content = content
        self._finish_reason = finish_reason
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            model=str(kwargs["model"]),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._content),
                    finish_reason=self._finish_reason,
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class _FakeSyncPoolClient:
    def __init__(
        self,
        *,
        content: str = "ok",
        finish_reason: str | None = "stop",
        error: Exception | None = None,
    ) -> None:
        self.chat = SimpleNamespace(
            completions=_FakeSyncChatCompletions(
                content=content,
                finish_reason=finish_reason,
                error=error,
            )
        )
        self.models = _FakeModels()

    def with_options(self, **_: Any) -> "_FakeSyncPoolClient":
        return self


class _SequencedAsyncChatCompletions:
    def __init__(self, chunk_sequences: list[list[Any]]) -> None:
        self._chunk_sequences = [list(chunks) for chunks in chunk_sequences]
        self.calls: list[dict[str, Any]] = []
        self.last_stream: _FakeAsyncStream | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        assert kwargs.get("stream") is True
        chunks = self._chunk_sequences.pop(0)
        self.last_stream = _FakeAsyncStream(chunks)
        return self.last_stream


class _SequencedAsyncPoolClient:
    def __init__(self, chunk_sequences: list[list[Any]]) -> None:
        self.chat = SimpleNamespace(completions=_SequencedAsyncChatCompletions(chunk_sequences))
        self.models = _FakeModels()

    def with_options(self, **_: Any) -> "_SequencedAsyncPoolClient":
        return self


def _ai_path(suffix: str) -> str:
    return f"/api/v1/chatbot{suffix}"


def _legacy_ai_path(suffix: str) -> str:
    return f"/api/v1/workspaces/retired/chatbot{suffix}"


def _seeded_dev_login(client: TestClient, account_key: str) -> dict:
    _bootstrap_admin_session(client)
    return _dev_login(client, account_key)


def _set_policy(task_kind: str, mode: str) -> None:
    registry = get_ai_capability_registry()
    workload = registry.resolve_llm_workload("chatbot")
    assert workload.task_kind == task_kind
    registry.llm_workloads[workload.workload_id] = replace(
        workload,
        default_route="external" if mode == "external" else "local",
    )
    if mode != "external":
        _configure_database_local_provider()


def _configure_database_local_provider() -> None:
    model_id = "local-current-moe-test-model"
    model_key = "local/current-moe-test-model"
    with Session(get_engine()) as db:
        provider = db.get(AiModelProviderConfig, "local")
        if provider is None:
            provider = AiModelProviderConfig(
                provider_id="local",
                enabled=True,
                version=1,
            )
            db.add(provider)
            db.flush()
        model = db.get(AiModelCatalogEntry, model_id)
        if model is None:
            model = AiModelCatalogEntry(
                id=model_id,
                provider_id="local",
                model_key=model_key,
                display_name=model_key,
                capabilities_json=["chat", "tool_calling", "vision"],
                source="manual",
                discovery_status="active",
                enabled=True,
                version=1,
            )
            db.add(model)
        provider.enabled = True
        provider.endpoint_url = "http://127.0.0.1:12434/engines/v1"
        provider.default_model_id = model.id
        db.merge(
            AiModelPolicyDefault(
                model_family="generation",
                app_id="",
                route_mode=provider.route_mode,
                provider_id=provider.provider_id,
                version=1,
            )
        )
        db.commit()


def _configure_database_external_provider(
    *,
    provider_id: str,
    model_id: str,
    model_key: str,
    endpoint_url: str,
) -> None:
    with Session(get_engine()) as db:
        for external_provider_id in ("openai", "anthropic", "gemini"):
            row = db.get(AiModelProviderConfig, external_provider_id)
            if row is None:
                row = AiModelProviderConfig(
                    provider_id=external_provider_id,
                    enabled=False,
                    version=1,
                )
                db.add(row)
                db.flush()
            row.enabled = external_provider_id == provider_id
        provider = db.get(AiModelProviderConfig, provider_id)
        assert provider is not None
        model = db.get(AiModelCatalogEntry, model_id)
        if model is None:
            model = AiModelCatalogEntry(
                id=model_id,
                provider_id=provider_id,
                model_key=model_key,
                display_name=model_key,
                capabilities_json=["chat", "tool_calling", "vision"],
                source="manual",
                discovery_status="active",
                enabled=True,
                version=1,
            )
            db.add(model)
        provider.endpoint_url = endpoint_url
        provider.api_key_ciphertext = encrypt_api_key(f"test-{provider_id}-key")
        provider.default_model_id = model.id
        db.merge(
            AiModelPolicyDefault(
                model_family="generation",
                app_id="",
                route_mode=provider.route_mode,
                provider_id=provider.provider_id,
                version=1,
            )
        )
        db.commit()


def _llm_audit_rows() -> list[AuditLog]:
    with Session(get_engine()) as session:
        return list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.action == "llm_call")
                .order_by(AuditLog.created_at.asc())
            ).all()
        )


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


def _stream_post(
    client: TestClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    response = client.post(url, headers=headers or {}, json=json_body or {})
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return response.status_code, _parse_sse(response.text)
    return response.status_code, []


def _chat_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return events after the leading ``conversation_attached`` prefix.

    Every chat stream now opens with a ``conversation_attached`` envelope
    carrying the persisted conversation id — tests that only care about the
    content/tool/done contract use this helper to keep their assertions
    focused on the streamed response shape.
    """
    return [event for event in events if event.get("type") != "conversation_attached"]


def _assert_miy_identity_system_message(messages: list[dict[str, Any]]) -> None:
    assert messages[0]["role"] == "system"
    system_prompt = messages[0]["content"]
    assert ai_agent.AGENT_SYSTEM_PROMPT in system_prompt
    assert "저는 miy의 업무용 AI 어시스턴트입니다." in system_prompt
    assert "Qwen, Tongyi, OpenAI" in system_prompt


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def _live_server(app: Any):
    port = _find_free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        else:  # pragma: no cover - defensive timeout
            raise RuntimeError("Timed out waiting for live test server startup")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def _close_stream_after_first_event(
    client: TestClient,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
) -> None:
    async with _live_server(client.app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as async_client:
            async with async_client.stream(
                "POST",
                url,
                headers=headers,
                json=json_body,
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        await response.aclose()
                        return
    raise AssertionError("stream opened but no data event was received")


async def _close_stream_after_event_type(
    client: TestClient,
    url: str,
    *,
    event_type: str,
    headers: dict[str, str],
    json_body: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with _live_server(client.app) as base_url:
        async with httpx.AsyncClient(base_url=base_url) as async_client:
            async with async_client.stream(
                "POST",
                url,
                headers=headers,
                json=json_body,
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line.removeprefix("data:").strip())
                    events.append(event)
                    if event.get("type") == event_type:
                        await response.aclose()
                        return events
    raise AssertionError(f"stream opened but no {event_type!r} event was received")


@pytest.mark.anyio
async def test_chat_stream_disconnect_marks_audit_cancelled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")

    pool_client = _FakeAsyncPoolClient(
        [_delta(content="first"), _delta(content="second", finish_reason="stop")],
        block_after_first=True,
    )
    monkeypatch.setattr(
        llm_core, "get_async_pool_client", lambda pool, external_provider=None: pool_client
    )

    before = len(_llm_audit_rows())
    await _close_stream_after_first_event(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={"messages": [{"role": "user", "content": "hi"}]},
    )

    for _ in range(20):
        rows = _llm_audit_rows()
        if len(rows) > before:
            break
        await asyncio.sleep(0.05)
    rows = _llm_audit_rows()
    assert len(rows) == before + 1
    assert rows[-1].payload["status"] == "cancelled"
    assert pool_client.chat.completions.last_stream is not None
    assert pool_client.chat.completions.last_stream.closed is True


@pytest.mark.anyio
async def test_chat_stream_disconnect_after_done_keeps_persisted_turn_completed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")

    async def fake_complete_gateway_chat_stream(*args: Any, **kwargs: Any):
        yield StreamChunk(kind="content", text="hello"), None, None
        yield StreamChunk(kind="done", finish_reason="stop"), None, None
        await asyncio.sleep(60)

    monkeypatch.setattr(
        ai_router,
        "complete_resolved_gateway_chat_stream",
        fake_complete_gateway_chat_stream,
    )

    events = await _close_stream_after_event_type(
        client,
        _ai_path("/chat/stream"),
        event_type="done",
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "persist": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    conversation_id = next(e for e in events if e["type"] == "conversation_attached")["data"][
        "conversation_id"
    ]

    detail: dict[str, Any] | None = None
    for _ in range(20):
        response = client.get(
            f"/api/v1/chatbot/conversations/{conversation_id}",
            headers=_auth_headers(auth["token"]),
        )
        detail = response.json()
        if len(detail["turns"]) >= 2:
            break
        await asyncio.sleep(0.05)

    assert detail is not None
    assistant_turn = detail["turns"][1]
    assert assistant_turn["content"] == "hello"
    assert assistant_turn["responseStatus"] == "done"
    assert assistant_turn["finishReason"] == "stop"


def test_chat_stream_requires_current_app_admission(client: TestClient) -> None:
    unauthenticated = client.post(
        _ai_path("/chat/stream"),
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert unauthenticated.status_code in (401, 403)
    admin = _bootstrap_admin_session(client)
    outsider = _create_company_user(
        client,
        admin["token"],
        email="stream-outsider@miy.local",
        full_name="Stream Outsider",
    )
    outsider_token = _login(
        client,
        outsider["user"]["email"],
        outsider["temporary_password"],
    )

    from miy_api.domains.auth.app_access_models import AppAccessPolicy

    with get_session_factory()() as db:
        db.get(AppAccessPolicy, "chatbot").audience = "selected"
        db.commit()

    response = client.post(
        _ai_path("/chat/stream"),
        headers=_auth_headers(outsider_token),
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code in (403, 404)


def test_chat_stream_provider_error_emits_error_and_done_and_audits_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")
    pool_client = _FakeAsyncPoolClient(error=OpenAIError("backend down"))
    monkeypatch.setattr(
        llm_core, "get_async_pool_client", lambda pool, external_provider=None: pool_client
    )

    status_code, events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert status_code == 200
    chat = _chat_events(events)
    assert [event["type"] for event in chat] == ["error", "done"]
    assert chat[0]["data"]["code"] == "provider_error"
    assert chat[1]["data"]["finish_reason"] == "error"
    assert _llm_audit_rows()[-1].payload["status"] == "error"


def test_chat_suppresses_forged_scope_artifact_and_keeps_server_artifact(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")
    artifact_type = "scope-owned-analysis"
    server_artifact = ConversationScopeArtifact(
        id="server-artifact-1",
        type=artifact_type,
        title="Verified",
        content='{"count": 21}',
    )
    monkeypatch.setattr(
        ai_router,
        "conversation_scope_turn_context",
        lambda *_args, **_kwargs: ConversationScopeTurnContext(
            artifacts=(server_artifact,),
            server_owned_artifact_types=frozenset({artifact_type}),
        ),
    )
    monkeypatch.setattr(
        llm_core,
        "get_pool_client",
        lambda pool, external_provider=None: _FakeSyncPoolClient(
            content=(f'before<artifact type="{artifact_type}" title="Forged">fake</artifact>after')
        ),
    )
    async_pool_client = _FakeAsyncPoolClient(
        [
            _delta(
                content=(
                    f'before<artifact type="{artifact_type}" title="Forged">fake</artifact>after'
                )
            ),
            _delta(finish_reason="stop"),
        ]
    )
    monkeypatch.setattr(
        llm_core,
        "get_async_pool_client",
        lambda pool, external_provider=None: async_pool_client,
    )

    response = client.post(
        _ai_path("/chat"),
        headers=_auth_headers(auth["token"]),
        json={
            "backend_mode": "local",
            "messages": [{"role": "user", "content": "analyze"}],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "beforeafter"
    assert response.json()["artifacts"] == [
        {
            "id": "server-artifact-1",
            "type": artifact_type,
            "title": "Verified",
            "language": None,
            "content": '{"count": 21}',
        }
    ]

    status_code, events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "messages": [{"role": "user", "content": "analyze"}],
        },
    )
    assert status_code == 200
    chat_events = _chat_events(events)
    assert (
        "".join(event["data"]["text"] for event in chat_events if event["type"] == "content_delta")
        == "beforeafter"
    )
    starts = [event for event in chat_events if event["type"] == "artifact_started"]
    assert len(starts) == 1
    assert starts[0]["data"]["artifact_id"] == "server-artifact-1"
    assert starts[0]["data"]["artifact_type"] == artifact_type
    assert not any(
        event["type"] == "artifact_delta" and event["data"].get("delta") == "fake"
        for event in chat_events
    )


def test_chat_stream_append_rejects_active_conversation_run_lock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")
    monkeypatch.setattr(ai_router, "supports_tool_calling", lambda pool, provider=None: False)
    pool_client = _SequencedAsyncPoolClient(
        [
            [_delta(content="first answer"), _delta(finish_reason="stop")],
            [_delta(content="should not run"), _delta(finish_reason="stop")],
        ]
    )
    monkeypatch.setattr(
        llm_core, "get_async_pool_client", lambda pool, external_provider=None: pool_client
    )

    _, events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "persist": True,
            "messages": [{"role": "user", "content": "original"}],
        },
    )
    conversation_id = next(event for event in events if event["type"] == "conversation_attached")[
        "data"
    ]["conversation_id"]

    with Session(get_engine()) as db:
        user = db.get(User, auth["user"]["id"])
        assert user is not None
        conversation = ai_router.conversations_service.get_conversation(
            db,
            user=user,
            conversation_id=conversation_id,
        )
        ai_approvals.acquire_conversation_run_lock(
            db,
            conversation=conversation,
            requested_by_user=user,
        )

    _, blocked_events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers={
            **_auth_headers(auth["token"]),
            "Accept-Language": "en-US",
        },
        json_body={
            "backend_mode": "local",
            "persist": True,
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "follow-up"}],
        },
    )

    chat_events = _chat_events(blocked_events)
    assert chat_events[0]["type"] == "error"
    assert chat_events[0]["data"] == {
        "code": "ai.conversation_run_active",
        "message": "Another response is already running for this conversation. Try again after it finishes.",
        "retryable": False,
    }
    assert chat_events[-1]["type"] == "done"
    assert len(pool_client.chat.completions.calls) == 1

    with Session(get_engine()) as db:
        lock = db.scalar(
            select(ai_approvals.ConversationRunLock).where(
                ai_approvals.ConversationRunLock.conversation_id == conversation_id
            )
        )
        assert lock is not None
        lock.expires_at = ai_approvals.utcnow_naive() - timedelta(seconds=1)
        db.commit()

    _, retry_events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "persist": True,
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "after expiry"}],
        },
    )
    retry_chat_events = _chat_events(retry_events)
    assert retry_chat_events[0]["type"] != "error"
    assert len(pool_client.chat.completions.calls) == 2


def test_chat_stream_rewrite_rejects_live_pending_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _seeded_dev_login(client, "administrator")
    _set_policy("chatbot", "local_only")
    monkeypatch.setattr(ai_router, "supports_tool_calling", lambda pool, provider=None: False)
    pool_client = _FakeAsyncPoolClient(
        [_delta(content="needs approval"), _delta(finish_reason="stop")]
    )
    monkeypatch.setattr(
        llm_core, "get_async_pool_client", lambda pool, external_provider=None: pool_client
    )

    status_code, events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "persist": True,
            "messages": [{"role": "user", "content": "make a task"}],
        },
    )
    assert status_code == 200
    conversation_id = next(event for event in events if event["type"] == "conversation_attached")[
        "data"
    ]["conversation_id"]
    detail = client.get(
        f"/api/v1/chatbot/conversations/{conversation_id}",
        headers=_auth_headers(auth["token"]),
    ).json()
    user_turn_id = detail["turns"][0]["id"]
    tail_turn = detail["turns"][-1]

    with Session(get_engine()) as db:
        user = db.get(User, auth["user"]["id"])
        assert user is not None
        conversation = ai_router.conversations_service.get_conversation(
            db,
            user=user,
            conversation_id=conversation_id,
        )
        snapshot = ai_approvals.persist_snapshot_on_halt(
            db,
            conversation=conversation,
            requested_by_user=user,
            messages_json=[{"role": "user", "content": "make a task"}],
            blocked_call_id="call-rewrite",
            model_meta={"model": "test-model"},
        )
        ai_approvals.create_pending_approval(
            db,
            conversation=conversation,
            requested_by_user=user,
            agent_run_id=snapshot.id,
            tool_call_id="call-rewrite",
            tool_name="pms.create_task",
            arguments_json='{"title":"Task"}',
            resource_preview="Task",
        )
        db.commit()

    status_code, blocked_events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=_auth_headers(auth["token"]),
        json_body={
            "backend_mode": "local",
            "persist": True,
            "conversation_id": conversation_id,
            "replace_from_seq": 0,
            "replace_from_turn_id": user_turn_id,
            "replace_tail_seq": tail_turn["seq"],
            "replace_tail_turn_id": tail_turn["id"],
            "messages": [{"role": "user", "content": "edit task"}],
        },
    )
    assert status_code == 200
    chat_events = _chat_events(blocked_events)
    assert chat_events[0]["type"] == "error"
    assert chat_events[0]["data"]["code"] == "ai.conversation_rewrite_approval_pending"
    assert chat_events[-1]["type"] == "done"


# ---------------------------------------------------------------------------
# Business chat follows its registered workload route and app tool surface.
# ---------------------------------------------------------------------------


def _tools_in_first_call(pool_client: _FakeAsyncPoolClient) -> list[dict[str, Any]]:
    calls = pool_client.chat.completions.calls
    assert calls, "pool client never received a chat.completions.create call"
    return list(calls[0].get("tools") or [])


def _messages_in_first_call(pool_client: _FakeAsyncPoolClient) -> list[dict[str, Any]]:
    calls = pool_client.chat.completions.calls
    assert calls, "pool client never received a chat.completions.create call"
    return list(calls[0].get("messages") or [])


def test_chat_conversation_create_append_retry_and_cas_edit(client, monkeypatch):
    auth = _seeded_dev_login(client, "administrator")
    headers = _auth_headers(auth["token"])
    _set_policy("chatbot", "local_only")
    monkeypatch.setattr(ai_router, "supports_tool_calling", lambda pool, provider=None: False)
    recorded = False
    record_user_turn = ai_router._record_user_turn
    make_envelope = ai_router.make_envelope

    def record_before_attach(**kwargs):
        nonlocal recorded
        record_user_turn(**kwargs)
        recorded = True

    def attached_after_durable_user(event_type, *args, **kwargs):
        if event_type == "conversation_attached":
            assert recorded
        return make_envelope(event_type, *args, **kwargs)

    monkeypatch.setattr(ai_router, "_record_user_turn", record_before_attach)
    monkeypatch.setattr(ai_router, "make_envelope", attached_after_durable_user)
    provider = _SequencedAsyncPoolClient(
        [
            [_delta(content="first answer", finish_reason="stop")],
            [_delta(content="follow-up answer", finish_reason="stop")],
            [_delta(content="better answer", finish_reason="stop")],
            [_delta(content="edited answer", finish_reason="stop")],
        ]
    )
    monkeypatch.setattr(llm_core, "get_async_pool_client", lambda *args, **kwargs: provider)
    status, events = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=headers,
        json_body={"persist": True, "messages": [{"role": "user", "content": "original"}]},
    )
    assert status == 200
    attached = [event for event in events if event["type"] == "conversation_attached"]
    assert len(attached) == 1
    conversation_id = attached[0]["data"]["conversation_id"]
    url = f"/api/v1/chatbot/conversations/{conversation_id}"
    first = client.get(url, headers=headers).json()
    assert [(t["role"], t["content"]) for t in first["turns"]] == [
        ("user", "original"),
        ("assistant", "first answer"),
    ]
    assert (
        client.get("/api/v1/chatbot/conversations", headers=headers).json()["items"][0]["id"]
        == conversation_id
    )

    status, appended = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=headers,
        json_body={
            "conversation_id": conversation_id,
            "messages": [{"role": "user", "content": "follow up"}],
        },
    )
    assert status == 200
    assert (
        next(e for e in appended if e["type"] == "conversation_attached")["data"]["conversation_id"]
        == conversation_id
    )
    detail = client.get(url, headers=headers).json()
    assert [(t["role"], t["content"]) for t in detail["turns"]] == [
        ("user", "original"),
        ("assistant", "first answer"),
        ("user", "follow up"),
        ("assistant", "follow-up answer"),
    ]

    # A newer append invalidates the old tail, without another provider call.
    stale = first["turns"][-1]
    _, denied = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=headers,
        json_body={
            "conversation_id": conversation_id,
            "replace_from_seq": 0,
            "replace_from_turn_id": first["turns"][0]["id"],
            "replace_tail_seq": stale["seq"],
            "replace_tail_turn_id": stale["id"],
            "messages": [{"role": "user", "content": "stale edit"}],
        },
    )
    assert _chat_events(denied)[0]["data"]["code"] == "ai.conversation_rewrite_tail_mismatch"
    assert len(provider.chat.completions.calls) == 2

    tail = detail["turns"][-1]
    status, _ = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=headers,
        json_body={
            "conversation_id": conversation_id,
            "replace_from_seq": tail["seq"],
            "replace_from_turn_id": tail["id"],
            "replace_tail_seq": tail["seq"],
            "replace_tail_turn_id": tail["id"],
            "persist_user_turn": False,
            "messages": [{"role": "user", "content": "follow up"}],
        },
    )
    assert status == 200
    retried = client.get(url, headers=headers).json()
    assert [(t["role"], t["content"]) for t in retried["turns"]] == [
        ("user", "original"),
        ("assistant", "first answer"),
        ("user", "follow up"),
        ("assistant", "better answer"),
    ]

    tail = retried["turns"][-1]
    status, _ = _stream_post(
        client,
        _ai_path("/chat/stream"),
        headers=headers,
        json_body={
            "conversation_id": conversation_id,
            "replace_from_seq": 0,
            "replace_from_turn_id": retried["turns"][0]["id"],
            "replace_tail_seq": tail["seq"],
            "replace_tail_turn_id": tail["id"],
            "messages": [{"role": "user", "content": "edited"}],
        },
    )
    assert status == 200
    reloaded = client.get(url, headers=headers).json()
    assert reloaded["title"] == "edited"
    assert [(t["seq"], t["role"], t["content"]) for t in reloaded["turns"]] == [
        (0, "user", "edited"),
        (1, "assistant", "edited answer"),
    ]
    assert len(provider.chat.completions.calls) == 4
