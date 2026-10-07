"""Internal Core reads of canonical Source artifacts, without extraction authority.

The typed context selects delivery only. PostgreSQL privileges, current app/ACL
and the worker's mutation fence remain independent authority boundaries. Old
artifacts have no captured storage-key provenance; checksum consistency here is
not current-input attestation or an indexing/readiness claim.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, raiseload, undefer

from miy_api.domains.auth.models import User
from miy_api.domains.files.artifact_contract import (
    FileExtractionArtifact as FileExtractionArtifact,
    FileArtifactControlError as FileArtifactControlError,
    FileArtifactNotReady,
    FileArtifactInvalid,
    FileArtifactChecksumMismatch,
    MAX_FILES_RAG_EXTRACTED_CHARS as MAX_FILES_RAG_EXTRACTED_CHARS,
    MAX_FILE_ARTIFACT_BYTES as MAX_FILE_ARTIFACT_BYTES,
    MAX_FILE_ARTIFACT_BLOCKS as MAX_FILE_ARTIFACT_BLOCKS,
    MAX_FILE_ARTIFACT_ROWS as MAX_FILE_ARTIFACT_ROWS,
    MAX_FILE_ARTIFACT_CELLS as MAX_FILE_ARTIFACT_CELLS,
    MAX_FILE_ARTIFACT_METADATA_BYTES as MAX_FILE_ARTIFACT_METADATA_BYTES,
    MAX_FILE_ARTIFACT_METADATA_DEPTH as MAX_FILE_ARTIFACT_METADATA_DEPTH,
    MAX_FILE_ARTIFACT_METADATA_NODES as MAX_FILE_ARTIFACT_METADATA_NODES,
    MAX_FILE_ARTIFACT_METADATA_KEYS as MAX_FILE_ARTIFACT_METADATA_KEYS,
    MAX_FILE_ARTIFACT_FIELD_CHARS as MAX_FILE_ARTIFACT_FIELD_CHARS,
    is_file_artifact_checksum,
    validate_file_extraction_artifact,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.rag_projection import build_file_rag_projection
from miy_api.domains.rag.contracts import RagProjection
from miy_api.domains.retrieval.models import (
    RetrievalProjectionEvent,
    RetrievalProjectionHead,
)
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE

_COMPOSITION_KEY = object()


@dataclass(frozen=True)
class _PreparedCoreFileProjection:
    event: ProjectionEventRef


def is_prepared_core_file_projection(db: Session) -> bool:
    return isinstance(db.info.get(_COMPOSITION_KEY), _PreparedCoreFileProjection)


def _validate_event_ref(event: ProjectionEventRef) -> None:
    if not isinstance(event, ProjectionEventRef) or (
        event.resource_type != FILE_MANAGER_FILE_RESOURCE_TYPE
        or not isinstance(event.resource_id, str)
        or not 0 < len(event.resource_id) <= 255
        or type(event.event_sequence) is not int
        or event.event_sequence < 1
        or type(event.projection_version) is not int
        or event.projection_version < 1
        or event.change_kind not in {"content", "visibility", "delete", "repair"}
        or event.desired_state not in {"active", "deleted"}
        or (
            event.content_checksum is not None
            and not is_file_artifact_checksum(event.content_checksum)
        )
        or (
            event.visibility_checksum is not None
            and (
                not isinstance(event.visibility_checksum, str)
                or len(event.visibility_checksum) > 128
            )
        )
        or (event.change_kind == "delete" and event.desired_state != "deleted")
        or (event.desired_state == "deleted" and event.change_kind not in {"delete", "repair"})
    ):
        raise FileArtifactInvalid("event_ref_invalid")
    try:
        if str(UUID(event.retrieval_partition_id)) != event.retrieval_partition_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise FileArtifactInvalid("event_partition_invalid") from error


@contextmanager
def prepared_core_file_projection(db: Session, *, projection_event: ProjectionEventRef):
    """Scope one actual event supplied by an internal Core composition.

    Every read independently checks its persisted event/current head. No grant,
    global factory, settings, public request input or runtime activation changes.
    """
    _validate_event_ref(projection_event)
    if _COMPOSITION_KEY in db.info:
        raise FileArtifactInvalid("file_projection_already_prepared")
    db.info[_COMPOSITION_KEY] = _PreparedCoreFileProjection(projection_event)
    try:
        yield
    finally:
        db.info.pop(_COMPOSITION_KEY, None)


def require_prepared_core_file_projection_event(
    db: Session,
    *,
    projection_event: ProjectionEventRef | None = None,
    file_id: str | None = None,
) -> ProjectionEventRef:
    """Read the exact persisted Core event and its current head; never row-lock."""
    context = db.info.get(_COMPOSITION_KEY)
    if not isinstance(context, _PreparedCoreFileProjection):
        raise FileArtifactInvalid("file_projection_context_required")
    event = context.event
    if (projection_event is not None and projection_event != event) or (
        file_id is not None and file_id != event.resource_id
    ):
        raise FileArtifactInvalid("event_context_mismatch")
    fields = (
        "event_sequence",
        "resource_type",
        "resource_id",
        "projection_version",
        "retrieval_partition_id",
        "change_kind",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    )
    head_fields = (
        "projection_version",
        "retrieval_partition_id",
        "desired_state",
        "content_checksum",
        "visibility_checksum",
    )
    with db.no_autoflush:
        actual = db.execute(
            select(*(getattr(RetrievalProjectionEvent, field) for field in fields)).where(
                RetrievalProjectionEvent.event_sequence == event.event_sequence
            )
        ).one_or_none()
        if actual is None or tuple(actual) != tuple(getattr(event, field) for field in fields):
            raise FileArtifactInvalid("persisted_event_mismatch")
        head = db.execute(
            select(*(getattr(RetrievalProjectionHead, field) for field in head_fields)).where(
                RetrievalProjectionHead.resource_type == event.resource_type,
                RetrievalProjectionHead.resource_id == event.resource_id,
            )
        ).one_or_none()
    if head is None or tuple(head) != tuple(getattr(event, field) for field in head_fields):
        raise FileArtifactNotReady("event_superseded")
    return event


def load_ready_file_rag_projection(
    db: Session, *, file_id: str, expected_checksum: str | None = None
) -> RagProjection | None:
    """Read a bounded ready artifact for the exact accepted current Core event.

    Only a missing/deleted Source is None. Pending/failed/unsupported/malformed
    or mismatched artifacts are explicit control outcomes and never tombstones.
    No storage IO, extraction, OCR, Source mutation, flush or commit occurs.
    """
    event = require_prepared_core_file_projection_event(db, file_id=file_id)
    if expected_checksum is not None and expected_checksum != event.content_checksum:
        raise FileArtifactChecksumMismatch("expected_event_checksum_mismatch")
    with db.no_autoflush:
        file = db.scalar(
            select(FileManagerFile)
            .options(
                joinedload(FileManagerFile.owner).load_only(
                    User.id, User.display_name, User.full_name, raiseload=True
                ),
                joinedload(FileManagerFile.corpus).load_only(
                    FileManagerCorpus.id, FileManagerCorpus.access_scope_kind, raiseload=True
                ),
                joinedload(FileManagerFile.source_metadata).load_only(
                    FileManagerFileSourceMetadata.file_id,
                    FileManagerFileSourceMetadata.source_kind,
                    FileManagerFileSourceMetadata.title,
                    FileManagerFileSourceMetadata.author,
                    FileManagerFileSourceMetadata.authored_at,
                    FileManagerFileSourceMetadata.department,
                    FileManagerFileSourceMetadata.document_type,
                    FileManagerFileSourceMetadata.source_updated_at,
                    FileManagerFileSourceMetadata.content_checksum,
                    raiseload=True,
                ),
                undefer(FileManagerFile.extraction_text),
                undefer(FileManagerFile.extraction_blocks),
                undefer(FileManagerFile.extraction_metadata),
                raiseload("*"),
            )
            .where(FileManagerFile.id == file_id)
            .execution_options(populate_existing=True)
        )
    if file is None or file.deleted_at is not None:
        return None
    if event.desired_state != "active":
        raise FileArtifactNotReady("event_not_active")
    if file.extraction_status in {"pending", "failed", "unsupported"}:
        raise FileArtifactNotReady("source_" + file.extraction_status)
    if file.extraction_status != "ready":
        raise FileArtifactInvalid("source_status_invalid")
    if event.content_checksum is None:
        raise FileArtifactNotReady("event_checksum_pending")
    artifact = validate_file_extraction_artifact(
        file_id=file.id,
        content_checksum=file.extraction_content_checksum,
        text=file.extraction_text,
        blocks=file.extraction_blocks,
        metadata=file.extraction_metadata,
    )
    if artifact.content_checksum != event.content_checksum:
        raise FileArtifactChecksumMismatch("accepted_event_checksum_mismatch")
    if str(file.retrieval_partition_id) != event.retrieval_partition_id:
        raise FileArtifactInvalid("source_partition_mismatch")
    source = file.source_metadata
    if source is not None and source.content_checksum != artifact.content_checksum:
        raise FileArtifactChecksumMismatch("external_input_checksum_mismatch")
    return build_file_rag_projection(file=file, artifact=artifact)
