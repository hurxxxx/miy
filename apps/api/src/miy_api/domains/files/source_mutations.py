"""Inactive Source-only native root deletion and immutable history observation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session, load_only

from miy_api.domains.files.extraction_commands import (
    begin_file_source_stage,
    file_source_stage,
    require_current_file_source_actor,
    require_current_file_source_writer,
)
from miy_api.domains.files.models import (
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
)
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceDeleteSpec,
    FileSourceMutationConflict,
    FileSourceMutationReceipt,
    FileSourceMutationRefused,
)
from miy_api.domains.official_apps.projection_contracts import (
    ProjectionIntent,
    ProjectionOutboxError,
)
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import (
    append_projection_intent,
    lock_projection_source,
)
from miy_api.domains.retrieval.prepared_file_partitions import (
    require_prepared_file_source_partition,
)

_FILE_COLUMNS = (
    FileManagerFile.id,
    FileManagerFile.owner_id,
    FileManagerFile.retrieval_partition_id,
    FileManagerFile.corpus_id,
    FileManagerFile.folder_id,
    FileManagerFile.visibility,
    FileManagerFile.storage_key,
    FileManagerFile.filename,
    FileManagerFile.content_type,
    FileManagerFile.size_bytes,
    FileManagerFile.extraction_status,
    FileManagerFile.extraction_content_checksum,
    FileManagerFile.extraction_error_code,
    FileManagerFile.extracted_at,
    FileManagerFile.created_at,
    FileManagerFile.updated_at,
    FileManagerFile.deleted_at,
)


def _spec(value: FileSourceDeleteSpec) -> FileSourceDeleteSpec:
    if not isinstance(value, FileSourceDeleteSpec):
        raise FileSourceMutationRefused("source_contract_invalid")
    return FileSourceDeleteSpec.model_validate(value)


def _intent(spec: FileSourceDeleteSpec) -> ProjectionIntent:
    return ProjectionIntent(
        resource_type="file_manager_file",
        resource_id=spec.file_id,
        retrieval_partition_id=spec.expected.retrieval_partition_id,
        change_kind="delete",
        desired_state="deleted",
        operation="delete",
        trace_context={
            "files_source_mutation": {
                "protocol_version": 1,
                "command": "native_root_file_soft_delete",
                "spec_digest": spec.digest(),
                "before_digest": spec.expected.digest(),
                "actor_user_id": spec.actor_user_id,
                "execution_ref": spec.execution_ref,
                "previous_event_id": str(spec.expected.tip_event_id),
                "previous_event_digest": spec.expected.tip_event_digest,
                "previous_source_revision": spec.expected.tip_source_revision,
            }
        },
    )


def _event_lock(db: Session, identifier: UUID, *, shared: bool) -> None:
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    db.execute(
        text(f"SELECT {function}(hashtextextended(:identity,0))"),
        {"identity": "official.projection.event:" + str(identifier)},
    )


def _locked_file(db: Session, spec: FileSourceDeleteSpec, *, observe: bool) -> FileManagerFile:
    # Only this prepared leaf participates in the new Source-local gate. The
    # descriptor SHARE additionally interoperates with legacy tree UPDATE locks.
    gate = "pg_advisory_xact_lock_shared" if observe else "pg_advisory_xact_lock"
    db.execute(
        text(f"SELECT {gate}(hashtextextended(:identity,0))"),
        {"identity": "files.source.standalone:" + str(spec.expected.retrieval_partition_id)},
    )
    require_prepared_file_source_partition(
        db, partition_id=str(spec.expected.retrieval_partition_id), managed_metadata_version=None
    )
    file = db.scalar(
        select(FileManagerFile)
        .options(load_only(*_FILE_COLUMNS, raiseload=True))
        .where(FileManagerFile.id == spec.file_id)
        .with_for_update(read=observe)
        .execution_options(populate_existing=True)
    )
    if file is None:
        raise FileSourceMutationRefused("current_source_scope_unavailable")
    return file


def _scope(db: Session, file: FileManagerFile, spec: FileSourceDeleteSpec) -> None:
    if (
        file.owner_id != spec.actor_user_id
        or file.visibility != "private"
        or file.corpus_id is not None
        or file.folder_id is not None
        or str(file.retrieval_partition_id) != str(spec.expected.retrieval_partition_id)
        or db.scalar(
            select(FileManagerFileSourceMetadata.file_id)
            .where(FileManagerFileSourceMetadata.file_id == file.id)
            .limit(1)
        )
        is not None
        or db.scalar(
            select(FileManagerFileAccessGrant.file_id)
            .where(FileManagerFileAccessGrant.file_id == file.id)
            .limit(1)
        )
        is not None
    ):
        raise FileSourceMutationRefused("current_source_scope_unavailable")


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds") if value is not None else None


def _before(file: FileManagerFile, event: OfficialProjectionOutbox) -> FileSourceDeleteExpected:
    return FileSourceDeleteExpected(
        owner_id=file.owner_id,
        retrieval_partition_id=file.retrieval_partition_id,
        storage_key=file.storage_key,
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=file.size_bytes,
        visibility=file.visibility,
        corpus_id=file.corpus_id,
        folder_id=file.folder_id,
        deleted_at=_stamp(file.deleted_at),
        created_at=_stamp(file.created_at),
        updated_at=_stamp(file.updated_at),
        extraction_status=file.extraction_status,
        extraction_content_checksum=file.extraction_content_checksum,
        extraction_error_code=file.extraction_error_code,
        extracted_at=_stamp(file.extracted_at),
        tip_event_id=event.event_id,
        tip_event_digest=event.payload_digest,
        tip_source_revision=event.source_revision,
    )


def _previous(event: OfficialProjectionOutbox | None, spec: FileSourceDeleteSpec) -> None:
    if event is None:
        raise FileSourceMutationConflict("source_tip_changed")
    intent = ProjectionIntent.model_validate_json(event.payload)
    if (
        str(event.event_id) != str(spec.expected.tip_event_id)
        or event.resource_type != "file_manager_file"
        or event.resource_id != spec.file_id
        or event.source_revision != spec.expected.tip_source_revision
        or event.payload_digest != spec.expected.tip_event_digest
        or intent.canonical() != event.payload
        or intent.digest() != event.payload_digest
        or intent.resource_type != "file_manager_file"
        or intent.resource_id != spec.file_id
        or intent.retrieval_partition_id != spec.expected.retrieval_partition_id
        or intent.desired_state != "active"
        or intent.content_checksum != spec.expected.extraction_content_checksum
    ):
        raise FileSourceMutationConflict("source_tip_changed")


def _receipt(event: OfficialProjectionOutbox, spec: FileSourceDeleteSpec, *, historical: bool):
    return FileSourceMutationReceipt(
        file_id=spec.file_id,
        event_id=UUID(str(event.event_id)),
        event_digest=event.payload_digest,
        source_revision=event.source_revision,
        spec_digest=spec.digest(),
        producer_role_oid=event.producer_role_oid,
        producer_role_name=event.producer_role_name,
        producer_generation=event.producer_generation,
        producer_artifact=event.producer_artifact,
        historical=historical,
    )


def _current(
    db: Session, file: FileManagerFile, spec: FileSourceDeleteSpec, execution_ref: str
) -> None:
    require_current_file_source_writer(db)
    require_current_file_source_actor(
        db, actor_user_id=spec.actor_user_id, execution_ref=execution_ref
    )
    _scope(db, file, spec)


@file_source_stage
def stage_native_root_file_soft_delete(
    db: Session, *, spec: FileSourceDeleteSpec
) -> FileSourceMutationReceipt:
    spec = _spec(spec)
    begin_file_source_stage(db)
    require_current_file_source_actor(
        db, actor_user_id=spec.actor_user_id, execution_ref=spec.execution_ref
    )
    file = _locked_file(db, spec, observe=False)
    _current(db, file, spec, spec.execution_ref)
    if file.deleted_at is not None:
        raise FileSourceMutationRefused("mutation_observation_required")
    lock_projection_source(db, "file_manager_file", spec.file_id)
    tip = db.scalar(
        select(OfficialProjectionOutbox)
        .where(
            OfficialProjectionOutbox.resource_type == "file_manager_file",
            OfficialProjectionOutbox.resource_id == spec.file_id,
        )
        .order_by(OfficialProjectionOutbox.source_revision.desc())
        .limit(1)
    )
    _previous(tip, spec)
    if _before(file, tip) != spec.expected:
        raise FileSourceMutationConflict("source_state_changed")
    _current(db, file, spec, spec.execution_ref)
    if db.get(OfficialProjectionOutbox, str(spec.event_id)) is not None:
        raise FileSourceMutationRefused("mutation_observation_required")
    file.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    file.extraction_status = "pending"
    file.extraction_content_checksum = None
    file.extraction_text = None
    file.extraction_blocks = []
    file.extraction_metadata = {}
    file.extraction_error_code = None
    file.extracted_at = None
    db.flush()
    try:
        event = append_projection_intent(db, intent=_intent(spec), event_id=spec.event_id)
    except ProjectionOutboxError:
        raise FileSourceMutationConflict("mutation_event_conflict") from None
    _current(db, file, spec, spec.execution_ref)
    return _receipt(event, spec, historical=False)


@file_source_stage
def observe_native_root_file_soft_delete(
    db: Session,
    *,
    spec: FileSourceDeleteSpec,
    expected_event_digest: str,
    current_execution_ref: str,
) -> FileSourceMutationReceipt | None:
    spec = _spec(spec)
    if expected_event_digest != _intent(spec).digest():
        raise FileSourceMutationConflict("mutation_witness_mismatch")
    if (
        type(current_execution_ref) is not str
        or not 1 <= len(current_execution_ref) <= 36
        or current_execution_ref != current_execution_ref.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in current_execution_ref)
    ):
        raise FileSourceMutationRefused("source_contract_invalid")
    begin_file_source_stage(db)
    require_current_file_source_actor(
        db, actor_user_id=spec.actor_user_id, execution_ref=current_execution_ref
    )
    file = _locked_file(db, spec, observe=True)
    _current(db, file, spec, current_execution_ref)
    _event_lock(db, spec.event_id, shared=True)
    event = db.get(OfficialProjectionOutbox, str(spec.event_id), populate_existing=True)
    if event is not None:
        previous = db.get(OfficialProjectionOutbox, str(spec.expected.tip_event_id))
        _previous(previous, spec)
        if (
            event.resource_type != "file_manager_file"
            or event.resource_id != spec.file_id
            or event.source_revision != spec.expected.tip_source_revision + 1
            or event.payload != _intent(spec).canonical()
            or event.payload_digest != expected_event_digest
        ):
            raise FileSourceMutationConflict("mutation_witness_mismatch")
    _current(db, file, spec, current_execution_ref)
    return _receipt(event, spec, historical=True) if event is not None else None
