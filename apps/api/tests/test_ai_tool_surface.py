from __future__ import annotations

from dev_accounts import dev_login
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_engine, get_session_factory
from miy_api.core.principal import CallerPrincipal, user_principal
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.auth.models import CompanyAppControl


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _load_principal(session: dict) -> CallerPrincipal:
    with get_session_factory()() as db:
        user = load_user_graph(db, session["user"]["id"])
        assert user is not None
        principal = user_principal(
            user_id=user.id,
            source="api.stream",
        )
        return principal


def _disable_platform_app(app_id: str) -> None:
    with Session(get_engine()) as db:
        control = db.scalar(select(CompanyAppControl).where(CompanyAppControl.app_id == app_id))
        assert control is not None
        control.enabled = False
        db.add(control)
        db.commit()
