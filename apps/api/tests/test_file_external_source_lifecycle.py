from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from company_admission_fixture import company_authority_tables, seed_company_app_access

from miy_api.core.db import Base
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.auth.models import User, UserSystemRole
from miy_api.domains.pms.space_models import Team, TeamMember, SpaceGroupBinding
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.source_access.policy import SourceAclPolicy
from miy_api.domains.files import external_lifecycle, service as files_service
from miy_api.domains.files.external_lifecycle import ExternalFileGrant
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
    FileManagerFolder,
    FileManagerStorageCleanupJob,
)
from miy_api.domains.files.source_access import (
    can_read_file,
)
from miy_api.domains.rag.contracts import RagSyncOperation
from miy_api.domains.retrieval.models import RetrievalPartition


CORPUS_ID = "corpus-source"
PARTITION_ID = "11111111111111111111111111111111"
PLATFORM_ADMIN_ID = "platform-admin"
UNGRANTED_USER_ID = "ungranted-user"
MEMBER_ID = "member"
OTHER_ID = "other-user"
TEAM_MEMBER_ID = "team-member"
TEAM_ID = "team-search"
OTHER_TEAM_ID = "team-other"


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
            Team.__table__,
            TeamMember.__table__,
            SpaceGroupBinding.__table__,
            RetrievalPartition.__table__,
            FileManagerCorpus.__table__,
            FileManagerFolder.__table__,
            FileManagerFile.__table__,
            FileManagerFileSourceMetadata.__table__,
            FileManagerFileAccessGrant.__table__,
            FileManagerStorageCleanupJob.__table__,
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
        session.flush()
        session.add_all(
            [
                _user(PLATFORM_ADMIN_ID),
                _user(UNGRANTED_USER_ID),
                _user(MEMBER_ID),
                _user(OTHER_ID),
                _user(TEAM_MEMBER_ID),
            ]
        )
        session.flush()
        session.add_all(
            [
                UserSystemRole(
                    id="platform-admin-role",
                    user_id=PLATFORM_ADMIN_ID,
                    role="platform_admin",
                ),
                Team(
                    id=TEAM_ID,
                    key="search",
                    name="Search",
                ),
                Team(
                    id=OTHER_TEAM_ID,
                    key="other-search",
                    name="Other Search",
                ),
            ]
        )
        session.flush()
        session.add(Group(id="source-group", name="Source audience", source="local"))
        session.flush()
        session.add(GroupMember(group_id="source-group", user_id=MEMBER_ID))
        session.add(
            TeamMember(
                id="team-member-link",
                team_id=TEAM_ID,
                user_id=TEAM_MEMBER_ID,
                role="member",
            )
        )
        session.add(
            TeamMember(
                id="other-team-member-link",
                team_id=OTHER_TEAM_ID,
                user_id=TEAM_MEMBER_ID,
                role="member",
            )
        )
        session.add(
            RetrievalPartition(
                id=PARTITION_ID,
                source_namespace="files",
                candidate_scope_kind="company",
                candidate_user_id=None,
                state="active",
                metadata_version=1,
                is_default_ingest=False,
            )
        )
        session.flush()
        session.add(
            FileManagerCorpus(
                id=CORPUS_ID,
                name="External documents",
                access_scope_kind="company",
                retrieval_partition_id=PARTITION_ID,
                created_by_id=PLATFORM_ADMIN_ID,
                source_managed=True,
                authorization_mode="explicit_grants",
            )
        )
        session.commit()
        yield session


