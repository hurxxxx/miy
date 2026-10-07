from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from miy_api import app as app_module
from miy_api.api_registry import router_specs
from miy_api.openapi_contract import assert_openapi_contract


def test_owned_compositions_partition_the_unchanged_legacy_contract() -> None:
    legacy = app_module.create_app(initialize_runtime=False).openapi()
    platform = app_module.create_app(composition="platform", initialize_runtime=False).openapi()
    official = app_module.create_app(composition="official", initialize_runtime=False).openapi()

    def api_paths(schema):
        return {path for path in schema["paths"] if path.startswith("/api/")}

    assert api_paths(platform).isdisjoint(api_paths(official))
    assert api_paths(platform) | api_paths(official) == api_paths(legacy)
    assert "/api/v1/pms/lists" in official["paths"]
    assert "/api/v1/docs/hub" in official["paths"]
    assert "/api/v1/chatbot/chat" in platform["paths"]
    assert "/api/v1/independent-apps/catalog" in platform["paths"]
    for schema in (platform, official):
        assert_openapi_contract(schema)
        for path in api_paths(schema):
            assert schema["paths"][path] == legacy["paths"][path]
    specs = router_specs()
    assert [spec.position for spec in specs] == list(range(len(specs)))
    assert {spec.owner for spec in router_specs("platform")} == {"platform"}
    assert {spec.owner for spec in router_specs("official")} == {"official"}
    owner = Path(__file__).resolve().parents[3] / "apps/official-suite/ownership.json"
    assert {spec.source for spec in router_specs("official")} == set(
        json.loads(owner.read_text())["api_modules"]
    )


@pytest.mark.parametrize("composition", ["platform", "official"])
def test_split_artifact_health_is_not_activation_or_readiness(monkeypatch, composition) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Inactive artifacts must not touch shared runtime or storage")

    for name in (
        "init_db",
        "ensure_bucket",
        "initialize_platform_extensions",
        "get_session_factory",
        "prepare_miy_desktop_update_dirs",
        "mount_frontend",
        "mount_miy_desktop_update_feeds",
        "bootstrap_telemetry",
        "install_stack_dump_signal",
    ):
        monkeypatch.setattr(app_module, name, forbidden)
    api = app_module.create_app(composition=composition, initialize_runtime=False)
    with TestClient(api) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["activation"] == "inactive"
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["code"] == "service_not_activated"
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
        for method in ("GET", "POST", "PUT", "DELETE", "OPTIONS"):
            response = client.request(method, "/api/v1/pms/lists")
            assert response.status_code == 503
            assert response.json() == {"code": "service_not_activated"}
        assert client.post("/healthz").status_code == 503
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/v1/docs/ws/test"):
                pytest.fail("Inactive artifact must not accept WebSocket business traffic")
        assert denied.value.code == 1013
    with pytest.raises(RuntimeError, match="writer cutover"):
        app_module.create_app(composition=composition)


def test_unknown_composition_cannot_fall_back_to_legacy() -> None:
    with pytest.raises(ValueError, match="Unsupported API composition"):
        app_module.create_app(composition="future-profile", initialize_runtime=False)
    with pytest.raises(ValueError, match="Unsupported API composition"):
        router_specs("future-profile")


def test_duplicate_router_ownership_fails_before_mounting(monkeypatch) -> None:
    from miy_api import official_api_registry

    spec = router_specs("platform")[0]
    monkeypatch.setattr(
        official_api_registry,
        "official_router_specs",
        lambda: (replace(spec, position=100, owner="official"),),
    )
    with pytest.raises(ValueError, match="duplicate routers"):
        router_specs()


def test_actual_split_entrypoints_construct_only_inactive_apps(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Importing a split artifact must not initialize the legacy runtime")

    monkeypatch.setattr(app_module, "init_db", forbidden)
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/official-suite/api/src"))
    for module, expected in (
        ("miy_api.platform_main", "platform"),
        ("miy_official_api.main", "official"),
    ):
        artifact = importlib.import_module(module)
        assert artifact.app.state.api_composition == expected
        with TestClient(artifact.app) as client:
            assert client.get("/readyz").status_code == 503
