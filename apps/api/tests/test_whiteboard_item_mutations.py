from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import User
from dev_accounts import dev_login


def _bound_delivery_hub_session() -> Session:
    db = get_session_factory()()
    return db


def _load_user(db: Session, user_id: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id))
    assert user is not None
    return user


def _create_whiteboard(client: TestClient, token: str, *, title: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/whiteboard/items",
        headers=_auth_headers(token),
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_edit_link_share(client: TestClient, token: str, item_id: str) -> str:
    response = client.put(
        f"/api/v1/whiteboard/items/{item_id}/sharing/link",
        headers=_auth_headers(token),
        json={"access_level": "edit"},
    )
    assert response.status_code == 200, response.text
    token_value = response.json()["link_share"]["token"]
    assert isinstance(token_value, str)
    return token_value


def _dev_login(client: TestClient, account_key: str) -> dict[str, Any]:
    return dev_login(client, account_key)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
