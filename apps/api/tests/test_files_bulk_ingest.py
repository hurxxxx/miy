from __future__ import annotations

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from company_admission_fixture import company_authority_tables, seed_company_app_access

from miy_api.core.db import Base
from miy_api.domains.auth.models import User, UserSystemRole
from miy_api.domains.files import bulk_ingest
from miy_api.domains.files.models import (
    FileManagerBulkIngestEntry,
    FileManagerBulkIngestRun,
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFolder,
    FileManagerStorageCleanupJob,
)
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.search.models import SearchIndexJob


ADMIN_ID = "admin-a"
MEMBER_ID = "member-a"
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_files_bulk_ingest.py"


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            *company_authority_tables(),
            RuntimeOwnership.__table__,
            RetrievalPartition.__table__,
            FileManagerCorpus.__table__,
            FileManagerFolder.__table__,
            FileManagerFile.__table__,
            FileManagerStorageCleanupJob.__table__,
            FileManagerBulkIngestRun.__table__,
            FileManagerBulkIngestEntry.__table__,
            RetrievalProjectionHead.__table__,
            RetrievalProjectionEvent.__table__,
            SearchIndexJob.__table__,
            RagSyncJob.__table__,
        ],
    )
    with Session(engine) as session:
        session.add(
            RuntimeOwnership(
                scope="official.suite",
                active_owner="legacy",
                generation=1,
                artifact=None,
                state="active",
            )
        )
        session.flush()
        seed_company_app_access(session)
        session.add_all(
            [
                User(
                    id=ADMIN_ID,
                    login_id="operator",
                    email="operator@example.com",
                    full_name="Operator",
                    password_hash="!",
                    status="active",
                    login_blocked=False,
                ),
                User(
                    id=MEMBER_ID,
                    login_id="owner",
                    email="owner@example.com",
                    full_name="Owner",
                    password_hash="!",
                    status="active",
                    login_blocked=False,
                ),
            ]
        )
        session.add(UserSystemRole(id="operator-role", user_id=ADMIN_ID, role="platform_admin"))
        session.commit()
        yield session


def test_control_plane_admin_can_assign_only_an_authorized_ingest_owner(db: Session) -> None:
    owner = db.get(User, MEMBER_ID)
    assert owner is not None
    with pytest.raises(bulk_ingest.FilesBulkIngestError, match="run_owner_access_required"):
        bulk_ingest.create_run(
            db,
            actor=_actor(db),
            owner=owner,
            corpus_name="Denied",
            root_folder_name="Denied",
            idempotency_key="denied-owner",
            manifest_sha256="c" * 64,
            source_root_sha256="d" * 64,
            entries=[_manifest_entry("root.txt", b"root")],
        )
    db.add(UserSystemRole(id="delegated-operator-role", user_id=owner.id, role="platform_admin"))
    db.flush()
    run = bulk_ingest.create_run(
        db,
        actor=_actor(db),
        owner=owner,
        corpus_name="기술연구소 안전 적재",
        root_folder_name="프로젝트 RAG",
        idempotency_key="member-owned-operation",
        manifest_sha256="c" * 64,
        source_root_sha256="d" * 64,
        entries=[_manifest_entry("root.txt", b"root")],
    )

    root = db.get(FileManagerFolder, run.root_folder_id)
    assert root is not None
    assert root.owner_id == MEMBER_ID
    assert run.created_by_id == ADMIN_ID
    assert run.corpus.created_by_id == ADMIN_ID


def _manifest_entry(path: str, content: bytes) -> bulk_ingest.ManifestEntry:
    return bulk_ingest.ManifestEntry(
        source_path=path,
        size_bytes=len(content),
        content_sha256=sha256(content).hexdigest(),
        content_type="text/plain",
    )


def _actor(db: Session) -> User:
    actor = db.get(User, ADMIN_ID)
    assert actor is not None
    return actor


def _load_script() -> ModuleType:
    spec = spec_from_file_location("test_manage_files_bulk_ingest", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
