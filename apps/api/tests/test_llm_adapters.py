"""Unit tests for streaming adapters + ``complete_chat_stream``.

These stay provider-free by handing the adapters fake async SDK objects. No
HTTP or FastAPI client here — route wiring lives in ``test_ai_stream.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core import llm as llm_core
from miy_api.core.db import get_engine
from miy_api.core.llm import (
    LlmTaskContext,
    ResolvedLlmExecution,
    complete_chat_stream,
)
from miy_api.core.llm_adapters import StreamChunk
from miy_api.domains.ai.gateway import (
    LlmWorkloadContext,
    build_llm_workload_request,
    resolve_gateway_execution,
)
from miy_api.domains.auth.models import AuditLog

pytestmark = pytest.mark.anyio


def _delta_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    reasoning: Any = None,
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


def _usage_tail(
    *, prompt_tokens: int, completion_tokens: int, total_tokens: int
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


class _FakeAsyncStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    def __aiter__(self) -> "_FakeAsyncStream":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.closed = True


class _FakeAsyncChatCompletions:
    def __init__(
        self,
        chunks: list[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._chunks = chunks or []
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.last_stream: _FakeAsyncStream | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        self.last_stream = _FakeAsyncStream(self._chunks)
        return self.last_stream


class _FakeAsyncPoolClient:
    def __init__(self, completions: _FakeAsyncChatCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)

    def with_options(self, **_: Any) -> "_FakeAsyncPoolClient":
        return self


def _tool_call_delta(
    *,
    index: int,
    tool_id: str,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=tool_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class _CloseReturnsCoroutineStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self):
        async def mark_closed() -> None:
            self.closed = True

        return mark_closed()


def _ctx() -> LlmTaskContext:
    return LlmTaskContext(
        source="test.stream",
        actor_user_id=None,
        task_kind="chatbot",
        app_id="chatbot",
        workload_id="chatbot",
    )


def _make_db_session() -> Session:
    return Session(get_engine())


def _resolve_database_execution(
    db: Session,
    *,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> ResolvedLlmExecution:
    request = build_llm_workload_request(
        "chatbot",
        LlmWorkloadContext.from_task_context(_ctx()),
        db,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resolve_gateway_execution(request, db).llm_execution


def _install_fake_pool(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[Any],
    *,
    error: Exception | None = None,
) -> _FakeAsyncChatCompletions:
    completions = _FakeAsyncChatCompletions(chunks, error=error)
    client = _FakeAsyncPoolClient(completions)
    monkeypatch.setattr(
        llm_core,
        "_new_async_pool_client",
        lambda _config: client,
    )
    return completions


def _set_policy(task_kind: str, mode: str) -> None:
    # Legacy test shim: registered workload routing is no longer DB task-policy driven.
    _ = (task_kind, mode)


def _audit_rows() -> list[AuditLog]:
    with _make_db_session() as session:
        return list(
            session.scalars(
                select(AuditLog)
                .where(AuditLog.action == "llm_call")
                .order_by(AuditLog.created_at.asc())
            ).all()
        )


async def _drain(**kwargs: Any) -> list[StreamChunk]:
    kwargs.setdefault("max_tokens", 32_768)
    db = _make_db_session()
    try:
        if "resolved_execution" not in kwargs:
            kwargs["resolved_execution"] = _resolve_database_execution(
                db,
                messages=kwargs["messages"],
                max_tokens=kwargs["max_tokens"],
            )
        return [chunk async for chunk, _, _ in complete_chat_stream(_ctx(), db, **kwargs)]
    finally:
        db.close()


@pytest.fixture(name="configured_llm_test_runtime")
def _configured_llm_test_runtime(configured_local_llm_control_plane: None) -> None:
    """Use the explicit DB-managed local model for LLM execution tests."""

    return configured_local_llm_control_plane
