from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from miy_api.domains.auth.access import serialize_auth_user
from miy_api.domains.auth.models import User


def admin_user_list_projection(db: Session, users: list[User]) -> list[dict[str, Any]]:
    return [serialize_auth_user(db, user) for user in users]
