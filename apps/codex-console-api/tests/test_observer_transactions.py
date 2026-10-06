import asyncio
import threading
import time

import pytest
from sqlalchemy import event

from codex_console import host, monitor
from codex_console.models import HostObservation, ServiceObservation, database


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
