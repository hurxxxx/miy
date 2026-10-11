"""Core-prepared company defaults and narrow Source UUID admission.

Source never reads/locks Core tables directly or allocates a partition. The fixed
SQL capability holds admission/default SHARE locks in this caller transaction.
"""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.official_apps.projection_contracts import ProjectionOutboxError
from miy_api.domains.official_apps.projection_delivery import is_prepared_source_projection
from miy_api.domains.official_apps.projection_outbox import require_current_transaction
from miy_api.domains.official_apps.writer import WriterIdentity, _admin
from miy_api.domains.official_apps.writer_roles import _lock
from miy_api.domains.retrieval.models import RetrievalPartition, RetrievalPartitionState
from miy_api.domains.retrieval.partitioning import (
    RetrievalPartitionConflict,
    RetrievalPartitionId,
    assign_default_partition,
    ensure_default_partition,
)

COMPANY_PROJECTION_NAMESPACES = ("docs", "meeting", "pms")


@dataclass(frozen=True)
class PreparedCompanyPartition:
    source_namespace: str
    partition_id: RetrievalPartitionId


def require_prepared_company_partition(
    db: Session, *, source_namespace: str, bound_partition_id: str | None = None
) -> RetrievalPartitionId:
    require_current_transaction(db)
    if (
        not is_prepared_source_projection(db)
        or source_namespace not in COMPANY_PROJECTION_NAMESPACES
    ):
        raise ProjectionOutboxError("projection_partition_composition_required")
    with db.no_autoflush:
        identifier = db.scalar(
            text(
                "SELECT public.miy_read_official_company_partition(:namespace, CAST(:bound AS uuid))"
            ),
            {"namespace": source_namespace, "bound": bound_partition_id},
        )
    if identifier is None:
        raise RetrievalPartitionConflict("prepared company projection partition unavailable")
    return RetrievalPartitionId(str(identifier))


def assign_company_projection_partition(
    db: Session, *, target, source_namespace: str
) -> RetrievalPartitionId:
    if source_namespace not in COMPANY_PROJECTION_NAMESPACES:
        raise ProjectionOutboxError("projection_partition_namespace_unavailable")
    if not is_prepared_source_projection(db):
        return assign_default_partition(
            db,
            target=target,
            source_namespace=source_namespace,
            candidate_scope_kind="company",
        )
    identifier = require_prepared_company_partition(
        db,
        source_namespace=source_namespace,
        bound_partition_id=getattr(target, "retrieval_partition_id", None),
    )
    if target.retrieval_partition_id != identifier:
        target.retrieval_partition_id = identifier
        db.add(target)
    return identifier


def prepare_company_projection_defaults(
    db: Session,
    actor: AuthContext,
    *,
    expected: WriterIdentity,
    expected_state: str,
) -> tuple[PreparedCompanyPartition, ...]:
    """Internal Core setup; exact authority and outer COMMIT belong to the caller."""
    require_current_transaction(db)
    with db.no_autoflush:
        if not db.scalar(
            text(
                "SELECT has_table_privilege(session_user,'public.retrieval_partitions','SELECT') "
                "AND has_table_privilege(session_user,'public.retrieval_partitions','INSERT') "
                "AND has_table_privilege(session_user,'public.retrieval_partitions','UPDATE')"
            )
        ):
            raise ProjectionOutboxError("projection_core_authority_required")
        _lock(db, actor, expected, expected_state)
        prepared = []
        for namespace in COMPANY_PROJECTION_NAMESPACES:
            partition = ensure_default_partition(
                db, source_namespace=namespace, candidate_scope_kind="company"
            )
            partition = db.scalar(
                select(RetrievalPartition)
                .where(RetrievalPartition.id == partition.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if (
                partition is None
                or partition.source_namespace != namespace
                or partition.candidate_scope_kind != "company"
                or partition.candidate_user_id is not None
                or not partition.is_default_ingest
                or partition.state != RetrievalPartitionState.ACTIVE.value
            ):
                raise RetrievalPartitionConflict("invalid prepared company projection partition")
            prepared.append(PreparedCompanyPartition(namespace, RetrievalPartitionId(partition.id)))
        _admin(db, actor)
    return tuple(prepared)


def lookup_company_projection_defaults(
    db: Session, *, prepared: tuple[PreparedCompanyPartition, ...]
) -> tuple[PreparedCompanyPartition, ...] | None:
    """Observe saved setup UUIDs after unknown COMMIT, without allocating anything.

    Missing rows are only unobserved. Changed/retired identities are refused;
    calling the allocator again is not a reconciliation procedure.
    """
    require_current_transaction(db)
    if tuple(item.source_namespace for item in prepared) != COMPANY_PROJECTION_NAMESPACES:
        raise ProjectionOutboxError("projection_default_reconciliation_identity_invalid")
    with db.no_autoflush:
        if not db.scalar(
            text("SELECT has_table_privilege(session_user,'public.retrieval_partitions','SELECT')")
        ):
            raise ProjectionOutboxError("projection_core_authority_required")
        for item in prepared:
            partition = db.get(RetrievalPartition, item.partition_id, populate_existing=True)
            if partition is None:
                return None
            if (
                partition.source_namespace != item.source_namespace
                or partition.candidate_scope_kind != "company"
                or partition.candidate_user_id is not None
                or not partition.is_default_ingest
                or partition.state != RetrievalPartitionState.ACTIVE.value
            ):
                raise RetrievalPartitionConflict("prepared company projection partition changed")
    return prepared
