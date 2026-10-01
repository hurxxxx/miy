"""Authenticated forwarding to the persisted execution owner, never arbitrary targets."""

import re

import httpx
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from . import store
from .errors import ConsoleError


def execution_target(factory, path, query):
    if path.startswith("/api/templates/") and (
        path.endswith("/run") or path == "/api/templates/catalog"
    ):
        return "templates"
    task_id = None
    match = re.match(r"^/api/tasks/([0-9a-f-]{36})(?:/|$)", path)
    if match:
        task_id = match[1]
    elif path == "/api/codex/models":
        task_id = query.get("task_id")
    if task_id:
        with factory() as db:
            return store.require_task(db, task_id).executor
    if path.startswith(("/api/tasks", "/api/codex")):
        return "session"
    return None


async def forward(request, target):
    cfg = request.app.state.settings
    port = cfg.template_port if target == "templates" else cfg.port
    path = request.url.path.removeprefix(cfg.base_path)
    client = httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(125, connect=3, read=None if path.endswith("/events") else 125),
    )
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower()
        in {
            "host",
            "origin",
            "cookie",
            "x-csrf-token",
            "content-type",
            "content-length",
            "x-file-name",
            "last-event-id",
        }
    }
    url = f"http://127.0.0.1:{port}{path}"
    try:
        response = await client.send(
            client.build_request(
                request.method,
                url,
                params=request.query_params,
                headers=headers,
                content=request.stream(),
            ),
            stream=True,
        )
    except httpx.HTTPError:
        await client.aclose()
        return JSONResponse(
            {
                "code": "template_runner_unavailable"
                if target == "templates"
                else "codex_unavailable"
            },
            status_code=503,
        )

    async def close():
        await response.aclose()
        await client.aclose()

    safe_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower()
        in {"content-type", "content-disposition", "cache-control", "x-accel-buffering"}
    }
    if 300 <= response.status_code < 400:
        await close()
        raise ConsoleError("request_failed", 502)
    return StreamingResponse(
        response.aiter_bytes(),
        status_code=response.status_code,
        headers=safe_headers,
        background=BackgroundTask(close),
    )
