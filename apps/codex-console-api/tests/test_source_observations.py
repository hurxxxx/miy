import asyncio
import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from codex_console import workbench_sources as sources
from codex_console.models import WorkbenchObservation, database, now


@pytest.mark.parametrize("kind", ["catalog", "usage", "gitlab"])
def test_source_refresh_writer_wait_keeps_event_loop_responsive(settings, monkeypatch, kind):
    engine, factory = database(settings.database_url)
    attempted = threading.Event()
    settings.miy_api_origin = "https://miy.example.test"

    async def miy_get(_settings, path):
        if kind == "catalog":
            return "ready", {
                "schema_version": 1,
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 200,
                "generated_at": now().isoformat(),
            }
        return "unavailable", None

    async def glab_get(*args):
        return []

    monkeypatch.setattr(sources, "miy_get", miy_get)
    monkeypatch.setattr(sources, "glab_get", glab_get)
    monkeypatch.setattr(
        sources,
        "gitlab_origin",
        lambda root: (
            "git.example.test",
            "team/repo",
            "https://git.example.test/team/repo",
        ),
    )

    def beginning(_conn, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            attempted.set()

    async def run():
        refresh = None
        try:
            with factory.begin():
                event.listen(engine, "before_cursor_execute", beginning)
                coroutine = (
                    sources.runtime_catalog(settings, factory)
                    if kind == "catalog"
                    else sources.runtime_usage(settings, factory, "docs")
                    if kind == "usage"
                    else sources.gitlab(settings, factory)
                )
                refresh = asyncio.create_task(coroutine)
                started = time.monotonic()
                await asyncio.wait_for(asyncio.to_thread(attempted.wait, 2), 3)
                assert attempted.is_set()
                await asyncio.sleep(0.02)
                assert time.monotonic() - started < 1
            result = await asyncio.wait_for(refresh, 3)
            assert result is not None
        finally:
            if refresh:
                await asyncio.gather(refresh, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        engine.dispose()


@pytest.mark.parametrize("same_origin", [True, False])
@pytest.mark.parametrize(
    "error_code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_BUSY | 256, sqlite3.SQLITE_ERROR]
)
def test_busy_source_cache_preserves_scoped_stale_evidence_only(
    settings, monkeypatch, same_origin, error_code
):
    engine, factory = database(settings.database_url)
    previous = now() - timedelta(minutes=1)
    old = {
        "origin": "https://old.example.test",
        "state": "ready",
        "data": {"items": []},
        "checked_at": previous.isoformat(),
    }
    with factory.begin() as db:
        db.add(WorkbenchObservation(key="runtime-catalog", payload=old, checked_at=previous))

    def blocked(_conn, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            error = sqlite3.OperationalError("database is locked")
            error.sqlite_errorcode = error_code
            raise OperationalError("BEGIN IMMEDIATE", (), error)

    event.listen(engine, "before_cursor_execute", blocked)
    origin = old["origin"] if same_origin else "https://new.example.test"

    async def run():
        if error_code & 255 != sqlite3.SQLITE_BUSY:
            with pytest.raises(OperationalError):
                await sources.save_scoped(
                    factory, "runtime-catalog", origin, "ready", {"new": True}
                )
            return
        result = await sources.save_scoped(
            factory, "runtime-catalog", origin, "ready", {"new": True}
        )
        assert result["state"] == "unavailable"
        assert result["origin"] == origin
        assert result["data"] == (old["data"] if same_origin else None)
        assert result["checked_at"] == (old["checked_at"] if same_origin else None)
        with factory() as db:
            row = db.get(WorkbenchObservation, "runtime-catalog")
            assert row.payload == old and row.checked_at == previous

    try:
        asyncio.run(run())
    finally:
        engine.dispose()
