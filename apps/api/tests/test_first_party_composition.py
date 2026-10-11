from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from miy_api import external_runtime
from miy_api.first_party_routes import nginx_client_owner_map, nginx_owner_map


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
