from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from miy_api.domains.dm import conversation_membership


NOW = datetime(2026, 5, 21, 12, 0, 0)


class _FakeDb:
    def __init__(self, *, scalar_results=None, scalars_result=None) -> None:
        self.scalar_results = list(scalar_results or [])
        self.scalars_result = scalars_result or []
        self.added = []
        self.added_all = []
        self.commit_count = 0
        self.rollback_count = 0

    def scalar(self, query):  # noqa: ANN001
        return self.scalar_results.pop(0) if self.scalar_results else None

    def scalars(self, query):  # noqa: ANN001
        return self.scalars_result

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    def add_all(self, rows) -> None:  # noqa: ANN001
        self.added_all.extend(list(rows))

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _patch_required_conversation(
    monkeypatch: pytest.MonkeyPatch,
    conversation: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        conversation_membership.conversation_queries,
        "require_user_conversation",
        lambda db, *, current_user, conversation_id: conversation,
    )


def _conversation(
    *,
    conversation_type: str = "group",
    participants: list[SimpleNamespace],
) -> SimpleNamespace:
    return SimpleNamespace(
        id="conversation-1",
        conversation_type=conversation_type,
        title=None,
        participants=participants,
        updated_at=None,
    )


def _participant(
    user: SimpleNamespace,
    *,
    role: str = "member",
    joined_at: datetime = NOW,
    left_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id="conversation-1",
        user_id=user.id,
        user=user,
        role=role,
        joined_at=joined_at,
        left_at=left_at,
        last_read_message_id=None,
    )


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, status="active", email=f"{user_id}@example.test")
