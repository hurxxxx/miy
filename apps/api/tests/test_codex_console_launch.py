import pytest
from pydantic import ValidationError

from dev_accounts import create_company_user_session, dev_login
from miy_api.core.settings import Settings, get_settings


def _catalog(client, session, *, host=None):
    headers = {"Authorization": f"Bearer {session['token']}"}
    if host is not None:
        headers["host"] = host
    response = client.get("/api/v1/apps/bootstrap", headers=headers)
    assert response.status_code == 200
    return {a["app_id"]: a for a in response.json()["apps"]}


def test_console_launch_requires_configuration_admission_and_admin(client, monkeypatch):
    admin = dev_login(client, "administrator")
    settings = get_settings()
    monkeypatch.setattr(settings, "codex_console_launch_url", "")
    monkeypatch.setattr(settings, "codex_console_launch_url_by_host", {})
    assert "codex-console" not in _catalog(client, admin)
    monkeypatch.setattr(settings, "codex_console_launch_url", "/codex-console/")
    app = _catalog(client, admin)["codex-console"]
    assert app["launch_url"] == "/codex-console/"
    assert app["execution_context_kind"] == "personal"
    monkeypatch.setattr(
        settings,
        "codex_console_launch_url_by_host",
        {"demo.example.test:4200": "https://console.example.test/"},
    )
    assert (
        _catalog(client, admin, host="demo.example.test:4200")["codex-console"]["launch_url"]
        == "https://console.example.test/"
    )
    assert (
        _catalog(client, admin, host="unmapped.example.test")["codex-console"]["launch_url"]
        == "/codex-console/"
    )
    member = create_company_user_session(
        client,
        login_id="console-member",
        email="console-member@example.test",
        full_name="Console Member",
    )
    assert "codex-console" not in _catalog(client, member)
    response = client.put(
        "/api/v1/admin/apps/codex-console/access-policy",
        headers={"Authorization": f"Bearer {admin['token']}"},
        json={"enabled": False, "audience": "selected"},
    )
    assert response.status_code == 200
    assert "codex-console" not in _catalog(client, admin)


@pytest.mark.parametrize("url", ["javascript:alert(1)"])
def test_console_launch_url_rejects_unsafe_destinations(url):
    with pytest.raises(ValidationError):
        Settings(codex_console_launch_url=url)
