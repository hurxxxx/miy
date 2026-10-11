from __future__ import annotations

from types import SimpleNamespace

import pytest

from miy_api.domains.dm import attachment_records


from miy_api.domains.dm.models import DmMessageAttachment


def _patch_attachment_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    storage: "_FakeAttachmentStorage",
) -> list[tuple[str, str]]:
    checked: list[tuple[str, str]] = []

    def require_user_conversation(db, *, current_user, conversation_id):  # noqa: ANN001
        checked.append((current_user.id, conversation_id))
        return SimpleNamespace(id=conversation_id, participants=[])

    monkeypatch.setattr(
        attachment_records.conversation_queries,
        "require_user_conversation",
        require_user_conversation,
    )
    monkeypatch.setattr(attachment_records, "new_id", lambda: "attachment-1")
    monkeypatch.setattr(
        attachment_records.attachment_persistence.attachment_storage,
        "dm_attachment_storage",
        lambda: storage,
    )
    return checked


def _attachment(*, content_type: str = "image/png") -> DmMessageAttachment:
    return DmMessageAttachment(
        id="attachment-1",
        conversation_id="conversation-1",
        message_id=None,
        uploader_id="user-1",
        filename="file.png",
        content_type=content_type,
        size_bytes=12,
        storage_key="dm/conversation-1/attachment-1/file.png",
    )


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


class _FakeDb:
    def __init__(self, *, attachment=None, commit_error: Exception | None = None) -> None:
        self.attachment = attachment
        self.commit_error = commit_error
        self.added = []
        self.refreshed = []
        self.flushed = False
        self.committed = False
        self.rollback_count = 0

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    def flush(self) -> None:
        self.flushed = True

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    def refresh(self, row) -> None:  # noqa: ANN001
        self.refreshed.append(row)

    def rollback(self) -> None:
        self.rollback_count += 1

    def scalar(self, query):
        return "user-1"

    def get(self, model, key: str):  # noqa: ANN001
        assert model is DmMessageAttachment
        assert key == "attachment-1"
        return self.attachment


class _FakeAttachmentStorage:
    def __init__(self, *, put_error: Exception | None = None) -> None:
        self.put_error = put_error
        self.put_calls = []
        self.remove_calls = []

    def put(
        self,
        storage_key: str,
        *,
        content,  # noqa: ANN001
        size_bytes: int,
        content_type: str,
    ) -> None:
        if self.put_error is not None:
            raise self.put_error
        assert content.tell() == 0
        self.put_calls.append((storage_key, size_bytes, content_type))

    def remove(self, *, storage_key: str) -> None:
        self.remove_calls.append(storage_key)
