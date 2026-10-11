from __future__ import annotations

from types import SimpleNamespace


def _conversation(
    *,
    conversation_type: str,
    participants: list[SimpleNamespace],
    title: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_type=conversation_type,
        title=title,
        participants=participants,
    )


def _participant(user: SimpleNamespace, *, left_at=None) -> SimpleNamespace:
    return SimpleNamespace(user_id=user.id, user=user, left_at=left_at)


def _user(
    user_id: str,
    *,
    display_name: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        display_name=display_name,
        full_name=full_name,
        email=email or f"{user_id}@example.test",
    )
