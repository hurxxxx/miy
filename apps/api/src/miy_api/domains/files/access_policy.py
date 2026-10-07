"""Files-owned read policy shared by browse and bounded selected-file access."""

from __future__ import annotations

from collections.abc import Iterable
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import User
from miy_api.domains.files.external_access import authorize_explicit_file_ids
from miy_api.domains.files.models import FileManagerCorpus, FileManagerFile, FileManagerFolder

ANCESTOR_DEPTH = 32
ANCESTOR_SECONDS = 2.0


def record_visible(visibility: str, owner_id: str, *, user: User) -> bool:
    # Native personal records deliberately have no administrator read override.
    return owner_id == user.id or visibility == "company"


def filter_readable_files(
    db: Session,
    *,
    user: User,
    files: Iterable[FileManagerFile],
    accessible_folder_ids: set[str],
) -> list[FileManagerFile]:
    records = list(files)
    corpus_ids = {file.corpus_id for file in records if file.corpus_id is not None}
    corpora = (
        {
            corpus.id: corpus
            for corpus in db.scalars(
                select(FileManagerCorpus)
                .where(FileManagerCorpus.id.in_(corpus_ids))
                .execution_options(populate_existing=True)
            )
        }
        if corpus_ids
        else {}
    )
    explicit_allowed = authorize_explicit_file_ids(
        db,
        file_ids=[
            file.id
            for file in records
            if (corpus := corpora.get(file.corpus_id)) is not None
            and corpus.authorization_mode == "explicit_grants"
        ],
        user_id=user.id,
    )
    allowed = []
    for file in records:
        if file.corpus_id is not None:
            corpus = corpora.get(file.corpus_id)
            if corpus is None or corpus.access_scope_kind != "company":
                continue
            if corpus.authorization_mode == "explicit_grants" and file.id not in explicit_allowed:
                continue
            allowed.append(file)
        elif record_visible(file.visibility, file.owner_id, user=user) and (
            file.folder_id is None or file.folder_id in accessible_folder_ids
        ):
            allowed.append(file)
    return allowed


def readable_folder_subset(
    db: Session, *, user: User, folder_ids: set[str]
) -> tuple[set[str], bool]:
    """Resolve only candidate ancestors, with an explicit depth/work limit.

    Missing/deleted/hidden ancestors and cycles deny that branch. An unfinished
    branch is not reported as an empty accessible tree: callers expose incomplete.
    The request's transaction-local statement timeout bounds each database call.
    """
    pending = set(folder_ids)
    found: dict[str, FileManagerFolder] = {}
    visited: set[str] = set()
    deadline = time.monotonic() + ANCESTOR_SECONDS
    for _ in range(ANCESTOR_DEPTH):
        if not pending or time.monotonic() >= deadline:
            break
        visited.update(pending)
        rows = list(
            db.scalars(
                select(FileManagerFolder)
                .where(
                    FileManagerFolder.id.in_(pending),
                    FileManagerFolder.deleted_at.is_(None),
                )
                .execution_options(populate_existing=True)
            )
        )
        found.update({row.id: row for row in rows})
        pending = {
            row.parent_id
            for row in rows
            if row.parent_id is not None and row.parent_id not in visited
        }
    incomplete = bool(pending)
    allowed = set()
    for folder_id in folder_ids:
        current: str | None = folder_id
        branch: set[str] = set()
        while current is not None:
            row = found.get(current)
            if (
                row is None
                or current in branch
                or not record_visible(row.visibility, row.owner_id, user=user)
            ):
                break
            branch.add(current)
            current = row.parent_id
        if current is None:
            allowed.add(folder_id)
    return allowed, incomplete
