from __future__ import annotations

from fastapi.testclient import TestClient

from test_meeting import _auth_headers, _bootstrap_admin_session, _create_company_user, _login

_BASE = "/api/v1/announcements"


def test_announcement_default_and_explicit_company_audience_require_active_company_user(
    client: TestClient,
) -> None:
    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.models import User

    admin = _bootstrap_admin_session(client)
    other = _create_company_user(
        client,
        admin["token"],
        email="ann-colleague@miy.local",
        full_name="Company Colleague",
    )
    other_token = _login(client, other["user"]["email"], other["temporary_password"])
    forbidden = client.post(
        _BASE,
        headers=_auth_headers(other_token),
        json={"title": "Unauthorized company announcement", "scope": "company"},
    )
    assert forbidden.status_code == 403
    created = client.post(
        _BASE,
        headers=_auth_headers(admin["token"]),
        json={"title": "Company audience"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "company"
    resource_id = created.json()["id"]
    listing = client.get(_BASE, headers=_auth_headers(other_token))
    assert listing.status_code == 200, listing.text
    assert resource_id in {item["id"] for item in listing.json()["items"]}
    assert (
        client.get(f"{_BASE}/{resource_id}", headers=_auth_headers(other_token)).status_code == 200
    )
    with get_session_factory()() as db:
        db.get(User, other["user"]["id"]).login_blocked = True
        db.commit()
    assert client.get(_BASE, headers=_auth_headers(other_token)).status_code == 403
    assert (
        client.get(f"{_BASE}/{resource_id}", headers=_auth_headers(other_token)).status_code == 403
    )
