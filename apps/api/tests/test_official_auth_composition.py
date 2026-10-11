from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from miy_api import api_registry, official_auth
from miy_api.api_composition import RouterSpec
from miy_api.app import localized_http_exception_handler
from miy_api.core.db import get_db_session
from miy_api.core.settings import get_settings
from miy_api.domains.auth.dependencies import require_auth_context, require_current_user


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
