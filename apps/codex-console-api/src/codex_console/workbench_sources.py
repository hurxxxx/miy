"""Read-only, bounded projections from the configured MIY installation and GitLab origin."""

import asyncio
import json
import os
import re
import sqlite3
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from . import git
from .errors import ConsoleError
from .models import WorkbenchObservation, now
from .workbench_schemas import GitLabItem, GitLabOut, RuntimeCatalog, RuntimeOut, RuntimeUsage

MAX_BYTES = 1024 * 1024
TTL = 15


def cached(factory, key, *, allow_expired=False):
    with factory() as db:
        row = db.get(WorkbenchObservation, key)
        if row and (allow_expired or (now() - row.checked_at).total_seconds() < TTL):
            return row.payload
    return None


async def miy_get(settings, path):
    if not settings.miy_api_origin or not settings.miy_api_key:
        return "unconfigured", None
    try:
        async with (
            asyncio.timeout(10),
            httpx.AsyncClient(
                timeout=5,
                follow_redirects=False,
                trust_env=False,
            ) as client,
        ):
            async with client.stream(
                "GET",
                settings.miy_api_origin + "/api/v1/integrations/apps" + path,
                headers={"Authorization": "Bearer " + settings.miy_api_key.get_secret_value()},
            ) as response:
                if response.status_code in (401, 403):
                    return "denied", None
                if response.status_code in (404, 405):
                    return "unsupported", None
                if response.status_code != 200:
                    return "unavailable", None
                if response.headers.get("content-type", "").split(";")[0] != "application/json":
                    return "unsupported", None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        return "unavailable", None
        return "ready", json.loads(body)
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        return "unavailable", None


async def runtime_catalog(settings, factory, *, fresh=False):
    # A changed or removed installation cannot inherit another installation's cache.
    key = "runtime-catalog"
    if not settings.miy_api_origin:
        return RuntimeOut(state="unconfigured")
    stored = None if fresh else cached(factory, key)
    if not stored or stored.get("origin") != settings.miy_api_origin:
        state, data = await miy_get(settings, "?page_size=200")
        try:
            parsed = RuntimeCatalog.model_validate(data) if state == "ready" else None
            if parsed and (
                parsed.total != len(parsed.items)
                or len({a.app_id for a in parsed.items}) != len(parsed.items)
            ):
                raise ValueError("Incomplete catalog")
            normalized = parsed.model_dump(mode="json") if parsed else None
        except (ValueError, ValidationError):
            state, normalized = "unsupported", None
        stored = await save_scoped(factory, key, settings.miy_api_origin, state, normalized)
    return RuntimeOut(
        state=stored["state"],
        checked_at=stored.get("checked_at"),
        stale=stored["state"] != "ready",
        items=(stored.get("data") or {}).get("items", []),
    )


async def save_scoped(factory, key, origin, state, data):
    try:
        return await asyncio.to_thread(_save_scoped, factory, key, origin, state, data)
    except OperationalError as error:
        if getattr(error.orig, "sqlite_errorcode", 0) & 0xFF != sqlite3.SQLITE_BUSY:
            raise
        # Observations may retain stale evidence, but a failed write cannot
        # refresh its timestamp or carry evidence into a changed installation.
        old = cached(factory, key, allow_expired=True) or {}
        if old.get("origin") != origin:
            old = {}
        return {
            "origin": origin,
            "state": "unavailable" if state == "ready" else state,
            "data": old.get("data"),
            "checked_at": old.get("checked_at"),
        }


def _save_scoped(factory, key, origin, state, data):
    with factory.begin() as db:
        row = db.get(WorkbenchObservation, key)
        old = row.payload if row and row.payload.get("origin") == origin else {}
        payload = {
            "origin": origin,
            "state": state,
            "data": data if data is not None else old.get("data"),
            "checked_at": now().isoformat() if data is not None else old.get("checked_at"),
        }
        if row:
            row.payload, row.checked_at = payload, now()
        else:
            db.add(WorkbenchObservation(key=key, payload=payload))
    return payload


async def runtime_usage(settings, factory, app_id):
    month = now().strftime("%Y-%m")
    if not settings.miy_api_origin:
        return {"state": "unconfigured", "data": None, "checked_at": None}
    key = "usage:" + app_id
    stored = cached(factory, key)
    origin = settings.miy_api_origin + ":" + month
    if not stored or stored.get("origin") != origin:
        state, data = await miy_get(settings, "/" + quote(app_id, safe="") + "/usage")
        try:
            parsed = RuntimeUsage.model_validate(data) if state == "ready" else None
            if parsed and (parsed.app_id != app_id or parsed.month != month):
                raise ValueError("Mismatched projection")
            normalized = parsed.model_dump(mode="json") if parsed else None
        except (ValueError, ValidationError):
            state, normalized = "unsupported", None
        stored = await save_scoped(factory, key, origin, state, normalized)
    return stored


