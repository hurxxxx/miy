from fastapi import WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from miy_api.app import create_app
from miy_api.core.settings import get_settings


@pytest.fixture
def frontend(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    (tmp_path / ".miy-build-id").write_text("build-current\n")
    (tmp_path / "recording-sync-sw.js").write_text("// sw")
    (assets / "app.js").write_text("console.log('ok');")
    monkeypatch.setenv("MIY_API_SERVE_FRONTEND", "1")
    monkeypatch.setenv("MIY_API_FRONTEND_DIST_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield create_app(initialize_runtime=False)
    finally:
        get_settings.cache_clear()


def test_real_frontend_mount_keeps_asset_spa_and_reserved_routes_distinct(frontend):
    client = TestClient(frontend)
    response = client.get("/apps/meeting/meetings/example")
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert response.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
    asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and asset.text == "console.log('ok');"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    worker = client.get("/recording-sync-sw.js")
    assert worker.status_code == 200
    assert worker.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
    missing = client.get("/assets/PMSView-old.js")
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
    reserved = client.get("/api/not-a-real-route")
    assert reserved.status_code == 404
    assert '<div id="root"></div>' not in reserved.text
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/not-a-real-websocket"):
            pass
    assert closed.value.code == 1008


def test_real_frontend_guard_blocks_stale_post_before_handler_and_allows_current(frontend):
    calls = []

    @frontend.post("/api/test-write")
    async def write(payload: dict[str, bool]):
        calls.append(payload)
        return {"ok": True}

    # Register the probe before the real terminal frontend mount, as product routes are.
    frontend.router.routes.insert(0, frontend.router.routes.pop())
    client = TestClient(frontend)
    headers = {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "empty"}
    stale = client.post(
        "/api/test-write", headers={**headers, "X-MIY-Web-Build": "build-old"}, json={"write": True}
    )
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"
    assert stale.headers["x-miy-reload-required"] == "1"
    assert stale.headers["x-miy-web-build"] == "build-current"
    assert stale.json()["code"] == "CLIENT_BUILD_MISMATCH"
    assert calls == []
    missing = client.post("/api/test-write", headers=headers, json={"write": True})
    assert missing.status_code == 409 and calls == []
    current = client.post(
        "/api/test-write",
        headers={**headers, "X-MIY-Web-Build": "build-current"},
        json={"write": False},
    )
    assert current.status_code == 200 and calls == [{"write": False}]


def test_real_frontend_websocket_accepts_before_stale_close_without_calling_handler(frontend):
    calls = []
    frames = []

    @frontend.websocket("/api/test-socket")
    async def socket(websocket: WebSocket):
        calls.append(True)
        await websocket.accept()
        await websocket.send_text("current")
        await websocket.close()

    frontend.router.routes.insert(0, frontend.router.routes.pop())

    async def observed(scope, receive, send):
        async def record(message):
            if scope["type"] == "websocket":
                frames.append(message)
            await send(message)

        await frontend(scope, receive, record)

    client = TestClient(observed)
    with client.websocket_connect("/api/test-socket?__miy_build=build-old") as stale:
        with pytest.raises(WebSocketDisconnect) as closed:
            stale.receive_text()
    assert closed.value.code == 4409 and calls == []
    assert frames == [
        {"type": "websocket.accept"},
        {"type": "websocket.close", "code": 4409, "reason": "CLIENT_BUILD_MISMATCH"},
    ]
    with client.websocket_connect("/api/test-socket?__miy_build=build-current") as current:
        assert current.receive_text() == "current"
    assert calls == [True]
