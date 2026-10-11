from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from miy_api import external_runtime as runtime_module


class _ProbeService:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        startup_error: Exception | None = None,
    ) -> None:
        self._name = name
        self._events = events
        self._startup_error = startup_error

    async def startup(self) -> None:
        self._events.append(f"start:{self._name}")
        if self._startup_error is not None:
            raise self._startup_error

    async def shutdown(self) -> None:
        self._events.append(f"stop:{self._name}")


def _runtime_settings() -> SimpleNamespace:
    return SimpleNamespace(
        realtime_redis_url="redis://unused.invalid/0",
        instance_id="runtime-test",
    )


def test_production_external_runtime_rolls_back_started_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    services = {
        "agent": _ProbeService("agent", events),
        "app": _ProbeService("app", events),
        "docs": _ProbeService("docs", events, startup_error=RuntimeError("failed")),
    }
    monkeypatch.setattr(
        runtime_module,
        "AgentTerminalRuntime",
        lambda *_args, **_kwargs: services["agent"],
    )
    monkeypatch.setattr(runtime_module, "AppRealtimeHub", lambda *_args, **_kwargs: services["app"])
    monkeypatch.setattr(runtime_module, "DocsCollabHub", lambda: services["docs"])
    monkeypatch.setattr(
        runtime_module,
        "WhiteboardCollabHub",
        lambda: _ProbeService("whiteboard", events),
    )
    runtime = runtime_module.ProductionApiExternalRuntime(_runtime_settings())  # type: ignore[arg-type]
    app = FastAPI()

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="failed"):
            async with runtime.activate(app):
                raise AssertionError("unreachable")

    asyncio.run(exercise())

    assert events == [
        "start:agent",
        "start:app",
        "start:docs",
        "stop:docs",
        "stop:app",
        "stop:agent",
    ]
    assert app.state.agent_terminal_runtime is None
    assert app.state.app_realtime is None
    assert app.state.docs_collab is None
