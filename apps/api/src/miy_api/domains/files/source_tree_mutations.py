"""Inactive Source-only fixed flat tree; caller owns COMMIT, history never replays."""

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
    FileManagerFolder,
)
from miy_api.domains.files.source_mutation_contracts import (
    FileSourceMutationConflict,
    FileSourceMutationReceipt,
    FileSourceMutationRefused,
)
from miy_api.domains.files.source_mutations import _FILE_COLUMNS, _event_lock, _stamp
from miy_api.domains.files.source_tree_mutation_contracts import (
    MAX_FLAT_FOLDER_FILES,
    FileSourceFolderDeleteExpected,
    FileSourceFolderDeleteMember,
    FileSourceFolderDeleteReceipt,
    FileSourceFolderDeleteSpec,
    FileSourceFolderFileExpected,
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

_FOLDER_COLUMNS = (
    FileManagerFolder.id,
    FileManagerFolder.owner_id,
    FileManagerFolder.retrieval_partition_id,
    FileManagerFolder.corpus_id,
    FileManagerFolder.parent_id,
    FileManagerFolder.name,
    FileManagerFolder.visibility,
    FileManagerFolder.created_at,
    FileManagerFolder.updated_at,
    FileManagerFolder.deleted_at,
)


def _spec(value: FileSourceFolderDeleteSpec) -> FileSourceFolderDeleteSpec:
    if not isinstance(value, FileSourceFolderDeleteSpec):
        raise FileSourceMutationRefused("source_contract_invalid")
    return FileSourceFolderDeleteSpec.model_validate(value)


def _intent(
    spec: FileSourceFolderDeleteSpec, member: FileSourceFolderDeleteMember
) -> ProjectionIntent:
    return ProjectionIntent(
        resource_type="file_manager_file",
        resource_id=member.file_id,
        retrieval_partition_id=spec.expected.retrieval_partition_id,
        change_kind="delete",
        desired_state="deleted",
        operation="delete",
        trace_context={
            "files_source_mutation": {
                "protocol_version": 1,
                "command": "native_root_flat_folder_soft_delete",
                "spec_digest": spec.digest(),
                "folder_id": spec.folder_id,
                "folder_before_digest": spec.expected.digest(),
                "before_digest": member.expected.digest(),
                "actor_user_id": spec.actor_user_id,
                "execution_ref": spec.execution_ref,
                "previous_event_id": str(member.expected.tip_event_id),
                "previous_event_digest": member.expected.tip_event_digest,
                "previous_source_revision": member.expected.tip_source_revision,
            }
        },
    )


def _locked_source(
    db: Session, spec: FileSourceFolderDeleteSpec, *, observe: bool
) -> tuple[FileManagerFolder, list[FileManagerFile]]:
    gate = "pg_advisory_xact_lock_shared" if observe else "pg_advisory_xact_lock"
    db.execute(
        text(f"SELECT {gate}(hashtextextended(:identity,0))"),
        {"identity": "files.source.standalone:" + str(spec.expected.retrieval_partition_id)},
    )
    require_prepared_file_source_partition(
        db, partition_id=str(spec.expected.retrieval_partition_id), managed_metadata_version=None
    )
    folder = db.scalar(
        select(FileManagerFolder)
        .options(load_only(*_FOLDER_COLUMNS, raiseload=True))
        .where(FileManagerFolder.id == spec.folder_id)
        .with_for_update(read=observe)
        .execution_options(populate_existing=True)
    )
    if folder is None:
        raise FileSourceMutationRefused("current_source_scope_unavailable")
    _folder_scope(folder, spec)
    if not observe:
        # FOR UPDATE conflicts with both parent_id/folder_id FK KEY SHARE.
        # It protects current membership within this transaction, not inserts
        # into a soft-deleted parent after COMMIT by unconverted participants.
        nested = db.scalar(
            select(FileManagerFolder.id).where(FileManagerFolder.parent_id == folder.id).limit(1)
        )
        members = list(
            db.scalars(
                select(FileManagerFile.id)
                .where(FileManagerFile.folder_id == folder.id)
                .order_by(FileManagerFile.id)
                .limit(MAX_FLAT_FOLDER_FILES + 1)
            )
        )
        if nested is not None or members != [member.file_id for member in spec.members]:
            raise FileSourceMutationConflict("source_tree_membership_changed")
    files = []
    for member in spec.members:
        file = db.scalar(
            select(FileManagerFile)
            .options(load_only(*_FILE_COLUMNS, raiseload=True))
            .where(FileManagerFile.id == member.file_id)
            .with_for_update(read=observe)
            .execution_options(populate_existing=True)
        )
        if file is None:
            raise FileSourceMutationRefused("current_source_scope_unavailable")
        files.append(file)
    return folder, files


def _folder_scope(folder: FileManagerFolder, spec: FileSourceFolderDeleteSpec) -> None:
    if (
        folder.owner_id != spec.actor_user_id
        or folder.visibility != "private"
        or folder.corpus_id is not None
        or folder.parent_id is not None
        or str(folder.retrieval_partition_id) != str(spec.expected.retrieval_partition_id)
    ):
        raise FileSourceMutationRefused("current_source_scope_unavailable")


def _scope(
    db: Session,
    folder: FileManagerFolder,
    files: list[FileManagerFile],
    spec: FileSourceFolderDeleteSpec,
) -> None:
    _folder_scope(folder, spec)
    for file in files:
        if (
            file.owner_id != spec.actor_user_id
            or file.visibility != "private"
            or file.corpus_id is not None
            or file.folder_id != spec.folder_id
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


def _folder_before(folder: FileManagerFolder) -> FileSourceFolderDeleteExpected:
    return FileSourceFolderDeleteExpected(
        owner_id=folder.owner_id,
        retrieval_partition_id=folder.retrieval_partition_id,
        name=folder.name,
        visibility=folder.visibility,
        corpus_id=folder.corpus_id,
        parent_id=folder.parent_id,
        deleted_at=_stamp(folder.deleted_at),
        created_at=_stamp(folder.created_at),
        updated_at=_stamp(folder.updated_at),
    )


def _file_before(
    file: FileManagerFile, event: OfficialProjectionOutbox
) -> FileSourceFolderFileExpected:
    return FileSourceFolderFileExpected(
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


def _previous(event: OfficialProjectionOutbox | None, member: FileSourceFolderDeleteMember) -> None:
    if event is None:
        raise FileSourceMutationConflict("source_tip_changed")
    intent = ProjectionIntent.model_validate_json(event.payload)
    if (
        str(event.event_id) != str(member.expected.tip_event_id)
        or event.resource_type != "file_manager_file"
        or event.resource_id != member.file_id
        or event.source_revision != member.expected.tip_source_revision
        or event.payload_digest != member.expected.tip_event_digest
        or intent.canonical() != event.payload
        or intent.digest() != event.payload_digest
        or intent.resource_type != "file_manager_file"
        or intent.resource_id != member.file_id
        or intent.retrieval_partition_id != member.expected.retrieval_partition_id
        or intent.desired_state != "active"
        or intent.content_checksum != member.expected.extraction_content_checksum
    ):
        raise FileSourceMutationConflict("source_tip_changed")


def _current(
    db: Session,
    folder: FileManagerFolder,
    files: list[FileManagerFile],
    spec: FileSourceFolderDeleteSpec,
    execution_ref: str,
) -> None:
    require_current_file_source_writer(db)
    require_current_file_source_actor(
        db, actor_user_id=spec.actor_user_id, execution_ref=execution_ref
    )
    _scope(db, folder, files, spec)


def _receipt(
    events: list[OfficialProjectionOutbox], spec: FileSourceFolderDeleteSpec, *, historical: bool
) -> FileSourceFolderDeleteReceipt:
    return FileSourceFolderDeleteReceipt(
        folder_id=spec.folder_id,
        spec_digest=spec.digest(),
        historical=historical,
        events=tuple(
            FileSourceMutationReceipt(
                file_id=member.file_id,
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
            for member, event in zip(spec.members, events, strict=True)
        ),
    )


@file_source_stage
def stage_native_root_folder_soft_delete(
    db: Session, *, spec: FileSourceFolderDeleteSpec
) -> FileSourceFolderDeleteReceipt:
    spec = _spec(spec)
    begin_file_source_stage(db)
    require_current_file_source_actor(
        db, actor_user_id=spec.actor_user_id, execution_ref=spec.execution_ref
    )
    folder, files = _locked_source(db, spec, observe=False)
    _current(db, folder, files, spec, spec.execution_ref)
    if folder.deleted_at is not None or any(file.deleted_at is not None for file in files):
        raise FileSourceMutationRefused("mutation_observation_required")
    if _folder_before(folder) != spec.expected:
        raise FileSourceMutationConflict("source_state_changed")
    for member in spec.members:
        lock_projection_source(db, "file_manager_file", member.file_id)
    for member, file in zip(spec.members, files, strict=True):
        tip = db.scalar(
            select(OfficialProjectionOutbox)
            .where(
                OfficialProjectionOutbox.resource_type == "file_manager_file",
                OfficialProjectionOutbox.resource_id == member.file_id,
            )
            .order_by(OfficialProjectionOutbox.source_revision.desc())
            .limit(1)
        )
        _previous(tip, member)
        if _file_before(file, tip) != member.expected:
            raise FileSourceMutationConflict("source_state_changed")
    for identifier in sorted(member.event_id for member in spec.members):
        _event_lock(db, identifier, shared=False)
    _current(db, folder, files, spec, spec.execution_ref)
    if any(db.get(OfficialProjectionOutbox, str(member.event_id)) for member in spec.members):
        raise FileSourceMutationRefused("mutation_observation_required")
    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    folder.deleted_at = deleted_at
    for file in files:
        file.deleted_at = deleted_at
        file.extraction_status = "pending"
        file.extraction_content_checksum = None
        file.extraction_text = None
        file.extraction_blocks = []
        file.extraction_metadata = {}
        file.extraction_error_code = None
        file.extracted_at = None
    db.flush()
    events = []
    try:
        for member in spec.members:
            events.append(
                append_projection_intent(db, intent=_intent(spec, member), event_id=member.event_id)
            )
    except ProjectionOutboxError:
        raise FileSourceMutationConflict("mutation_event_conflict") from None
    _current(db, folder, files, spec, spec.execution_ref)
    return _receipt(events, spec, historical=False)


@file_source_stage
def observe_native_root_folder_soft_delete(
    db: Session,
    *,
    spec: FileSourceFolderDeleteSpec,
    expected_event_digests: tuple[str, ...],
    current_execution_ref: str,
) -> FileSourceFolderDeleteReceipt | None:
    spec = _spec(spec)
    if type(expected_event_digests) is not tuple or expected_event_digests != tuple(
        _intent(spec, member).digest() for member in spec.members
    ):
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
    folder, files = _locked_source(db, spec, observe=True)
    _current(db, folder, files, spec, current_execution_ref)
    for identifier in sorted(member.event_id for member in spec.members):
        _event_lock(db, identifier, shared=True)
    events = []
    unobserved = 0
    for member, digest in zip(spec.members, expected_event_digests, strict=True):
        event = db.get(OfficialProjectionOutbox, str(member.event_id), populate_existing=True)
        if event is None:
            unobserved += 1
            continue
        _previous(db.get(OfficialProjectionOutbox, str(member.expected.tip_event_id)), member)
        if (
            event.resource_type != "file_manager_file"
            or event.resource_id != member.file_id
            or event.source_revision != member.expected.tip_source_revision + 1
            or event.payload != _intent(spec, member).canonical()
            or event.payload_digest != digest
        ):
            raise FileSourceMutationConflict("mutation_witness_mismatch")
        events.append(event)
    _current(db, folder, files, spec, current_execution_ref)
    if events and unobserved:
        raise FileSourceMutationConflict("mutation_witness_incomplete")
    return _receipt(events, spec, historical=True) if events else None
