from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.groups.models import Group
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
)
from miy_api.domains.retrieval.partition_adapter_registry import (
    RetrievalProjectionBinding,
    register_retrieval_partition_adapter,
    reset_retrieval_partition_adapters,
)
from miy_api.domains.retrieval.partitioning import (
    RetrievalPartitionConflict,
    create_managed_partition,
    ensure_default_partition,
    resolve_read_scope,
    transition_partition_candidate_scope,
)


@dataclass(frozen=True)
class _FakePartitionAdapter:
    adapter_id: str
    source_namespace: str
    resource_types: tuple[str, ...]
    allowed_candidate_scopes: tuple[str, ...] = ("company",)
    allowed_transitions: tuple[str, ...] = ()
    transition_mode: str = "generic"
    partition_id: str = "partition-a"

    def bind_resource_partition(
        self,
        db: Session,
        *,
        resource_type: str,
        resource_id: str,
    ) -> RetrievalProjectionBinding:
        del db
        return RetrievalProjectionBinding(
            resource_type=resource_type,
            resource_id=resource_id,
            partition_id=self.partition_id,
        )


@pytest.fixture
def db() -> Session:
    reset_retrieval_partition_adapters()
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(
        engine,
        tables=[
            Group.__table__,
            User.__table__,
            RetrievalPartition.__table__,
        ],
    )
    with Session(engine) as session:
        session.add_all(
            [
                User(
                    id="user-a",
                    login_id="user-a",
                    email="user-a@example.com",
                    full_name="User A",
                    password_hash="hash",
                ),
                User(
                    id="user-b",
                    login_id="user-b",
                    email="user-b@example.com",
                    full_name="User B",
                    password_hash="hash",
                ),
            ]
        )
        session.commit()
        yield session
    reset_retrieval_partition_adapters()


def test_read_scope_unions_company_managed_and_personal_partitions(db: Session) -> None:
    company = ensure_default_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="company",
    )
    managed_a = create_managed_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="company",
    )
    managed_b = create_managed_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="company",
    )
    personal_a = ensure_default_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="personal",
        user_id="user-a",
    )
    personal_b = ensure_default_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="personal",
        user_id="user-b",
    )

    scope = resolve_read_scope(
        db,
        source_namespaces=["files", "docs"],
        user_id="user-a",
    )

    assert set(scope.for_source("files")) == {
        company.id,
        managed_a.id,
        managed_b.id,
        personal_a.id,
    }
    assert personal_b.id not in scope.for_source("files")
    assert scope.for_source("docs") == ()
    assert not scope.is_empty


def test_files_source_owned_adapter_rejects_generic_candidate_scope_transition(
    db: Session,
) -> None:
    from miy_api.domains.files.source_access import FileManagerSourceAccessAdapter

    adapter = FileManagerSourceAccessAdapter()
    partition = create_managed_partition(
        db,
        source_namespace="files",
        candidate_scope_kind="company",
    )
    register_retrieval_partition_adapter(adapter)

    with pytest.raises(RetrievalPartitionConflict, match="owned by its source service"):
        transition_partition_candidate_scope(
            db,
            partition_id=partition.id,
            adapter_id=adapter.adapter_id,
            transition_operation="corpus_scope_change",
            expected_metadata_version=1,
            candidate_scope_kind="company",
        )

    assert partition.candidate_scope_kind == "company"
    assert partition.candidate_user_id is None
    assert partition.metadata_version == 1
