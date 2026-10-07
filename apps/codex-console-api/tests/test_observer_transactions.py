import asyncio
import sqlite3
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from codex_console import host, monitor
from codex_console.models import HostObservation, ServiceObservation, database, now


@pytest.mark.parametrize("kind", ["services", "host"])
def test_observer_writer_wait_keeps_event_loop_responsive(settings, monkeypatch, kind):
    engine, factory = database(settings.database_url)
    attempted = threading.Event()

    async def probe(*_args):
        return "healthy", None

    async def version(*_args):
        return None

    if kind == "services":
        monitor_services = monitor.services(settings)[:1]
        monkeypatch.setattr(monitor, "services", lambda cfg: monitor_services)
        monkeypatch.setattr(monitor, "probe", probe)
        observe = monitor.observe
        model, key = ServiceObservation, monitor_services[0].id
    else:
        monkeypatch.setattr(host, "collect", lambda _cfg: {})
        monkeypatch.setattr(host, "version", version)
        observe = host.observe
        model, key = HostObservation, 1

    def beginning(_conn, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            attempted.set()

    async def run():
        observer = None
        try:
            # A concurrent request/process owns SQLite's writer. Its release needs
            # the ASGI loop to keep running while monitoring waits for the lock.
            with factory.begin():
                event.listen(engine, "before_cursor_execute", beginning)
                observer = asyncio.create_task(observe(settings, factory))
                started = time.monotonic()
                await asyncio.wait_for(asyncio.to_thread(attempted.wait, 2), 3)
                assert attempted.is_set()
                await asyncio.sleep(0.02)
                assert time.monotonic() - started < 1
            async with asyncio.timeout(3):
                while True:
                    with factory() as db:
                        row = db.get(model, key)
                    if row:
                        break
                    await asyncio.sleep(0.01)
            assert row.checked_at is not None
        finally:
            if observer is not None:
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["services", "host"])
@pytest.mark.parametrize("error_code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_ERROR])
def test_observer_writer_errors_preserve_data_and_only_busy_refreshes(
    settings, monkeypatch, kind, error_code
):
    engine, factory = database(settings.database_url)
    module = monitor if kind == "services" else host
    selected = monitor.services(settings)[:1]
    model, key = (
        (ServiceObservation, selected[0].id) if kind == "services" else (HostObservation, 1)
    )
    original = module._save_observation
    calls = 0
    previous = now() - timedelta(minutes=1)
    with factory.begin() as db:
        db.add(
            ServiceObservation(service_id=key, status="healthy", version="v1", checked_at=previous)
            if kind == "services"
            else HostObservation(id=key, payload={}, checked_at=previous)
        )

    async def probe(*_args):
        return "healthy", "v2"

    async def version(*_args):
        return None

    monkeypatch.setattr(monitor, "services", lambda _cfg: selected)
    monkeypatch.setattr(monitor, "probe", probe)
    monkeypatch.setattr(host, "collect", lambda _cfg: {})
    monkeypatch.setattr(host, "version", version)

    async def run():
        first = asyncio.Event()
        refreshed = asyncio.Event()
        poll_waiting = asyncio.Event()
        allow_poll = asyncio.Event()
        intervals = []
        loop = asyncio.get_running_loop()

        class ObserverAsyncio:
            def __getattr__(self, name):
                return getattr(asyncio, name)

            async def sleep(self, delay):
                # Control only this observer's cadence, not global asyncio or
                # its real worker-thread SQLite transaction.
                intervals.append(delay)
                assert delay == 10
                poll_waiting.set()
                await allow_poll.wait()
                allow_poll.clear()

        def save(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = error_code
                loop.call_soon_threadsafe(first.set)
                raise OperationalError("BEGIN IMMEDIATE", (), error)
            original(*args)
            loop.call_soon_threadsafe(refreshed.set)

        monkeypatch.setattr(module, "_save_observation", save)
        monkeypatch.setattr(module, "asyncio", ObserverAsyncio())
        observer = asyncio.create_task(module.observe(settings, factory))
        ready = asyncio.create_task(refreshed.wait())
        polling = asyncio.create_task(poll_waiting.wait())
        try:
            await asyncio.wait_for(first.wait(), 3)
            if error_code != sqlite3.SQLITE_BUSY:
                with pytest.raises(OperationalError):
                    await asyncio.wait_for(observer, 3)
                assert calls == 1
                assert intervals == []
                with factory() as db:
                    assert db.get(model, key).checked_at == previous
                return
            done, _ = await asyncio.wait(
                (observer, polling), timeout=3, return_when=asyncio.FIRST_COMPLETED
            )
            if observer in done:
                await observer
            assert polling in done
            assert intervals == [10]
            assert calls == 1
            assert not refreshed.is_set()
            with factory() as db:
                assert db.get(model, key).checked_at == previous
            allow_poll.set()
            done, _ = await asyncio.wait(
                (observer, ready), timeout=3, return_when=asyncio.FIRST_COMPLETED
            )
            if observer in done:
                await observer
            assert ready in done
            with factory() as db:
                assert db.get(model, key).checked_at > previous
            assert calls == 2
        finally:
            observer.cancel()
            ready.cancel()
            polling.cancel()
            await asyncio.gather(observer, ready, polling, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        engine.dispose()
