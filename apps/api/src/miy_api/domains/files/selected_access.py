"""Files-owned bounded selection, descriptor and current source authorization."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.models import User
from miy_api.domains.files.access_policy import filter_readable_files, readable_folder_subset
from miy_api.domains.files.content_access import (
    file_content_acl_binding,
    file_content_object_identity,
)
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.files.selected_storage import MAX_BYTES

SCAN_LIMIT = 200


class SelectedFileDenied(ValueError):
    pass


@dataclass(frozen=True)
class SelectedFileDescriptor:
    file_id: str
    name: str
    content_type: str
    size_bytes: int
    version: str
    storage_key: str


@dataclass(frozen=True)
class SelectedFilePage:
    items: list[SelectedFileDescriptor]
    after: str | None
    incomplete: bool


def _user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id, populate_existing=True)
    if (
        user is None
        or user.status != "active"
        or user.login_blocked
        or user.must_change_password
        or not can_use_app(db, app_id="files", user_id=user.id)
    ):
        raise SelectedFileDenied("source_access")
    return user


def _descriptor(file: FileManagerFile) -> SelectedFileDescriptor:
    version = hashlib.sha256(
        json.dumps(
            [file_content_object_identity(file), file_content_acl_binding(file)],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    return SelectedFileDescriptor(
        file_id=file.id,
        name=file.filename[:255],
        content_type=file.content_type or "application/octet-stream",
        size_bytes=file.size_bytes,
        version=version,
        storage_key=file.storage_key,
    )


def _allowed(db: Session, user: User, files: list[FileManagerFile]):
    folders, incomplete = readable_folder_subset(
        db,
        user=user,
        folder_ids={file.folder_id for file in files if file.corpus_id is None and file.folder_id},
    )
    return filter_readable_files(
        db,
        user=user,
        files=files,
        accessible_folder_ids=folders,
    ), incomplete


def selected_file(db: Session, *, user_id: str, file_id: str) -> SelectedFileDescriptor:
    user = _user(db, user_id)
    file = db.scalar(
        select(FileManagerFile)
        .options(joinedload(FileManagerFile.corpus))
        .where(FileManagerFile.id == file_id, FileManagerFile.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    if file is None:
        raise SelectedFileDenied("source_access")
    allowed, _ = _allowed(db, user, [file])
    if not allowed:
        raise SelectedFileDenied("source_access")
    return _descriptor(file)


def selection_candidates(
    db: Session, *, user_id: str, query: str, after: str | None, limit: int
) -> SelectedFilePage:
    if len(query) > 120 or not 1 <= limit <= 25:
        raise ValueError("selection_query")
    user = _user(db, user_id)
    statement = (
        select(FileManagerFile)
        .options(joinedload(FileManagerFile.corpus))
        .where(
            FileManagerFile.deleted_at.is_(None),
            FileManagerFile.size_bytes.between(0, MAX_BYTES),
        )
        .order_by(FileManagerFile.id)
        .limit(SCAN_LIMIT + 1)
        .execution_options(populate_existing=True)
    )
    if query:
        statement = statement.where(FileManagerFile.filename.icontains(query, autoescape=True))
    if after is not None:
        statement = statement.where(FileManagerFile.id > after)
    rows = list(db.scalars(statement))
    scanned = rows[:SCAN_LIMIT]
    allowed, incomplete = _allowed(db, user, scanned)
    by_id = {row.id: row for row in allowed}
    items = []
    consumed = 0
    last = None
    for row in scanned:
        consumed += 1
        last = row.id
        if row.id in by_id:
            items.append(_descriptor(by_id[row.id]))
            if len(items) == limit:
                break
    more = consumed < len(rows)
    return SelectedFilePage(items, last if more else None, incomplete or more)
