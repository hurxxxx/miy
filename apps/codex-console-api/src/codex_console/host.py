"""Bounded Linux observations. Never starts, stops or changes a monitored service."""

import asyncio
import os
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from .models import HostObservation, now
from .rpc import CONTRACT


class MemoryOut(BaseModel):
    total: int
    used: int
    available: int
    swap_total: int
    swap_used: int
    cgroup_limit: int | None = None
    cgroup_used: int | None = None


class DiskOut(BaseModel):
    path: str
    total: int
    used: int
    available: int


class HostOut(BaseModel):
    checked_at: str | None = None
    stale: bool = True
    memory: MemoryOut | None = None
    disks: list[DiskOut] = []
    load: list[float] = []
    cpu_count: int | None = None
    installed_cli: str | None = None
    template_cli: str | None = None
    contract_cli: str = CONTRACT["codexVersion"]


def collect(settings, *, proc=Path("/proc"), cgroups=Path("/sys/fs/cgroup")):
    result = {"disks": []}
    try:
        values = {}
        for line in (proc / "meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.split()[0]) * 1024
        total, available = values["MemTotal"], values["MemAvailable"]
        memory = dict(
            total=total,
            used=max(0, total - available),
            available=available,
            swap_total=values.get("SwapTotal", 0),
            swap_used=max(0, values.get("SwapTotal", 0) - values.get("SwapFree", 0)),
        )
        result["memory"] = memory
        # Evaluate the current unified cgroup and its parents; a parent can be tighter.
        membership = next(
            x[3:] for x in (proc / "self/cgroup").read_text().splitlines() if x.startswith("0::")
        )
        node = (cgroups / membership.lstrip("/")).resolve()
        base = cgroups.resolve()
        limits = []
        while node.is_relative_to(base):
            try:
                limit = (node / "memory.max").read_text().strip()
                current = int((node / "memory.current").read_text().strip())
                if limit.isdecimal() and int(limit) > 0:
                    limits.append((int(limit), current))
            except (OSError, ValueError):
                pass
            if node == base:
                break
            node = node.parent
        if limits:
            limit, current = min(limits)
            memory.update(cgroup_limit=limit, cgroup_used=current)
    except (OSError, ValueError, KeyError, StopIteration):
        # No invented zero values when an observation is unavailable.
        pass
    devices = set()
    for path in (Path("/"), settings.workspace):
        try:
            device = path.stat().st_dev
            if device in devices:
                continue
            devices.add(device)
            usage = os.statvfs(path)
            total = usage.f_blocks * usage.f_frsize
            result["disks"].append(
                dict(
                    path=str(path),
                    total=total,
                    used=(usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                    available=usage.f_bavail * usage.f_frsize,
                )
            )
        except OSError:
            pass
    try:
        result.update(load=list(os.getloadavg()), cpu_count=os.cpu_count())
    except OSError:
        pass
    return result


async def version(binary):
    if not binary:
        return None
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        async with asyncio.timeout(3):
            output = await process.stdout.read(256)
            await process.wait()
        value = output.decode().strip()
        return (
            value
            if not process.returncode and re.fullmatch(r"codex-cli \d+\.\d+\.\d+", value)
            else None
        )
    except (OSError, TimeoutError, UnicodeError):
        return None
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()


def _save_observation(factory, payload):
    with factory.begin() as db:
        row = db.get(HostObservation, 1)
        if not row:
            row = HostObservation(id=1, payload=payload)
            db.add(row)
        row.payload, row.checked_at = payload, now()


async def observe(settings, factory):
    while True:
        payload = await asyncio.to_thread(collect, settings)
        installed, runner = await asyncio.gather(
            version(settings.binary), version(settings.template_binary)
        )
        payload.update(installed_cli=installed, template_cli=runner)
        try:
            await asyncio.to_thread(_save_observation, factory, payload)
        except OperationalError as error:
            if getattr(error.orig, "sqlite_errorcode", 0) & 0xFF != sqlite3.SQLITE_BUSY:
                raise
            # Preserve the last sample and retry at the normal observation interval.
        await asyncio.sleep(10)


def snapshot(factory):
    with factory() as db:
        row = db.get(HostObservation, 1)
        if not row:
            return HostOut()
        return HostOut(
            **row.payload,
            checked_at=row.checked_at.isoformat(),
            stale=row.checked_at < now() - timedelta(seconds=30),
        )
