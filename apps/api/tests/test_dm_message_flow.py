from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


NOW = datetime(2026, 5, 21, 12, 0, 0)


class _FakeDb:
    def __init__(
        self,
        attachments: list[SimpleNamespace],
        *,
        scalar_row: SimpleNamespace | None = None,
    ) -> None:
        self.attachments = attachments
        self.scalar_row = scalar_row

    def scalars(self, query):  # noqa: ANN001
        return self.attachments

    def scalar(self, query):  # noqa: ANN001
        return self.scalar_row


def _conversation(
    *,
    participants: list[SimpleNamespace],
    message_seq: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="conversation-1",
        participants=participants,
        message_seq=message_seq,
        updated_at=None,
    )


def _participant(user: SimpleNamespace, *, left_at=None) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user.id,
        user=user,
        joined_at=NOW,
        left_at=left_at,
        last_read_message_id=None,
    )


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email=f"{user_id}@example.test", status="active")


def _attachment(
    attachment_id: str,
    *,
    conversation_id: str = "conversation-1",
    uploader_id: str = "sender",
    message_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=attachment_id,
        conversation_id=conversation_id,
        uploader_id=uploader_id,
        message_id=message_id,
        filename=f"{attachment_id}.txt",
    )
