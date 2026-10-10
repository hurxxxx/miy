from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from miy_api.app import create_app, create_first_party_app
from miy_api.core.settings import get_settings


def test_official_static_paths_and_fixed_compatibility_do_not_shadow_platform_or_files(
    monkeypatch, tmp_path
):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/official-suite/api/src"))
    from miy_official_api.frontend import mount_official_frontend, read_platform_build_id

    (tmp_path / "assets").mkdir()
    (tmp_path / "help/pms").mkdir(parents=True)
    (tmp_path / "index.html").write_text("official reviewed shell")
    (tmp_path / "assets/app.js").write_text("official reviewed module")
    (tmp_path / "recording-sync-sw.js").write_text("official fixed worker")
    (tmp_path / "help/pms/user-guide.html").write_text("official fixed help")
    (tmp_path / ".miy-platform-build-id").write_text("platform-reviewed\n")
    unrelated = tmp_path.parent / "unrelated.txt"
    unrelated.write_text("outside artifact")
    app = FastAPI()
    mount_official_frontend(app, tmp_path, platform_build_id=read_platform_build_id(tmp_path))
    with TestClient(app) as client:
        for path in (
            "/apps/docs/documents/id.with.dot?view=mine",
            "/apps/pms/assigned",
            "/official-suite/widgets",
        ):
            assert client.get(path).text == "official reviewed shell"
        assert client.get("/official-suite/assets/app.js").text == "official reviewed module"
        assert client.get("/official-suite/platform-build.json").json() == {
            "platform_build_id": "platform-reviewed"
        }
        assert (
            client.get("/recording-sync-sw.js", params={"file": str(unrelated)}).text
            == "official fixed worker"
        )
        assert client.head("/help/pms/user-guide.html").status_code == 200
        assert client.get("/help/pms/user-guide.html").text == "official fixed help"
        for path in (
            "/",
            "/login",
            "/apps/home",
            "/api/v1/auth/me",
            "/official-suite/assets/missing.js",
        ):
            assert client.get(path).status_code == 404


def test_official_ui_requires_reviewed_compatibility_metadata(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/official-suite/api/src"))
    from miy_official_api.frontend import read_platform_build_id

    (tmp_path / "index.html").write_text("official shell")
    with pytest.raises(RuntimeError, match="compatibility_missing"):
        read_platform_build_id(tmp_path)
    (tmp_path / ".miy-platform-build-id").write_text("../invalid")
    with pytest.raises(RuntimeError, match="compatibility_invalid"):
        read_platform_build_id(tmp_path)


def test_official_api_and_client_metadata_use_the_same_reviewed_compatibility(
    monkeypatch, tmp_path
):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/official-suite/api/src"))
    from miy_official_api.frontend import mount_official_frontend, read_platform_build_id

    (tmp_path / "index.html").write_text("official shell")
    compatibility = tmp_path / ".miy-platform-build-id"
    compatibility.write_text("reviewed-core-id\n")
    captured_id = read_platform_build_id(tmp_path)
    app = create_first_party_app(
        composition="official", initialize_runtime=False, client_build_id=captured_id
    )
    mount_official_frontend(app, tmp_path, platform_build_id=captured_id)
    compatibility.write_text("other-running-core-id")
    with TestClient(app) as client:
        assert client.get("/official-suite/platform-build.json").json() == {
            "platform_build_id": "reviewed-core-id"
        }
        response = client.get("/api/v1/docs/hub", headers={"X-MIY-Web-Build": "stale-id"})
        assert response.status_code == 409
        assert response.headers["X-MIY-Web-Build"] == captured_id
        assert response.json()["code"] == "CLIENT_BUILD_MISMATCH"
        assert (
            client.get("/api/v1/docs/hub", headers={"X-MIY-Web-Build": captured_id}).status_code
            == 401
        )
        with client.websocket_connect(
            "/api/v1/docs/collab/pages/example/ws?__miy_build=stale-id"
        ) as websocket:
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_text()
            assert closed.value.code == 4409

    compatibility.write_text("\n")
    assert read_platform_build_id(tmp_path) is None


def test_legacy_serves_separate_official_ui_before_portal_fallback(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps/official-suite/api/src"))
    platform = tmp_path / "web"
    official = tmp_path / "official-suite"
    platform.mkdir()
    official.mkdir()
    (official / "assets").mkdir()
    (platform / "index.html").write_text("portal descriptor shell")
    (platform / ".miy-build-id").write_text("paired-platform-id")
    (official / "index.html").write_text("independent official shell")
    (official / ".miy-platform-build-id").write_text("paired-platform-id")
    (official / "assets/app.js").write_text("independent business module")
    monkeypatch.setenv("MIY_API_SERVE_FRONTEND", "1")
    monkeypatch.setenv("MIY_API_FRONTEND_DIST_DIR", str(platform))
    get_settings.cache_clear()
    try:
        with TestClient(create_app(initialize_runtime=False)) as client:
            for path in ("/", "/login", "/apps/home"):
                assert client.get(path).text == "portal descriptor shell"
            for path in (
                "/apps/docs",
                "/apps/docs/documents/id.with.dot",
                "/official-suite/widgets",
            ):
                assert client.get(path).text == "independent official shell"
            assert client.get("/official-suite/assets/app.js").text == "independent business module"
            assert client.get("/official-suite/platform-build.json").json() == {
                "platform_build_id": "paired-platform-id"
            }
            assert client.get("/api/v1/docs/hub").status_code == 401
        with TestClient(
            create_first_party_app(composition="platform", initialize_runtime=False)
        ) as client:
            assert client.get("/apps/docs").text == "portal descriptor shell"
            assert client.get("/official-suite/widgets").text == "portal descriptor shell"
        (official / ".miy-platform-build-id").write_text("unpaired-id")
        with pytest.raises(RuntimeError, match="legacy_official_frontend_compatibility_mismatch"):
            create_app(initialize_runtime=False)
    finally:
        get_settings.cache_clear()
