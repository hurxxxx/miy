from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from fastapi import HTTPException
import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from miy_api.domains.dm import attachment_persistence
from miy_api.domains.dm.models import DmMessageAttachment


def test_persist_created_attachment_stores_object_and_commits() -> None:
    db = _FakeDb()
    storage = _FakeAttachmentStorage()
    row = _attachment()

    result = attachment_persistence.persist_created_attachment(
        db,
        row=row,
        object_write=_object_write(),
        object_storage=storage,
    )

    assert result is row
    assert db.added == [row]
    assert db.flushed is True
    assert storage.put_calls == [("dm/conversation-1/attachment-1/file.txt", 12, "text/plain")]
    assert db.committed is True
    assert db.refreshed == [row]


def test_persist_created_attachment_rolls_back_when_object_write_fails() -> None:
    db = _FakeDb()
    storage = _FakeAttachmentStorage(put_error=RuntimeError("upload"))

    with pytest.raises(HTTPException) as excinfo:
        attachment_persistence.persist_created_attachment(
            db,
            row=_attachment(),
            object_write=_object_write(),
            object_storage=storage,
        )

    assert excinfo.value.status_code == 502
    assert db.rollback_count == 1
    assert db.committed is False
    assert storage.remove_calls == []


@pytest.mark.parametrize(
    "sqlstate", ["23502", "23503", "23505", "23514", "23P01", "40001", "40P01"]
)
def test_persist_created_attachment_removes_object_when_commit_is_rejected(sqlstate: str) -> None:
    db = _FakeDb(commit_error=_database_error(sqlstate))
    storage = _FakeAttachmentStorage()

    with pytest.raises(HTTPException) as excinfo:
        attachment_persistence.persist_created_attachment(
            db,
            row=_attachment(),
            object_write=_object_write(),
            object_storage=storage,
        )

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail.code == "dm.attachment_save_failed"
    assert db.rollback_count == 1
    assert storage.remove_calls == ["dm/conversation-1/attachment-1/file.txt"]


def test_persist_created_attachment_hides_cleanup_failure_after_commit_error() -> None:
    db = _FakeDb(commit_error=_database_error("23503"))
    storage = _FakeAttachmentStorage(remove_error=RuntimeError("remove"))

    with pytest.raises(HTTPException) as excinfo:
        attachment_persistence.persist_created_attachment(
            db,
            row=_attachment(),
            object_write=_object_write(),
            object_storage=storage,
        )

    assert excinfo.value.status_code == 500
    assert db.rollback_count == 1
    assert storage.remove_calls == ["dm/conversation-1/attachment-1/file.txt"]


def _database_error(sqlstate: str, *, invalidated: bool = False) -> DBAPIError:
    return DBAPIError(
        "COMMIT",
        None,
        psycopg.errors.lookup(sqlstate)("private database error"),
        connection_invalidated=invalidated,
    )


@pytest.mark.parametrize(
    "commit_error",
    [
        RuntimeError("private untyped failure"),
        OSError("private transport failure"),
        _database_error("40003"),
        _database_error("08007"),
        _database_error("08006"),
        _database_error("57014"),
        _database_error("42P01"),
        _database_error("23503", invalidated=True),
        psycopg.errors.ForeignKeyViolation("unwrapped error"),
        DBAPIError("COMMIT", None, SimpleNamespace(sqlstate="23503")),
    ],
)
def test_unknown_commit_outcome_keeps_uploaded_bytes_without_retry(commit_error: Exception) -> None:
    db = _FakeDb(commit_error=commit_error)
    storage = _FakeAttachmentStorage()
    with pytest.raises(HTTPException) as error:
        attachment_persistence.persist_created_attachment(
            db,
            row=_attachment(),
            object_write=_object_write(),
            object_storage=storage,
        )
    assert error.value.status_code == 500
    assert error.value.detail.code == "dm.attachment_save_unknown"
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert db.commit_count == 1 and db.rollback_count == 1
    assert len(storage.put_calls) == 1 and storage.remove_calls == []


def test_rollback_failure_preserves_bytes_and_hides_both_errors() -> None:
    db = _FakeDb(commit_error=_database_error("23503"), rollback_error=OSError("private rollback"))
    storage = _FakeAttachmentStorage()
    with pytest.raises(HTTPException) as error:
        attachment_persistence.persist_created_attachment(
            db,
            row=_attachment(),
            object_write=_object_write(),
            object_storage=storage,
        )
    assert error.value.detail.code == "dm.attachment_save_unknown"
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert db.commit_count == 1 and db.rollback_count == 1
    assert len(storage.put_calls) == 1 and storage.remove_calls == []


def _object_write() -> attachment_persistence.DmAttachmentObjectWrite:
    return attachment_persistence.DmAttachmentObjectWrite(
        storage_key="dm/conversation-1/attachment-1/file.txt",
        content=BytesIO(b"attachment"),
        size_bytes=12,
        content_type="text/plain",
    )


def _attachment() -> DmMessageAttachment:
    return DmMessageAttachment(
        id="attachment-1",
        conversation_id="conversation-1",
        message_id=None,
        uploader_id="user-1",
        filename="file.txt",
        content_type="text/plain",
        size_bytes=12,
        storage_key="dm/conversation-1/attachment-1/file.txt",
    )


class _FakeDb:
    def __init__(
        self, *, commit_error: Exception | None = None, rollback_error: Exception | None = None
    ) -> None:
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.added = []
        self.refreshed = []
        self.flushed = False
        self.committed = False
        self.rollback_count = 0
        self.commit_count = 0

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    def flush(self) -> None:
        self.flushed = True

    def commit(self) -> None:
        self.commit_count += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    def rollback(self) -> None:
        self.rollback_count += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def refresh(self, row) -> None:  # noqa: ANN001
        self.refreshed.append(row)


class _FakeAttachmentStorage:
    def __init__(
        self,
        *,
        put_error: Exception | None = None,
        remove_error: Exception | None = None,
    ) -> None:
        self.put_error = put_error
        self.remove_error = remove_error
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
        if self.remove_error is not None:
            raise self.remove_error
