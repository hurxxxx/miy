"""Strict prepared Files output reads; no extraction or effect authority.

The latest genuine Source tip must be accepted as this exact current Core event.
One bounded scalar snapshot feeds both existing builders. Final reads are still
observations: the effect composition owns Source-stream then Core-head locking,
provider admission, bounded effects and the durable progress COMMIT.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import User
from miy_api.domains.files.artifact_contract import (
    FileArtifactChecksumMismatch,
    FileArtifactInvalid,
    FileArtifactNotReady,
    is_file_artifact_checksum,
    validate_file_extraction_artifact,
)
from miy_api.domains.files.core_projection import (
    is_prepared_core_file_projection,
    require_prepared_core_file_projection_event,
)
from miy_api.domains.files.current_content import file_extraction_result_marker
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.rag_projection import build_file_rag_projection
from miy_api.domains.files.search_projection import build_file_search_document
from miy_api.domains.official_apps.projection_models import (
    OfficialProjectionOutbox,
    OfficialProjectionReceipt,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionOutboxError
from miy_api.domains.official_apps.projection_outbox import require_current_transaction
from miy_api.domains.rag.contracts import RagProjection
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef

_FILE_FIELDS = (
    "id",
    "owner_id",
    "filename",
    "folder_id",
    "corpus_id",
    "content_type",
    "size_bytes",
    "visibility",
    "updated_at",
    "retrieval_partition_id",
    "deleted_at",
    "extraction_status",
    "extraction_content_checksum",
    "extraction_text",
    "extraction_blocks",
    "extraction_metadata",
    "extracted_at",
)
_IDENTITY_FIELDS = (
    "id",
    "corpus_id",
    "retrieval_partition_id",
    "deleted_at",
    "extraction_status",
    "extraction_content_checksum",
    "extracted_at",
)
_CORPUS_FIELDS = ("id", "access_scope_kind", "retrieval_partition_id")
_METADATA_FIELDS = (
    "file_id",
    "corpus_id",
    "source_kind",
    "title",
    "author",
    "authored_at",
    "department",
    "document_type",
    "source_updated_at",
    "content_checksum",
)
_METADATA_IDENTITY_FIELDS = ("file_id", "corpus_id", "content_checksum")


@dataclass(frozen=True, slots=True)
class FileMaterializationSourceWitness:
    source_event_id: str
    source_revision: int
    payload_digest: str
    projection_event: ProjectionEventRef


@dataclass(frozen=True, slots=True)
class _SourceIdentity:
    file_id: str
    corpus_id: str | None
    retrieval_partition_id: str | None
    deleted_at: datetime | None
    extraction_status: str
    content_checksum: str | None
    extracted_at: str | None
    corpus_binding: tuple[Any, ...]
    metadata_binding: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class FileMaterializationProjection:
    """Retained local envelope, not a new durable output or compute receipt."""

    witness: FileMaterializationSourceWitness
    source_identity: _SourceIdentity | None
    keyword_document: dict[str, Any] | None
    rag_projection: RagProjection | None


@dataclass(frozen=True, slots=True)
class _OwnerSnapshot:
    id: str
    display_name: str | None
    full_name: str | None


@dataclass(frozen=True, slots=True)
class _CorpusSnapshot:
    id: str
    access_scope_kind: str
    retrieval_partition_id: str


@dataclass(frozen=True, slots=True)
class _MetadataSnapshot:
    file_id: str
    corpus_id: str
    source_kind: str
    title: str | None
    author: str | None
    authored_at: datetime | None
    department: str | None
    document_type: str | None
    source_updated_at: datetime | None
    content_checksum: str


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    id: str
    owner_id: str
    filename: str
    folder_id: str | None
    corpus_id: str | None
    content_type: str
    size_bytes: int
    visibility: str
    updated_at: datetime
    retrieval_partition_id: str | None
    deleted_at: datetime | None
    extraction_status: str
    extraction_content_checksum: str | None
    extraction_text: str | None
    extraction_blocks: list[dict[str, Any]]
    extraction_metadata: dict[str, Any]
    extracted_at: datetime | None
    owner: _OwnerSnapshot | None
    corpus: _CorpusSnapshot | None
    source_metadata: _MetadataSnapshot | None


def _require_core_identity(db: Session) -> None:
    """Actual Core caller and transaction-local canonical lookup namespace."""
    with db.no_autoflush:
        try:
            require_current_transaction(db)
        except ProjectionOutboxError:
            raise FileArtifactInvalid("materialization_requires_read_committed") from None
        except SQLAlchemyError:
            raise FileArtifactInvalid("materialization_core_identity_unavailable") from None
        try:
            # PostgreSQL otherwise searches pg_temp ahead of unqualified model
            # tables. Pin it explicitly last before identity/content reads;
            # this transaction-local setting grants no role or data authority.
            db.execute(
                text(
                    "SELECT pg_catalog.set_config('search_path', 'pg_catalog, public, pg_temp', true)"
                )
            )
        except SQLAlchemyError:
            raise FileArtifactInvalid("materialization_namespace_unavailable") from None
        try:
            row = db.execute(
                text("""
                SELECT r.rolcanlogin,r.rolsuper,r.rolinherit,r.rolcreatedb,
                    r.rolcreaterole,r.rolreplication,r.rolbypassrls,
                    EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m
                        WHERE m.member=r.oid OR m.roleid=r.oid),
                    EXISTS(SELECT 1 FROM public.official_writer_principals p
                        WHERE p.role_oid=r.oid::bigint OR p.role_name=session_user)
                FROM pg_catalog.pg_roles r WHERE r.rolname=session_user
            """)
            ).one_or_none()
        except SQLAlchemyError:
            raise FileArtifactInvalid("materialization_core_identity_unavailable") from None
    if row is None or tuple(row) != (True, False, False, False, False, False, False, False, False):
        raise FileArtifactInvalid("materialization_core_identity_forbidden")


def require_file_materialization_identity(db: Session) -> None:
    """Admit Core/transaction/namespace before discovery or historical reads.

    No prepared current-event context is needed for empty reconciliation or
    immutable history. This grants neither Source nor effect authority.
    """
    _require_core_identity(db)


def require_current_file_materialization_source(
    db: Session, *, projection_event: ProjectionEventRef
) -> FileMaterializationSourceWitness:
    """Read exact current Core and latest accepted Source correlation, without locks."""
    if not is_prepared_core_file_projection(db):
        raise FileArtifactInvalid("file_projection_context_required")
    _require_core_identity(db)
    event = require_prepared_core_file_projection_event(db, projection_event=projection_event)
    source_fields = (
        "event_id",
        "resource_type",
        "resource_id",
        "source_revision",
        "payload_digest",
    )
    receipt_fields = (*source_fields, "status", "core_event_sequence")
    with db.no_autoflush:
        row = db.execute(
            select(
                *(getattr(OfficialProjectionOutbox, field) for field in source_fields),
                *(getattr(OfficialProjectionReceipt, field) for field in receipt_fields),
            )
            .outerjoin(
                OfficialProjectionReceipt,
                OfficialProjectionReceipt.event_id == OfficialProjectionOutbox.event_id,
            )
            .where(
                OfficialProjectionOutbox.resource_type == event.resource_type,
                OfficialProjectionOutbox.resource_id == event.resource_id,
            )
            .order_by(OfficialProjectionOutbox.source_revision.desc())
            .limit(1)
        ).one_or_none()
    if row is None:
        raise FileArtifactNotReady("source_tip_missing")
    source, receipt = tuple(row[:5]), tuple(row[5:])
    try:
        valid_id = type(source[0]) is str and str(UUID(source[0])) == source[0]
    except (ValueError, TypeError, AttributeError):
        valid_id = False
    if (
        not valid_id
        or source[1:3] != (event.resource_type, event.resource_id)
        or type(source[3]) is not int
        or source[3] < 1
        or not is_file_artifact_checksum(source[4])
    ):
        raise FileArtifactInvalid("source_tip_invalid")
    if receipt[0] is None:
        raise FileArtifactNotReady("source_tip_unaccepted")
    if receipt[:5] != source:
        raise FileArtifactInvalid("source_receipt_mismatch")
    if receipt[5] not in {"accepted", "superseded"}:
        raise FileArtifactInvalid("source_receipt_invalid")
    if receipt[5] != "accepted" or receipt[6] != event.event_sequence:
        raise FileArtifactNotReady("source_tip_not_accepted_for_event")
    return FileMaterializationSourceWitness(source[0], source[3], source[4], event)


def _source_row(db: Session, file_id: str, *, artifact: bool):
    file_fields = _FILE_FIELDS if artifact else _IDENTITY_FIELDS
    metadata_fields = _METADATA_FIELDS if artifact else _METADATA_IDENTITY_FIELDS
    columns = [getattr(FileManagerFile, field).label("file_" + field) for field in file_fields]
    if artifact:
        columns.extend(
            getattr(User, field).label("owner_" + field)
            for field in ("id", "display_name", "full_name")
        )
    columns.extend(
        getattr(FileManagerCorpus, field).label("corpus_" + field) for field in _CORPUS_FIELDS
    )
    columns.extend(
        getattr(FileManagerFileSourceMetadata, field).label("metadata_" + field)
        for field in metadata_fields
    )
    statement = select(*columns).select_from(FileManagerFile)
    if artifact:
        statement = statement.outerjoin(User, User.id == FileManagerFile.owner_id)
    statement = (
        statement.outerjoin(FileManagerCorpus, FileManagerCorpus.id == FileManagerFile.corpus_id)
        .outerjoin(
            FileManagerFileSourceMetadata,
            FileManagerFileSourceMetadata.file_id == FileManagerFile.id,
        )
        .where(FileManagerFile.id == file_id)
    )
    with db.no_autoflush:
        return db.execute(statement).mappings().one_or_none()


def _identity(row) -> _SourceIdentity | None:
    if row is None:
        return None
    return _SourceIdentity(
        row["file_id"],
        row["file_corpus_id"],
        row["file_retrieval_partition_id"],
        row["file_deleted_at"],
        row["file_extraction_status"],
        row["file_extraction_content_checksum"],
        file_extraction_result_marker(row["file_extracted_at"]),
        tuple(row["corpus_" + field] for field in _CORPUS_FIELDS),
        tuple(row["metadata_" + field] for field in _METADATA_IDENTITY_FIELDS),
    )


def _snapshot(row) -> _FileSnapshot:
    owner = (
        _OwnerSnapshot(*(row["owner_" + field] for field in ("id", "display_name", "full_name")))
        if row["owner_id"] is not None
        else None
    )
    corpus = (
        _CorpusSnapshot(*(row["corpus_" + field] for field in _CORPUS_FIELDS))
        if row["corpus_id"] is not None
        else None
    )
    metadata = (
        _MetadataSnapshot(*(row["metadata_" + field] for field in _METADATA_FIELDS))
        if row["metadata_file_id"] is not None
        else None
    )
    return _FileSnapshot(*(row["file_" + field] for field in _FILE_FIELDS), owner, corpus, metadata)


def _validate_binding(identity: _SourceIdentity, event: ProjectionEventRef) -> None:
    if identity.retrieval_partition_id != event.retrieval_partition_id:
        raise FileArtifactInvalid("source_partition_mismatch")
    if identity.corpus_id is not None and identity.corpus_binding != (
        identity.corpus_id,
        "company",
        event.retrieval_partition_id,
    ):
        raise FileArtifactInvalid("source_corpus_binding_mismatch")
    metadata_file_id, metadata_corpus_id, _checksum = identity.metadata_binding
    if metadata_file_id is not None and (
        metadata_file_id != identity.file_id
        or identity.corpus_id is None
        or metadata_corpus_id != identity.corpus_id
    ):
        raise FileArtifactInvalid("external_corpus_binding_mismatch")


def require_unchanged_file_materialization(
    db: Session, *, materialization: FileMaterializationProjection
) -> FileMaterializationSourceWitness:
    """Recheck after read/lock waits; the caller owns effect locks and COMMIT."""
    if not isinstance(materialization, FileMaterializationProjection):
        raise FileArtifactInvalid("materialization_required")
    witness = require_current_file_materialization_source(
        db, projection_event=materialization.witness.projection_event
    )
    if witness != materialization.witness:
        raise FileArtifactNotReady("source_witness_changed")
    identity = _identity(_source_row(db, witness.projection_event.resource_id, artifact=False))
    if identity != materialization.source_identity:
        raise FileArtifactNotReady("source_result_changed")
    return witness


def load_prepared_file_materialization(
    db: Session, *, projection_event: ProjectionEventRef
) -> FileMaterializationProjection:
    """Build both derived projections from one strictly admitted bounded snapshot.

    Active missing/deleted Source is a hold, never a tombstone. Only a genuine
    accepted deleted event with current missing/deleted/unsupported Source may
    return a deletion pair. No parser, storage, provider or transaction mutation.
    """
    witness = require_current_file_materialization_source(db, projection_event=projection_event)
    event = witness.projection_event
    row = _source_row(db, event.resource_id, artifact=True)
    identity = _identity(row)
    if event.desired_state == "deleted":
        if identity is not None:
            _validate_binding(identity, event)
            if identity.deleted_at is None and identity.extraction_status != "unsupported":
                raise FileArtifactNotReady("deleted_event_source_inconsistent")
        result = FileMaterializationProjection(witness, identity, None, None)
    else:
        if identity is None or identity.deleted_at is not None:
            raise FileArtifactNotReady("active_event_source_missing")
        _validate_binding(identity, event)
        if identity.extraction_status in {"pending", "failed", "unsupported"}:
            raise FileArtifactNotReady("source_" + identity.extraction_status)
        if identity.extraction_status != "ready":
            raise FileArtifactInvalid("source_status_invalid")
        if event.content_checksum is None:
            raise FileArtifactNotReady("event_checksum_pending")
        if identity.extracted_at is None:
            raise FileArtifactNotReady("source_result_stamp_missing")
        file = _snapshot(row)
        artifact = validate_file_extraction_artifact(
            file_id=file.id,
            content_checksum=file.extraction_content_checksum,
            text=file.extraction_text,
            blocks=file.extraction_blocks,
            metadata=file.extraction_metadata,
        )
        if artifact.content_checksum != event.content_checksum:
            raise FileArtifactChecksumMismatch("accepted_event_checksum_mismatch")
        if file.source_metadata is not None and (
            file.source_metadata.content_checksum != artifact.content_checksum
        ):
            raise FileArtifactChecksumMismatch("external_input_checksum_mismatch")
        keyword = build_file_search_document(file=file)
        keyword.update(
            retrieval_partition_id=event.retrieval_partition_id,
            projection_version=event.projection_version,
        )
        rag = build_file_rag_projection(file=file, artifact=artifact).model_copy(
            update={
                "retrieval_partition_id": event.retrieval_partition_id,
                "projection_version": event.projection_version,
            }
        )
        result = FileMaterializationProjection(witness, identity, keyword, rag)
    require_unchanged_file_materialization(db, materialization=result)
    return result


__all__ = [
    "FileMaterializationProjection",
    "FileMaterializationSourceWitness",
    "load_prepared_file_materialization",
    "require_current_file_materialization_source",
    "require_file_materialization_identity",
    "require_unchanged_file_materialization",
]
