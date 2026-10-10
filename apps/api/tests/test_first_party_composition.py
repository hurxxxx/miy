from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from miy_api.app import create_app, create_first_party_app
from miy_api import app as app_module
from miy_api import external_runtime
from miy_api.domains.auth.dependencies import require_auth_context
from miy_api.first_party_routes import nginx_owner_map, nginx_client_owner_map


def test_first_party_routes_partition_legacy_without_delegated_authentication():
    legacy = create_app(initialize_runtime=False).openapi()
    platform = create_first_party_app(composition="platform", initialize_runtime=False)
    official = create_first_party_app(composition="official", initialize_runtime=False)
    schemas = [app.openapi() for app in (platform, official)]
    paths = [{path for path in schema["paths"] if path.startswith("/api/")} for schema in schemas]
    assert paths[0].isdisjoint(paths[1])
    assert paths[0] | paths[1] == {path for path in legacy["paths"] if path.startswith("/api/")}
    for app, schema in zip((platform, official), schemas):
        assert require_auth_context not in app.dependency_overrides
        for path in schema["paths"]:
            if path.startswith("/api/"):
                assert schema["paths"][path] == legacy["paths"][path]
    with TestClient(official) as client:
        assert client.get("/api/v1/docs/hub").status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 404
        assert client.get("/healthz").json()["authority"] == "first_party_shared_database"
    with pytest.raises(ValueError, match="one router owner"):
        create_first_party_app(composition="legacy", initialize_runtime=False)


def test_ingress_projection_keeps_official_collaboration_and_common_realtime_separate():
    projection = nginx_owner_map()
    assert "default platform;" in projection
    assert "/api/v1/docs/collab/pages/" in projection
    assert "/api/v1/whiteboard/collab/items/" in projection
    assert "/api/v1/realtime/" not in projection
    assert "(?P<" not in projection
    client_projection = nginx_client_owner_map()
    assert "map $uri $miy_ui_owner" in client_projection
    assert "/apps/docs" in client_projection
    assert "/official" in client_projection
    assert "/apps/home" not in client_projection
    with pytest.raises(ValueError, match="prefix_invalid"):
        nginx_owner_map(api_prefix='/api/v1"; invalid')


def test_platform_keeps_the_owned_frontend_and_update_mounts(monkeypatch):
    mounted = []

    def mount_frontend(app, _settings):
        mounted.append("frontend")

        @app.get("/")
        def portal():
            return {"portal": "login"}

    def mount_updates(app, _settings, _dirs):
        mounted.append("updates")

        @app.get("/test-owned-update-feed")
        def update_feed():
            return {"feed": "owned"}

    monkeypatch.setattr(app_module, "mount_frontend", mount_frontend)
    monkeypatch.setattr(app_module, "mount_miy_desktop_update_feeds", mount_updates)
    with TestClient(
        create_first_party_app(composition="platform", initialize_runtime=False)
    ) as client:
        assert client.get("/").json() == {"portal": "login"}
        assert client.get("/test-owned-update-feed").json() == {"feed": "owned"}
    assert mounted == ["updates", "frontend"]
    mounted.clear()
    with TestClient(
        create_first_party_app(composition="official", initialize_runtime=False)
    ) as client:
        assert client.get("/").status_code == 404
    assert mounted == []


@pytest.mark.parametrize(
    "composition,expected",
    [("platform", ["terminal", "realtime"]), ("official", ["realtime", "docs", "whiteboard"])],
)
def test_owned_runtime_starts_only_owned_services_and_joins_reverse_cleanup(
    monkeypatch, composition, expected
):
    events = []

    class Service:
        def __init__(self, name):
            self.name = name

        async def startup(self):
            events.append("start:" + self.name)

        async def shutdown(self):
            events.append("stop:" + self.name)

    monkeypatch.setattr(external_runtime, "AgentTerminalRuntime", lambda *_a: Service("terminal"))
    monkeypatch.setattr(external_runtime, "AppRealtimeHub", lambda *_a, **_kw: Service("realtime"))
    monkeypatch.setattr(external_runtime, "DocsCollabHub", lambda: Service("docs"))
    monkeypatch.setattr(external_runtime, "WhiteboardCollabHub", lambda: Service("whiteboard"))
    monkeypatch.setattr(external_runtime, "get_session_factory", lambda: object())
    runtime = external_runtime.FirstPartyApiExternalRuntime(
        composition=composition,
        settings=SimpleNamespace(
            realtime_redis_url="redis://unused.invalid/0", instance_id="owned"
        ),
    )
    runtime.prepare()

    async def run():
        async with runtime.activate(FastAPI()):
            assert events == ["start:" + name for name in expected]

    asyncio.run(run())
    assert events == ["start:" + name for name in expected] + [
        "stop:" + name for name in reversed(expected)
    ]