def gitlab_origin(root):
    raw = git.git(root, "remote", "get-url", "origin", limit=4096).decode().strip()
    if "://" not in raw:
        match = re.fullmatch(r"git@([A-Za-z0-9.-]+):([A-Za-z0-9_./-]+)", raw)
        if not match:
            raise ConsoleError("git_unavailable")
        host, project = match.groups()
        base = "https://" + host
    else:
        url = urlsplit(raw)
        if (
            url.scheme not in ("https", "http", "ssh")
            or url.password
            or not url.hostname
            or url.query
            or url.fragment
        ):
            raise ConsoleError("git_unavailable")
        if url.scheme != "ssh" and url.username:
            raise ConsoleError("git_unavailable")
        host = url.hostname if url.scheme == "ssh" else url.netloc
        base = ("https" if url.scheme == "ssh" else url.scheme) + "://" + host
        project = url.path.lstrip("/")
    project = project.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", project):
        raise ConsoleError("git_unavailable")
    return host, project, base + "/" + project


async def glab_get(root, host, project, suffix):
    process = await asyncio.create_subprocess_exec(
        "glab",
        "api",
        "--method",
        "GET",
        "--hostname",
        host,
        "projects/" + quote(project, safe="") + suffix,
        cwd=root,
        env={k: os.environ[k] for k in ("HOME", "PATH", "LANG") if k in os.environ},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(12):
            body = await process.stdout.read(MAX_BYTES + 1)
            # StreamReader.read may return before EOF; collect bounded chunks.
            while len(body) <= MAX_BYTES:
                part = await process.stdout.read(min(65536, MAX_BYTES + 1 - len(body)))
                if not part:
                    break
                body += part
            if len(body) > MAX_BYTES:
                raise ValueError("GitLab response too large")
            if await process.wait() != 0:
                raise ValueError("GitLab unavailable")
        return json.loads(body)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def gitlab(settings, factory):
    try:
        host, project, web = await asyncio.to_thread(gitlab_origin, settings.workspace)
    except (ConsoleError, UnicodeError, ValueError):
        return GitLabOut(state="unconfigured")
    stored = cached(factory, "gitlab")
    if not stored or stored.get("origin") != web:
        try:
            branches, mrs, pipelines = await asyncio.gather(
                *(
                    glab_get(settings.workspace, host, project, suffix)
                    for suffix in (
                        "/repository/branches?per_page=20",
                        "/merge_requests?state=opened&per_page=20",
                        "/pipelines?per_page=20",
                    )
                ),
                return_exceptions=True,
            )
            if any(
                not isinstance(rows, list) or len(rows) > 20 for rows in (branches, mrs, pipelines)
            ):
                raise ValueError("Invalid GitLab projection")
            data = {
                "branches": [
                    GitLabItem(name=r["name"][:200], revision=r["commit"]["id"]).model_dump()
                    for r in branches
                ],
                "merge_requests": [
                    GitLabItem(
                        id=r["iid"],
                        name=r["title"][:200],
                        status=r["state"],
                        revision=r.get("sha"),
                        url=f"{web}/-/merge_requests/{int(r['iid'])}",
                    ).model_dump()
                    for r in mrs
                ],
                "pipelines": [
                    GitLabItem(
                        id=r["id"],
                        name=r["ref"][:200],
                        status=r["status"],
                        revision=r["sha"],
                        url=f"{web}/-/pipelines/{int(r['id'])}",
                    ).model_dump()
                    for r in pipelines
                ],
            }
            stored = await save_scoped(factory, "gitlab", web, "ready", data)
        except (OSError, TimeoutError, ValueError, KeyError, TypeError, RecursionError):
            stored = await save_scoped(factory, "gitlab", web, "unavailable", None)
    return GitLabOut(
        state=stored["state"],
        stale=stored["state"] != "ready",
        checked_at=stored.get("checked_at"),
        **(stored.get("data") or {}),
    )


async def verified_pipeline(settings, revision):
    """Fresh exact-revision evidence. Never interpret prose or a different branch's success."""
    try:
        host, project, web = await asyncio.to_thread(gitlab_origin, settings.workspace)
        rows = await glab_get(
            settings.workspace,
            host,
            project,
            "/pipelines?sha=" + revision + "&order_by=id&sort=desc&per_page=1",
        )
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("sha") != revision
            or row.get("status") != "success"
            or type(row.get("id")) is not int
            or row["id"] <= 0
        ):
            return None
        return {
            "pipeline_id": int(row["id"]),
            "revision": revision,
            "url": f"{web}/-/pipelines/{int(row['id'])}",
            "checked_at": now().isoformat(),
        }
    except (ConsoleError, OSError, TimeoutError, ValueError, KeyError, TypeError, RecursionError):
        return None
