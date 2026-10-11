"""Fixed caller-owned Files descriptor setup and same-UUID observation.

The caller retains the spec before starting and owns COMMIT. No lookup allocates
an ID, grants Source access or establishes whether an unacknowledged COMMIT failed.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.projection_outbox import require_current_transaction
from miy_api.domains.official_apps.writer import WriterIdentity, _admin, snapshot
from miy_api.domains.official_apps.writer_models import RuntimeOwnership
from miy_api.domains.official_apps.writer_roles import _lock
from miy_api.domains.retrieval.models import RetrievalPartition
from miy_api.domains.retrieval.partitioning import RetrievalPartitionConflict, RetrievalPartitionId


def _partition_uuid(value: str) -> str:
    if type(value) is not str:
        raise RetrievalPartitionConflict("prepared_file_partition_identity_invalid")
    try:
        return str(UUID(value))
    except ValueError:
        raise RetrievalPartitionConflict("prepared_file_partition_identity_invalid") from None


def _metadata_version(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise RetrievalPartitionConflict("prepared_file_partition_version_invalid")
    return value


@dataclass(frozen=True, slots=True)
class PreparedFilePartitionSpec:
    partition_id: str
    kind: Literal["company_default", "company_managed"]
    metadata_version: int

    def __post_init__(self):
        object.__setattr__(self, "partition_id", _partition_uuid(self.partition_id))
        if type(self.kind) is not str or self.kind not in {"company_default", "company_managed"}:
            raise RetrievalPartitionConflict("prepared_file_partition_kind_invalid")
        _metadata_version(self.metadata_version)


@dataclass(frozen=True, slots=True)
class PreparedFilePartitionReceipt:
    spec: PreparedFilePartitionSpec
    created: bool = False
    provisional: bool = True


def _start(db: Session, *, mutation: bool) -> None:
    # Refuse before SQL/autoflush; a rejected stage never discards caller work.
    if db.new or db.dirty or db.deleted or db.in_nested_transaction():
        raise RetrievalPartitionConflict("prepared_file_partition_clean_outer_required")
    require_current_transaction(db)
    with db.no_autoflush:
        allowed = db.scalar(
            text(
                "SELECT has_table_privilege(session_user,'public.retrieval_partitions','SELECT')"
                + (
                    " AND has_table_privilege(session_user,'public.retrieval_partitions','INSERT')"
                    " AND has_table_privilege(session_user,'public.retrieval_partitions','UPDATE')"
                    " AND has_table_privilege(session_user,'public.audit_logs','INSERT')"
                    if mutation
                    else ""
                )
            ),
        )
    if not allowed:
        raise RetrievalPartitionConflict("prepared_file_partition_core_authority_required")


def _observe_ownership(
    db: Session, actor: AuthContext, expected: WriterIdentity, expected_state: str
) -> None:
    if expected_state not in {"active", "draining"}:
        raise RetrievalPartitionConflict("prepared_file_partition_ownership_state_invalid")
    _admin(db, actor)
    record = db.get(RuntimeOwnership, expected.scope, populate_existing=True)
    if record is None or snapshot(record) != {
        "scope": expected.scope,
        "owner": expected.owner,
        "generation": expected.generation,
        "artifact": expected.artifact,
        "state": expected_state,
    }:
        raise RetrievalPartitionConflict("prepared_file_partition_ownership_changed")
    _admin(db, actor)


def _descriptor(db: Session, partition_id: str, *, lock: bool = False):
    statement = select(
        RetrievalPartition.id,
        RetrievalPartition.source_namespace,
        RetrievalPartition.candidate_scope_kind,
        RetrievalPartition.candidate_user_id,
        RetrievalPartition.state,
        RetrievalPartition.is_default_ingest,
        RetrievalPartition.metadata_version,
    ).where(RetrievalPartition.id == partition_id)
    if lock:
        statement = statement.with_for_update(read=True)
    return db.execute(statement).one_or_none()


def _require_exact_descriptor(row, spec: PreparedFilePartitionSpec) -> None:
    if tuple(row) != (
        spec.partition_id,
        "files",
        "company",
        None,
        "active",
        spec.kind == "company_default",
        spec.metadata_version,
    ):
        raise RetrievalPartitionConflict("prepared_file_partition_descriptor_changed")


def lookup_current_file_default(
    db: Session,
    actor: AuthContext,
    *,
    expected: WriterIdentity,
    expected_state: str,
) -> PreparedFilePartitionReceipt | None:
    """Read the actual current default identity before retaining a setup spec."""
    _start(db, mutation=False)
    with db.no_autoflush:
        _observe_ownership(db, actor, expected, expected_state)
        row = db.execute(
            select(
                RetrievalPartition.id, RetrievalPartition.state, RetrievalPartition.metadata_version
            ).where(
                RetrievalPartition.source_namespace == "files",
                RetrievalPartition.candidate_scope_kind == "company",
                RetrievalPartition.candidate_user_id.is_(None),
                RetrievalPartition.is_default_ingest.is_(True),
                RetrievalPartition.state != "retired",
            )
        ).one_or_none()
        _admin(db, actor)
        if row is None:
            return None
        if row.state != "active":
            raise RetrievalPartitionConflict("prepared_file_partition_descriptor_changed")
        return PreparedFilePartitionReceipt(
            PreparedFilePartitionSpec(row.id, "company_default", row.metadata_version)
        )


def prepare_file_partition_descriptor(
    db: Session,
    actor: AuthContext,
    *,
    spec: PreparedFilePartitionSpec,
    expected: WriterIdentity,
    expected_state: str,
) -> PreparedFilePartitionReceipt:
    """Stage one exact descriptor and audit; never commit or choose another UUID."""
    if not isinstance(spec, PreparedFilePartitionSpec):
        raise RetrievalPartitionConflict("prepared_file_partition_spec_required")
    if expected_state not in {"active", "draining"}:
        raise RetrievalPartitionConflict("prepared_file_partition_ownership_state_invalid")
    _start(db, mutation=True)
    with db.no_autoflush:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='15s'"))
        current = _lock(db, actor, expected, expected_state)
        row = _descriptor(db, spec.partition_id, lock=True)
        if row is not None:
            _require_exact_descriptor(row, spec)
            _admin(db, actor)
            return PreparedFilePartitionReceipt(spec)
        partition = RetrievalPartition(
            id=spec.partition_id,
            source_namespace="files",
            candidate_scope_kind="company",
            candidate_user_id=None,
            state="active",
            metadata_version=spec.metadata_version,
            is_default_ingest=spec.kind == "company_default",
        )
        db.add(partition)
        try:
            db.flush()
        except IntegrityError:
            # The caller rolls back its rejected transaction. Never retry the
            # allocator or adopt a conflicting default under a different ID.
            raise RetrievalPartitionConflict("prepared_file_partition_identity_conflict") from None
        _admin(db, actor)
        record_audit_log(
            db,
            action="retrieval.file_partition.prepare",
            entity_kind="retrieval_partition",
            entity_id=spec.partition_id,
            actor_user_id=current.user.id,
            summary="Prepared Files company partition",
            payload={"kind": spec.kind, "metadata_version": spec.metadata_version},
        )
        db.flush()
        _admin(db, actor)
        return PreparedFilePartitionReceipt(spec, created=True)


def lookup_prepared_file_partition(
    db: Session,
    actor: AuthContext,
    *,
    spec: PreparedFilePartitionSpec,
    expected: WriterIdentity,
    expected_state: str,
) -> PreparedFilePartitionReceipt | None:
    """Observe only the retained UUID; missing never proves COMMIT rejection."""
    if not isinstance(spec, PreparedFilePartitionSpec):
        raise RetrievalPartitionConflict("prepared_file_partition_spec_required")
    _start(db, mutation=False)
    with db.no_autoflush:
        _observe_ownership(db, actor, expected, expected_state)
        row = _descriptor(db, spec.partition_id)
        _admin(db, actor)
        if row is None:
            return None
        _require_exact_descriptor(row, spec)
        return PreparedFilePartitionReceipt(spec)


def require_prepared_file_source_partition(
    db: Session, *, partition_id: str, managed_metadata_version: int | None
) -> RetrievalPartitionId:
    """Source gets only UUID-only admission; the fixed SQL capability owns SHARE."""
    identifier = _partition_uuid(partition_id)
    if managed_metadata_version is not None:
        _metadata_version(managed_metadata_version)
    require_current_transaction(db)
    with db.no_autoflush:
        admitted = db.scalar(
            text("SELECT public.miy_read_file_source_partition(CAST(:id AS uuid),:version)"),
            {"id": identifier, "version": managed_metadata_version},
        )
    if admitted is None or str(admitted) != identifier:
        raise RetrievalPartitionConflict("prepared_file_partition_source_unavailable")
    return RetrievalPartitionId(identifier)
