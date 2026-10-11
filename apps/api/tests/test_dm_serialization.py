from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


NOW = datetime(2026, 5, 21, 12, 0, 0)


def _participant(
    user: SimpleNamespace,
    *,
    last_read_message_id: str | None = None,
    joined_at: datetime = NOW,
    left_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user.id,
        user=user,
        role="member",
        joined_at=joined_at,
        left_at=left_at,
        muted_at=None,
        last_read_message_id=last_read_message_id,
    )


def _user(
    user_id: str,
    *,
    full_name: str = "User Name",
    display_name: str | None = None,
    email: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email=email or f"{user_id}@example.test",
        full_name=full_name,
        display_name=display_name,
    )
