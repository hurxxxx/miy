from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from miy_api.domains.content_access import grants
from miy_api.domains.content_access.grants import (
    ContentGrantIssuer,
    InvalidContentGrant,
    decode_content_grant,
)
from miy_api.domains.files import content_access
from miy_api.domains.files.content_access import (
    build_file_content_url,
    open_file_content_grant,
)
from miy_api.domains.files.models import FileManagerCorpus, FileManagerFile


_USER_ID = "user-1"
_SESSION_ID = "session-1"


def _settings() -> SimpleNamespace:
    return SimpleNamespace(api_prefix="/api/v1", content_grant_signing_key="test-secret")


def _file(**overrides: object) -> FileManagerFile:
    values = {
        "id": "file-1",
        "folder_id": None,
        "owner_id": _USER_ID,
        "filename": "diagram final.png",
        "content_type": "image/png; charset=binary",
        "size_bytes": 9,
        "storage_key": "objects/file-1",
        "visibility": "private",
    }
    values.update(overrides)
    return FileManagerFile(**values)


def _corpus(*, scope: str = "company", metadata_version: int = 1) -> FileManagerCorpus:
    return FileManagerCorpus(
        id="corpus-1",
        name="Company handbook",
        access_scope_kind=scope,
        retrieval_partition_id="11111111-1111-1111-1111-111111111111",
        created_by_id=_USER_ID,
        metadata_version=metadata_version,
    )


class _FakeDb:
    def __init__(self, file: FileManagerFile | None) -> None:
        self.file = file
        self.user = SimpleNamespace(id=_USER_ID, status="active", login_blocked=False)

    def scalar(self, _statement: object) -> FileManagerFile | None:
        return self.file

    def get(self, model, identity):
        if model is content_access.User and identity == _USER_ID:
            return self.user
        return None


class _FakeObject:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.closed = False
        self.released = False

    def stream(self, _chunk_size: int):
        yield from self.chunks

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


def _claims(monkeypatch, file: FileManagerFile, *, disposition="attachment"):
    monkeypatch.setattr(grants, "get_settings", _settings)
    url = build_file_content_url(
        file,
        issuer=ContentGrantIssuer(user_id=_USER_ID, session_id=_SESSION_ID),
        disposition=disposition,
        now=100,
        expires_seconds=60,
    )
    token = parse_qs(urlparse(url).fragment)["grant"][0]
    return url, decode_content_grant(token, now=100)


def _allow_source(monkeypatch, file: FileManagerFile) -> None:
    monkeypatch.setattr(
        content_access.files_service,
        "require_file_access",
        lambda db, *, user, file_id: file,
    )


def test_corpus_transition_and_object_replacement_revoke_existing_grants(monkeypatch) -> None:
    corpus = _corpus(metadata_version=1)
    file = _file(corpus_id=corpus.id)
    file.corpus = corpus
    _, transition_claims = _claims(monkeypatch, file)
    corpus.metadata_version = 2
    with pytest.raises(InvalidContentGrant, match="binding"):
        open_file_content_grant(_FakeDb(file), claims=transition_claims)

    replacement = _file()
    _, object_claims = _claims(monkeypatch, replacement)
    replacement.storage_key = "objects/replacement"
    with pytest.raises(InvalidContentGrant, match="binding"):
        open_file_content_grant(_FakeDb(replacement), claims=object_claims)
