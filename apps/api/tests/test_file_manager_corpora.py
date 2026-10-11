from __future__ import annotations

from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from company_admission_fixture import company_authority_tables, seed_company_app_access
from miy_api.core.db import Base
from miy_api.domains.auth.models import User, UserSystemRole
from miy_api.domains.files import service as files_service
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
    FileManagerFolder,
    FileManagerStorageCleanupJob,
)
from miy_api.domains.retrieval.models import RetrievalPartition
from miy_api.domains.source_access.policy import SourceAclPolicy


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            *company_authority_tables(),
            RetrievalPartition.__table__,
            FileManagerCorpus.__table__,
            FileManagerFolder.__table__,
            FileManagerFile.__table__,
            FileManagerFileAccessGrant.__table__,
            FileManagerFileSourceMetadata.__table__,
            FileManagerStorageCleanupJob.__table__,
        ],
    )
    monkeypatch.setattr(files_service, "enqueue_file_retrieval_sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(files_service.file_storage, "put_file_object", lambda **kwargs: None)
    with Session(engine) as session:
        seed_company_app_access(session, ("files",))
        session.add_all(
            [
                User(
                    id=user_id,
                    login_id=user_id,
                    email=f"{user_id}@example.test",
                    full_name=user_id,
                    password_hash="unused",
                )
                for user_id in ("admin", "owner", "reader")
            ]
        )
        session.add(UserSystemRole(id="platform-role", user_id="admin", role="platform_admin"))
        session.commit()
        yield session
    engine.dispose()


def _folder(db, *, owner="admin", corpus_id=None, parent_id=None, acknowledge=True):
    return files_service.create_folder(
        db,
        user=db.get(User, owner),
        name="Folder",
        parent_id=parent_id,
        visibility="private",
        corpus_id=corpus_id,
        company_admin_read_acknowledged=acknowledge,
    )


def _file(
    db, *, owner="admin", corpus_id=None, folder_id=None, visibility="private", acknowledge=True
):
    return files_service.upload_file(
        db,
        user=db.get(User, owner),
        filename="report.txt",
        content_type="text/plain",
        content=BytesIO(b"test"),
        size_bytes=4,
        folder_id=folder_id,
        visibility=visibility,
        corpus_id=corpus_id,
        company_admin_read_acknowledged=acknowledge,
    )


def _policy(db, user_id):
    return SourceAclPolicy.for_user(db, user=db.get(User, user_id))


def test_non_admin_cannot_ingest_company_corpus_even_with_app_admission(db):
    corpus = files_service.create_file_corpus(db, user=db.get(User, "admin"), name="Records")
    with pytest.raises(files_service.FileCorpusAccessDenied):
        _folder(db, owner="owner", corpus_id=corpus.id)
    with pytest.raises(files_service.FileCorpusAccessDenied):
        _file(db, owner="owner", corpus_id=corpus.id)
