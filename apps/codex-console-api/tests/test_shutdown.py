"""Service ownership must be released even when durable runtime shutdown fails."""

import pytest
from conftest import FakeRPC
from fastapi.testclient import TestClient
from sqlalchemy import event

from codex_console import app as app_module
from codex_console.runtime import Runtime
from codex_console.storage import process_guard


def test_runtime_close_failure_preserves_error_and_closes_remaining_resources(
    settings, monkeypatch
):
    original_database = app_module.database
    original_close = Runtime.close
    closed, disposed = [], []

    def observed_database(url):
        engine, factory = original_database(url)
        event.listen(engine, "engine_disposed", lambda _: disposed.append(True))
        return engine, factory

    async def failing_close(runtime):
        await original_close(runtime)
        closed.append(runtime.executor)
        if runtime.executor == "session":
            raise RuntimeError("Synthetic durable shutdown failure")

    monkeypatch.setattr(app_module, "database", observed_database)
    monkeypatch.setattr(Runtime, "close", failing_close)
    with pytest.raises(RuntimeError, match="Synthetic durable shutdown failure"):
        with TestClient(app_module.create_app(settings, rpc_factory=FakeRPC)):
            pass
    assert closed == ["session", "templates"]
    assert disposed == [True]
    with process_guard(settings.database_url):
        pass  # A replacement process can acquire every role after failed shutdown.
