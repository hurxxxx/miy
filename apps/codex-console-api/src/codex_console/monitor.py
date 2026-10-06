"""Read-only, owner-configured probes. Operational decisions belong to Codex."""

import asyncio
import json
import re
import sqlite3
from datetime import timedelta

import httpx
from sqlalchemy.exc import OperationalError

from .config import MonitoredService
from .models import ServiceObservation, now


def services(settings):
    return [
        MonitoredService(
            id="console-session",
            name="Codex sessions",
            environment="console",
            health_url=f"http://127.0.0.1:{settings.port}/healthz",
        ),
        MonitoredService(
            id="console-templates",
            name="Codex template sessions",
            environment="console",
            health_url=f"http://127.0.0.1:{settings.template_port}/healthz",
        ),
        *settings.monitor_services,
    ]


async def supervisor(service):
    if service.unit:
        args = [
            "systemctl",
            *(["--user"] if service.user_unit else []),
            "show",
            "--property=ActiveState",
            "--value",
            "--",
            service.unit,
        ]
    elif service.container:
        args = ["docker", "inspect", "--format", "{{.State.Status}}", "--", service.container]
    else:
        return None
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=4096
    )
    try:
        async with asyncio.timeout(3):
            output = await process.stdout.read(4097)
            if len(output) > 4096:
                return "unknown"
            await process.wait()
        if process.returncode:
            return "unknown"
        value = output.decode().strip()
        return "running" if value in ("active", "running") else "stopped"
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def probe(service, client):
    status, version = "unknown", None
    try:
        process_status = await supervisor(service)
        if service.health_url:
            async with client.stream("GET", service.health_url) as response:
                if response.status_code != 200:
                    return "unavailable", None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        return "unknown", None
                status = "healthy"
                try:
                    data = json.loads(body)
                    value = data.get("runtime_revision") or data.get("version")
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._+-]{1,160}", value):
                        version = value
                except (ValueError, AttributeError):
                    pass
            if process_status in ("unknown", "stopped"):
                status = process_status
        else:
            status = process_status or "unknown"
    except (OSError, TimeoutError, httpx.HTTPError):
        status = "unknown"
    return status, version


def _save_observation(factory, service, status, version):
    with factory.begin() as db:
        row = db.get(ServiceObservation, service.id)
        if not row:
            row = ServiceObservation(service_id=service.id, status=status)
            db.add(row)
        row.status, row.version, row.checked_at = status, version, now()


async def observe(settings, factory):
    async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
        semaphore = asyncio.Semaphore(4)

        async def collect(service):
            async with semaphore:
                try:
                    async with asyncio.timeout(5):
                        status, version = await probe(service, client)
                except TimeoutError:
                    status, version = "unknown", None
                try:
                    await asyncio.to_thread(_save_observation, factory, service, status, version)
                except OperationalError as error:
                    if getattr(error.orig, "sqlite_errorcode", 0) & 0xFF != sqlite3.SQLITE_BUSY:
                        raise
                    # Keep the last sample; the existing polling cadence refreshes
                    # after contention clears, and snapshot() marks old data stale.

        while True:
            await asyncio.gather(*(collect(service) for service in services(settings)))
            await asyncio.sleep(10)


def snapshot(settings, factory):
    with factory() as db:
        result = []
        for service in services(settings):
            row = db.get(ServiceObservation, service.id)
            stale = row is None or row.checked_at < now() - timedelta(seconds=30)
            result.append(
                {
                    "id": service.id,
                    "name": service.name,
                    "environment": service.environment,
                    "status": row.status if row and not stale else "unknown",
                    "version": row.version if row else None,
                    "checked_at": row.checked_at.isoformat() if row else None,
                    "stale": stale,
                }
            )
        return result
