from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException

from miy_api import api_registry, official_auth
from miy_api.app import localized_http_exception_handler
from miy_api.api_composition import RouterSpec
from miy_api.core.db import get_db_session
from miy_api.core.app_contracts_generated import OFFICIAL_APP_IDS
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import require_auth_context, require_current_user


def test_official_http_scopes_cover_exactly_the_owned_launcher_apps():
    root = Path(__file__).resolve().parents[3]
    ids = set(json.loads((root / "apps/official-suite/ownership.json").read_text())["ui_app_ids"])
    specs = api_registry.router_specs("official")
    assert {spec.logical_app_id for spec in specs if spec.logical_app_id} == ids
    assert ids == OFFICIAL_APP_IDS
    assert all(spec.logical_app_id is None for spec in specs if spec.protection == "public")
    assert all(spec.logical_app_id is None for spec in api_registry.router_specs("platform"))


@pytest.mark.parametrize("logical_app_id", ["docs", None])
def test_route_scope_precedes_identity_and_cannot_be_selected_by_caller(
    monkeypatch, logical_app_id
):
    router = APIRouter()
    child = APIRouter()

    @child.get("/probe")
    def probe(user=Depends(require_current_user), context=Depends(require_auth_context)):
        return {"id": user.id, "roles": sorted(context.system_roles)}

    router.include_router(child)
    monkeypatch.setattr(
        api_registry,
        "router_specs",
        lambda _composition: (
            RouterSpec(router, "protected", 0, "official", "fixture", logical_app_id),
        ),
    )
    seen = []

    def resolve(db, token, *, logical_app_id):
        seen.append((db, token, logical_app_id))
        return SimpleNamespace(user=SimpleNamespace(id="member"), system_roles=frozenset({"user"}))

    monkeypatch.setattr(official_auth, "resolve_official_auth_context", resolve)
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.dependency_overrides[get_db_session] = lambda: "fixture-db"
    api_registry.register_api_routers(app, get_settings(), composition="official")
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/probe?logical_app_id=pms",
            headers={
                "Authorization": "Bearer fixture-token",
                "X-MIY-App-Id": "pms",
                "X-MIY-User-Id": "admin",
                "X-MIY-System-Roles": "platform_admin",
            },
        )
    if logical_app_id is None:
        assert response.status_code == 403 and not seen
    else:
        assert response.status_code == 200 and response.json() == {
            "id": "member",
            "roles": ["user"],
        }
        assert seen == [("fixture-db", "fixture-token", "docs")]


def test_missing_owned_route_scope_does_not_resolve_identity(monkeypatch):
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.dependency_overrides[get_db_session] = lambda: "fixture-db"

    @app.get("/unowned")
    def unowned(context=Depends(official_auth.require_official_auth_context)):
        pytest.fail("Unowned endpoint accepted a delegated identity")

    monkeypatch.setattr(
        official_auth,
        "resolve_official_auth_context",
        lambda *a, **kw: pytest.fail("Unowned identity lookup"),
    )
    with TestClient(app) as client:
        assert (
            client.get("/unowned", headers={"Authorization": "Bearer fixture-token"}).status_code
            == 403
        )
