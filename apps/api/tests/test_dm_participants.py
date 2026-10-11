from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


def _conversation(
    *,
    conversation_type: str = "group",
    participants: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_type=conversation_type,
        participants=participants or [],
    )


def _participant(
    user_id: str,
    user: SimpleNamespace,
    *,
    role: str = "member",
    joined_at: datetime | None = None,
    left_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user=user,
        role=role,
        joined_at=joined_at or datetime(2026, 5, 21, 12, 0, 0),
        left_at=left_at,
    )


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)