@pytest.fixture
def lifecycle_spies(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    stored: dict[str, bytes] = {}
    removed_storage_keys: list[str] = []
    sync_operations: list[RagSyncOperation] = []

    def put_file_object(*, storage_key, content, size_bytes, content_type) -> None:
        del content_type
        stored[storage_key] = content.read(size_bytes)

    def enqueue_sync(db, *, file, operation) -> None:
        del db, file
        sync_operations.append(operation)

    def remove_storage_object(storage_key: str) -> None:
        removed_storage_keys.append(storage_key)
        stored.pop(storage_key, None)

    monkeypatch.setattr(external_lifecycle.file_storage, "put_file_object", put_file_object)
    monkeypatch.setattr(external_lifecycle, "enqueue_file_retrieval_sync", enqueue_sync)
    monkeypatch.setattr(
        files_service,
        "remove_storage_object_immediately",
        remove_storage_object,
    )
    return SimpleNamespace(
        stored=stored,
        removed_storage_keys=removed_storage_keys,
        sync_operations=sync_operations,
    )


def test_external_upsert_delete_and_revive_are_idempotent(
    db: Session,
    lifecycle_spies: SimpleNamespace,
) -> None:
    created = _upsert(
        db,
        external_id="lifecycle",
        payload=b"version-one",
        grants=[ExternalFileGrant("user", MEMBER_ID)],
        source_version="1",
    )
    db.commit()
    first_key = created.file.storage_key
    assert lifecycle_spies.stored[first_key] == b"version-one"
    assert lifecycle_spies.removed_storage_keys == []

    unchanged = _upsert(
        db,
        external_id="lifecycle",
        payload=b"version-one",
        grants=[ExternalFileGrant("user", MEMBER_ID)],
        source_version="1",
    )
    assert not unchanged.created and not unchanged.changed
    assert lifecycle_spies.sync_operations == [RagSyncOperation.UPSERT]

    replaced = _upsert(
        db,
        external_id="lifecycle",
        payload=b"version-two",
        grants=[ExternalFileGrant("user", MEMBER_ID)],
        source_version="2",
    )
    db.commit()
    assert replaced.file.id == created.file.id
    assert replaced.obsolete_storage_keys == (first_key,)
    assert replaced.file.storage_key != first_key
    assert lifecycle_spies.stored[replaced.file.storage_key] == b"version-two"
    assert replaced.file.storage_key not in lifecycle_spies.removed_storage_keys

    deleted_storage_key = replaced.file.storage_key
    deleted = external_lifecycle.delete_external_file(
        db,
        actor=db.get(User, PLATFORM_ADMIN_ID),
        corpus_id=CORPUS_ID,
        file_id=replaced.file.id,
    )
    db.commit()
    assert deleted.changed
    assert deleted.obsolete_storage_keys == (deleted_storage_key,)
    cleanup_jobs = list(
        db.scalars(
            select(FileManagerStorageCleanupJob).order_by(
                FileManagerStorageCleanupJob.created_at.asc()
            )
        )
    )
    assert [job.storage_key for job in cleanup_jobs] == [
        first_key,
        deleted_storage_key,
    ]
    assert not can_read_file(_policy(db, MEMBER_ID), replaced.file.id)
    assert not external_lifecycle.delete_external_file(
        db,
        actor=db.get(User, PLATFORM_ADMIN_ID),
        corpus_id=CORPUS_ID,
        external_id="lifecycle",
    ).changed

    revived = _upsert(
        db,
        external_id="lifecycle",
        payload=b"version-two",
        grants=[ExternalFileGrant("user", MEMBER_ID)],
        source_version="2",
    )
    db.commit()
    assert revived.file.id == created.file.id
    assert revived.changed and not revived.created
    assert revived.file.deleted_at is None
    assert revived.file.storage_key != deleted_storage_key
    assert all(
        job.storage_key != revived.file.storage_key
        for job in db.scalars(select(FileManagerStorageCleanupJob))
    )
    assert can_read_file(_policy(db, MEMBER_ID), revived.file.id)
    assert lifecycle_spies.sync_operations == [
        RagSyncOperation.UPSERT,
        RagSyncOperation.UPSERT,
        RagSyncOperation.DELETE,
        RagSyncOperation.UPSERT,
    ]


def test_external_upsert_removes_object_when_caller_rolls_back(
    db: Session,
    lifecycle_spies: SimpleNamespace,
) -> None:
    result = _upsert(
        db,
        external_id="outer-rollback",
        payload=b"must-not-survive",
        grants=[ExternalFileGrant("company")],
    )
    storage_key = result.file.storage_key
    assert lifecycle_spies.stored[storage_key] == b"must-not-survive"

    db.rollback()

    assert lifecycle_spies.stored == {}
    assert lifecycle_spies.removed_storage_keys == [storage_key]
    assert db.scalar(select(func.count()).select_from(FileManagerFile)) == 0


def test_external_upsert_preserves_object_after_unknown_outer_commit_failure(
    db: Session,
    lifecycle_spies: SimpleNamespace,
) -> None:
    result = _upsert(
        db,
        external_id="commit-failure",
        payload=b"must-be-compensated",
        grants=[ExternalFileGrant("company")],
    )
    storage_key = result.file.storage_key

    def fail_commit(_connection) -> None:
        raise RuntimeError("database commit failed")

    event.listen(db.get_bind(), "commit", fail_commit, once=True)
    with pytest.raises(RuntimeError, match="database commit failed"):
        try:
            db.commit()
        except Exception:
            # SQLAlchemy requires callers to roll back a failed commit before
            # the Session can be reused. This does not prove COMMIT was rejected.
            db.rollback()
            raise

    assert lifecycle_spies.stored[storage_key] == b"must-be-compensated"
    assert lifecycle_spies.removed_storage_keys == []
    assert db.scalar(select(func.count()).select_from(FileManagerFile)) == 0


def _upsert(
    db: Session,
    *,
    external_id: str,
    payload: bytes,
    grants: list[ExternalFileGrant],
    source_version: str | None = None,
    raw_metadata: dict[str, object] | None = None,
    title: str | None = None,
    source_id: str | None = None,
    expected_file_id: str | None = None,
):
    return external_lifecycle.upsert_external_file(
        db,
        actor=db.get(User, PLATFORM_ADMIN_ID),
        corpus_id=CORPUS_ID,
        external_id=external_id,
        source_kind="external_document",
        source_id=source_id or external_id,
        expected_file_id=expected_file_id,
        filename=f"{external_id}.txt",
        content_type="text/plain",
        content=BytesIO(payload),
        size_bytes=len(payload),
        grants=grants,
        source_version=source_version,
        title=title or f"Title {external_id}",
        author="External Author",
        department="Engineering",
        document_type="technical",
        raw_metadata=raw_metadata,
    )


def _policy(db: Session, user_id: str) -> SourceAclPolicy:
    return SourceAclPolicy.for_user(db, user=db.get(User, user_id))


def _user(user_id: str) -> User:
    return User(
        id=user_id,
        login_id=user_id,
        email=f"{user_id}@example.test",
        full_name=user_id,
        password_hash="unused",
        status="active",
        login_blocked=False,
    )
