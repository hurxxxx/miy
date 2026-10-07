"""Inactive fixed Source stages. Callers own the fresh outer transaction."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from functools import wraps
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, load_only

from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import AuthSession, CompanyAppControl, User, UserSystemRole
from miy_api.domains.files.access_policy import filter_readable_files, readable_folder_subset
from miy_api.domains.files.artifact_contract import validate_file_extraction_artifact
from miy_api.domains.files.extraction_contracts import (
    LOCAL_EXTRACTION_POLICY,
    TERMINAL_STATES,
    FileExtractionBoundInput,
    FileExtractionComputedResult,
    FileExtractionConflict,
    FileExtractionInput,
    FileExtractionParserInput,
    FileExtractionReceipt,
    FileExtractionRefused,
    FileExtractionRequestSpec,
)
from miy_api.domains.files.models import (
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
    FileManagerFolder,
)
from miy_api.domains.files.source_extraction_bootstrap import (
    FileExtractionBootstrapMember,
    FileExtractionBootstrapProbe,
    FileExtractionBootstrapWorkset,
)
from miy_api.domains.official_apps.file_extraction_models import FileExtractionRequest
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_models import OfficialProjectionOutbox
from miy_api.domains.official_apps.projection_outbox import (
    append_projection_intent,
    lock_projection_source,
    require_current_transaction,
)
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember


# Fixed command and current app/ACL query routes, including conditional group
# and PMS-team grants. Session routing must not split this one Source transaction.
_SOURCE_SESSION_MODELS = (
    AuthSession,
    User,
    UserSystemRole,
    CompanyAppControl,
    AppAccessPolicy,
    AppUserGrant,
    AppGroupGrant,
    Group,
    GroupMember,
    FileManagerCorpus,
    FileManagerFile,
    FileManagerFolder,
    FileManagerFileAccessGrant,
    FileManagerFileSourceMetadata,
    FileExtractionRequest,
    OfficialProjectionOutbox,
    Team,
    TeamMember,
    SpaceGroupBinding,
)


def _clock() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def require_fresh_file_extraction_session(db: Session) -> None:
    """Non-SQL factory/stage validation grants no Source execution authority."""
    try:
        engine = db.get_bind()
    except SQLAlchemyError:
        raise FileExtractionRefused("source_engine_binding_required") from None
    if not isinstance(engine, Engine):
        raise FileExtractionRefused("source_engine_binding_required")
    if db.in_transaction() or db.in_nested_transaction() or db.new or db.dirty or db.deleted:
        raise FileExtractionRefused("fresh_clean_outer_transaction_required")
    try:
        for model in _SOURCE_SESSION_MODELS:
            if (
                db.get_bind(mapper=model) is not engine
                or db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise FileExtractionRefused("source_engine_binding_required")
    except SQLAlchemyError:
        raise FileExtractionRefused("source_engine_binding_required") from None


def _stage(function):
    @wraps(function)
    def wrapped(db: Session, *args, **kwargs):
        require_fresh_file_extraction_session(db)
        try:
            return function(db, *args, **kwargs)
        except Exception as error:
            if db.in_transaction():
                try:
                    db.rollback()
                except BaseException:
                    # Cleanup cannot prove rollback or replace the stable control.
                    pass
            if isinstance(error, SQLAlchemyError):
                # DBAPI/StatementError may embed canonical text, object keys and
                # SQL parameters. Runtime callers receive no raw database error.
                raise FileExtractionRefused("source_database_refused") from None
            if isinstance(error, ValidationError):
                raise FileExtractionRefused("source_contract_invalid") from None
            raise

    return wrapped


def _admit(db: Session, request_id: UUID | None = None) -> None:
    db.execute(
        text("SELECT public.miy_file_extraction_admit(CAST(:request_id AS uuid))"),
        {"request_id": str(request_id) if request_id else None},
    )


def _start(db: Session, *, request_id: UUID | None = None) -> None:
    # Reject previously flushed unrelated writes as well as pending ORM writes.
    # This is a fresh Session stage, not arbitrary borrowed-transaction commit.
    require_fresh_file_extraction_session(db)
    require_current_transaction(db)
    # Pooled TEMP relations must not shadow current execution, ACL or Source rows.
    db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
    db.execute(text("SELECT set_config('lock_timeout','5s',true)"))
    db.execute(text("SELECT set_config('statement_timeout','15s',true)"))
    _admit(db, request_id)


def _authorize(
    db: Session, *, actor_user_id: str, execution_ref: str, file: FileManagerFile
) -> None:
    session = db.execute(
        select(
            AuthSession.user_id,
            AuthSession.expires_at,
            AuthSession.revoked_at,
            AuthSession.impersonator_user_id,
        ).where(AuthSession.id == execution_ref)
    ).one_or_none()
    if (
        session is None
        or session.user_id != actor_user_id
        or session.expires_at <= _clock()
        or session.revoked_at is not None
        or session.impersonator_user_id is not None
    ):
        raise FileExtractionRefused("current_execution_denied")
    user = db.scalar(
        select(User)
        .options(load_only(User.id, User.status, User.login_blocked, raiseload=True))
        .where(User.id == actor_user_id)
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or user.status != "active"
        or user.login_blocked
        or not can_use_app(db, user_id=actor_user_id, app_id="files")
    ):
        raise FileExtractionRefused("current_actor_or_app_denied")
    folders, incomplete = readable_folder_subset(
        db,
        user=user,
        folder_ids={file.folder_id} if file.folder_id and not file.corpus_id else set(),
    )
    if incomplete or not filter_readable_files(
        db, user=user, files=[file], accessible_folder_ids=folders
    ):
        raise FileExtractionRefused("current_source_acl_denied")


_EXPECTED_CORPUS_UNSET = object()


def _file(
    db: Session,
    file_id: str,
    *,
    lock: bool = True,
    expected_corpus_id=_EXPECTED_CORPUS_UNSET,
) -> FileManagerFile:
    # Bind the Source corpus before its File. There is no Core partition read.
    corpus_id = db.scalar(select(FileManagerFile.corpus_id).where(FileManagerFile.id == file_id))
    if expected_corpus_id is not _EXPECTED_CORPUS_UNSET and corpus_id != expected_corpus_id:
        # Multi-File composition already locked its complete discovered corpus
        # set. Do not take an unexpected later aggregate lock after File locks.
        raise FileExtractionRefused("source_binding_changed")
    if corpus_id is not None:
        corpus = db.scalar(
            select(FileManagerCorpus)
            .where(FileManagerCorpus.id == corpus_id)
            .with_for_update(read=True)
        )
        if corpus is None or corpus.access_scope_kind != "company":
            raise FileExtractionRefused("source_binding_unavailable")
    query = (
        select(FileManagerFile)
        .where(FileManagerFile.id == file_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    file = db.scalar(query)
    if (
        file is None
        or file.deleted_at is not None
        or file.retrieval_partition_id is None
        or file.corpus_id != corpus_id
    ):
        raise FileExtractionRefused("source_binding_unavailable")
    if corpus_id is not None and str(corpus.retrieval_partition_id) != str(
        file.retrieval_partition_id
    ):
        raise FileExtractionRefused("source_binding_unavailable")
    return file


def _pending_input(db: Session, file: FileManagerFile) -> FileExtractionInput:
    if file.extraction_status != "pending" or file.extraction_content_checksum is not None:
        raise FileExtractionRefused("pending_source_required")
    lock_projection_source(db, "file_manager_file", file.id)
    tip = db.scalar(
        select(OfficialProjectionOutbox)
        .where(
            OfficialProjectionOutbox.resource_type == "file_manager_file",
            OfficialProjectionOutbox.resource_id == file.id,
        )
        .order_by(OfficialProjectionOutbox.source_revision.desc())
        .limit(1)
    )
    if tip is None:
        raise FileExtractionRefused("genuine_pending_intent_required")
    intent = ProjectionIntent.model_validate_json(tip.payload)
    if (
        intent.digest() != tip.payload_digest
        or intent.resource_type != "file_manager_file"
        or intent.resource_id != file.id
        or str(intent.retrieval_partition_id) != str(file.retrieval_partition_id)
        or intent.desired_state != "active"
        or intent.operation != "upsert"
        or intent.content_checksum is not None
    ):
        raise FileExtractionRefused("genuine_pending_intent_required")
    source = db.execute(
        select(
            FileManagerFileSourceMetadata.source_version,
            FileManagerFileSourceMetadata.content_checksum,
        )
        .where(FileManagerFileSourceMetadata.file_id == file.id)
        .with_for_update(read=True)
    ).one_or_none()
    return FileExtractionInput(
        storage_key=file.storage_key,
        size_bytes=file.size_bytes,
        updated_at=file.updated_at.isoformat(timespec="microseconds"),
        filename=file.filename,
        content_type=file.content_type,
        owner_id=file.owner_id,
        visibility=file.visibility,
        corpus_id=file.corpus_id,
        folder_id=file.folder_id,
        retrieval_partition_id=file.retrieval_partition_id,
        source_version=source.source_version if source else None,
        source_content_checksum=source.content_checksum if source else None,
        pending_event_id=tip.event_id,
        pending_event_digest=tip.payload_digest,
    )


@_stage
def capture_file_extraction_input(
    db: Session, *, actor_user_id: str, execution_ref: str, file_id: str
) -> FileExtractionInput:
    _start(db)
    file = _file(db, file_id)
    _authorize(db, actor_user_id=actor_user_id, execution_ref=execution_ref, file=file)
    captured = _pending_input(db, file)
    _authorize(db, actor_user_id=actor_user_id, execution_ref=execution_ref, file=file)
    return captured


def _receipt(row: FileExtractionRequest, *, newly_acquired: bool = False) -> FileExtractionReceipt:
    return FileExtractionReceipt(
        request_id=UUID(row.request_id),
        result_id=UUID(row.result_id),
        event_id=UUID(row.event_id),
        request_digest=row.request_digest,
        state=row.state,
        input_sha256=row.input_sha256,
        input_byte_count=row.input_byte_count,
        result_digest=row.result_digest,
        hold_reason=row.hold_reason,
        newly_acquired=newly_acquired,
        claim_token=UUID(row.claim_token) if row.claim_token else None,
        producer_role_oid=row.producer_role_oid,
        historical=row.state in TERMINAL_STATES,
    )


def _request(
    db: Session, request_id: UUID, request_digest: str, *, lock: bool = True
) -> FileExtractionRequest:
    query = (
        select(FileExtractionRequest)
        .where(FileExtractionRequest.request_id == str(request_id))
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise FileExtractionRefused("request_unobserved")
    if row.request_digest != request_digest:
        raise FileExtractionConflict("request_digest_conflict")
    return row


def _expected(row: FileExtractionRequest) -> FileExtractionInput:
    return FileExtractionInput.model_validate_json(
        json.loads(row.request_payload)["input_canonical"]
    )


def _bootstrap_spec(
    row: FileExtractionRequest, *, current_input: FileExtractionInput
) -> FileExtractionRequestSpec:
    try:
        spec = FileExtractionRequestSpec(
            request_id=row.request_id,
            result_id=row.result_id,
            event_id=row.event_id,
            file_id=row.file_id,
            actor_user_id=row.actor_user_id,
            execution_ref=row.execution_ref,
            parser_policy=row.parser_policy,
            expected_input=_expected(row),
        )
    except (ValueError, TypeError):
        raise FileExtractionConflict("bootstrap_request_conflict") from None
    if (
        spec.canonical() != row.request_payload
        or spec.digest() != row.request_digest
        or spec.expected_input != current_input
        or row.input_fingerprint != current_input.fingerprint()
    ):
        raise FileExtractionConflict("bootstrap_request_conflict")
    return spec


@_stage
def probe_file_extraction_workset(
    db: Session, *, workset: FileExtractionBootstrapWorkset
) -> FileExtractionBootstrapProbe:
    """Observe a fixed current selection; create no requests, IDs or permits."""
    workset = FileExtractionBootstrapWorkset.model_validate(workset)
    _start(db)
    discovered = dict(
        db.execute(
            select(FileManagerFile.id, FileManagerFile.corpus_id).where(
                FileManagerFile.id.in_(workset.file_ids)
            )
        ).all()
    )
    if tuple(sorted(discovered)) != workset.file_ids:
        raise FileExtractionRefused("source_binding_unavailable")
    # Aggregate/tree writers lock sorted corpora before Files. A sorted File
    # selection can map to the opposite corpus order, so discover the complete
    # bounded set and retain all corpus SHARE locks first.
    for corpus_id in sorted({value for value in discovered.values() if value is not None}):
        corpus = db.scalar(
            select(FileManagerCorpus)
            .where(FileManagerCorpus.id == corpus_id)
            .with_for_update(read=True)
        )
        if corpus is None or corpus.access_scope_kind != "company":
            raise FileExtractionRefused("source_binding_unavailable")
    members = []
    files = []
    for file_id in workset.file_ids:
        file = _file(db, file_id, expected_corpus_id=discovered[file_id])
        _authorize(
            db,
            actor_user_id=workset.actor_user_id,
            execution_ref=workset.execution_ref,
            file=file,
        )
        current_input = _pending_input(db, file)
        row = db.scalar(
            select(FileExtractionRequest).where(
                FileExtractionRequest.file_id == file_id,
                FileExtractionRequest.input_fingerprint == current_input.fingerprint(),
                FileExtractionRequest.parser_policy == LOCAL_EXTRACTION_POLICY,
            )
        )
        if row is None:
            member = FileExtractionBootstrapMember(file_id, "unrequested", current_input)
        elif (
            row.actor_user_id != workset.actor_user_id or row.execution_ref != workset.execution_ref
        ):
            member = FileExtractionBootstrapMember(file_id, "reserved_other_execution")
        else:
            spec = _bootstrap_spec(row, current_input=current_input)
            if row.state not in TERMINAL_STATES:
                _admit(db, UUID(row.request_id))
            disposition = (
                "existing_terminal"
                if row.state in TERMINAL_STATES
                else "existing_prepared"
                if row.state == "prepared"
                else "existing_bound"
            )
            member = FileExtractionBootstrapMember(
                file_id, disposition, current_input, spec, _receipt(row)
            )
        _authorize(
            db,
            actor_user_id=workset.actor_user_id,
            execution_ref=workset.execution_ref,
            file=file,
        )
        members.append(member)
        files.append(file)
    # A later member can wait after an earlier member's ACL observation. Recheck
    # the entire supplied selection after the last Source lock, with current time.
    for file in files:
        _authorize(
            db,
            actor_user_id=workset.actor_user_id,
            execution_ref=workset.execution_ref,
            file=file,
        )
    return FileExtractionBootstrapProbe(tuple(members))


@_stage
def prepare_file_extraction(
    db: Session, *, spec: FileExtractionRequestSpec
) -> FileExtractionReceipt:
    _start(db)
    file = _file(db, spec.file_id)
    _authorize(db, actor_user_id=spec.actor_user_id, execution_ref=spec.execution_ref, file=file)
    existing = db.get(FileExtractionRequest, str(spec.request_id), populate_existing=True)
    if existing is not None:
        if existing.request_payload != spec.canonical() or existing.request_digest != spec.digest():
            raise FileExtractionConflict("request_identity_conflict")
        return _receipt(existing)
    actual = _pending_input(db, file)
    _authorize(db, actor_user_id=spec.actor_user_id, execution_ref=spec.execution_ref, file=file)
    if actual != spec.expected_input:
        raise FileExtractionRefused("source_input_changed")
    duplicate = db.scalar(
        select(FileExtractionRequest.request_id).where(
            FileExtractionRequest.file_id == spec.file_id,
            FileExtractionRequest.input_fingerprint == actual.fingerprint(),
            FileExtractionRequest.parser_policy == spec.parser_policy,
        )
    )
    if duplicate is not None:
        raise FileExtractionConflict("input_already_requested")
    row = FileExtractionRequest(
        request_id=str(spec.request_id),
        result_id=str(spec.result_id),
        event_id=str(spec.event_id),
        file_id=spec.file_id,
        actor_user_id=spec.actor_user_id,
        execution_ref=spec.execution_ref,
        parser_policy=spec.parser_policy,
        request_payload=spec.canonical(),
        request_digest=spec.digest(),
        input_fingerprint=actual.fingerprint(),
        state="prepared",
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return _receipt(row)


def _active(db: Session, *, request_id: UUID, request_digest: str, execution_ref: str):
    _start(db)
    observed = _request(db, request_id, request_digest, lock=False)
    file = _file(db, observed.file_id)
    row = _request(db, request_id, request_digest)
    if row.state not in TERMINAL_STATES:
        _admit(db, request_id)
        if row.execution_ref != execution_ref:
            raise FileExtractionRefused("original_execution_required")
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    return row, file


@_stage
def claim_file_extraction(
    db: Session, *, request_id: UUID, request_digest: str, execution_ref: str, claim_token: UUID
) -> FileExtractionReceipt:
    row, file = _active(
        db, request_id=request_id, request_digest=request_digest, execution_ref=execution_ref
    )
    if row.state in TERMINAL_STATES:
        if row.claim_token != str(claim_token):
            raise FileExtractionConflict("claim_token_conflict")
        return replace(_receipt(row), provisional=False)
    if _pending_input(db, file) != _expected(row):
        raise FileExtractionRefused("source_input_changed")
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    if row.state == "prepared":
        row.claim_token = str(claim_token)
        row.state = "claimed"
        row.claimed_at = _clock()
        db.flush()
        return _receipt(row, newly_acquired=True)
    if row.claim_token != str(claim_token):
        raise FileExtractionConflict("claim_token_conflict")
    return _receipt(row)


def _read_source(file: FileManagerFile) -> bytes:
    # Owned Source transport: no caller-supplied bytes, URL, provider or credential.
    from miy_api.core.settings import get_settings
    from miy_api.domains.files.selected_storage import SelectedStorageConfig, read_selected_object

    settings = get_settings()
    config = SelectedStorageConfig(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        region=settings.independent_app_file_selection_storage_region,
    )
    return asyncio.run(
        read_selected_object(config, storage_key=file.storage_key, expected_size=file.size_bytes)
    )


@_stage
def bind_file_extraction_input(
    db: Session, *, request_id: UUID, request_digest: str, execution_ref: str, claim_token: UUID
) -> FileExtractionBoundInput:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise FileExtractionRefused("synchronous_runner_required")
    row, file = _active(
        db, request_id=request_id, request_digest=request_digest, execution_ref=execution_ref
    )
    if row.state != "claimed" or row.claim_token != str(claim_token):
        raise FileExtractionRefused("new_claim_read_required")
    captured = _pending_input(db, file)
    if captured != _expected(row):
        raise FileExtractionRefused("source_input_changed")
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    content = _read_source(file)
    digest = sha256(content).hexdigest()
    if len(content) != captured.size_bytes or (
        captured.source_content_checksum is not None and captured.source_content_checksum != digest
    ):
        raise FileExtractionRefused("source_bytes_changed")
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    if _pending_input(db, file) != captured:
        raise FileExtractionRefused("source_input_changed")
    row.input_sha256 = digest
    row.input_byte_count = len(content)
    row.state = "input_bound"
    row.input_bound_at = _clock()
    db.flush()
    return FileExtractionBoundInput(
        _receipt(row), FileExtractionParserInput(file.id, file.filename, file.content_type), content
    )


@_stage
def apply_file_extraction_result(
    db: Session,
    *,
    request_id: UUID,
    request_digest: str,
    execution_ref: str,
    claim_token: UUID,
    computed_result: FileExtractionComputedResult,
    expected_result_digest: str | None = None,
) -> FileExtractionReceipt:
    row, file = _active(
        db, request_id=request_id, request_digest=request_digest, execution_ref=execution_ref
    )
    if row.state in TERMINAL_STATES:
        # A body-submitting API cannot verify a historical body that is not
        # duplicated in the receipt. Observe the retained digest separately.
        raise FileExtractionRefused("terminal_observation_required")
    if (
        row.state != "input_bound"
        or row.claim_token != str(claim_token)
        or row.input_sha256 != computed_result.input_sha256
    ):
        raise FileExtractionConflict("result_claim_or_input_conflict")
    if _pending_input(db, file) != _expected(row):
        raise FileExtractionRefused("source_input_changed")
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    if computed_result.outcome == "ocr_required":
        row.hold_reason = "ocr_required"
        db.flush()
        return _receipt(row)
    if computed_result.outcome == "ready":
        artifact = computed_result.artifact
        if artifact is None:
            raise FileExtractionRefused("ready_artifact_required")
        artifact = validate_file_extraction_artifact(
            file_id=file.id,
            content_checksum=artifact.content_checksum,
            text=artifact.text,
            blocks=[b.to_dict() for b in artifact.blocks],
            metadata=artifact.metadata,
        )
        if artifact.content_checksum != row.input_sha256:
            raise FileExtractionConflict("result_checksum_conflict")
        file.extraction_text = artifact.text
        file.extraction_blocks = [b.to_dict() for b in artifact.blocks]
        file.extraction_metadata = artifact.metadata
        file.extraction_content_checksum = artifact.content_checksum
        file.extraction_error_code = None
    else:
        if (
            computed_result.outcome not in {"unsupported", "failed"}
            or computed_result.artifact is not None
        ):
            raise FileExtractionRefused("result_outcome_invalid")
        file.extraction_text = None
        file.extraction_blocks = []
        file.extraction_content_checksum = None
        file.extraction_error_code = (
            "unsupported_source"
            if computed_result.outcome == "unsupported"
            else "local_parser_failed"
        )
        file.extraction_metadata = (
            {"parser_version": "files-retrieval-v2", "unsupported_reason": "unsupported_source"}
            if computed_result.outcome == "unsupported"
            else {}
        )
    file.extraction_status = computed_result.outcome
    file.extracted_at = _clock()
    db.flush()
    db.refresh(file)
    if computed_result.outcome in {"ready", "unsupported"}:
        deleted = computed_result.outcome == "unsupported"
        append_projection_intent(
            db,
            event_id=UUID(row.event_id),
            intent=ProjectionIntent(
                resource_type="file_manager_file",
                resource_id=file.id,
                retrieval_partition_id=file.retrieval_partition_id,
                change_kind="delete" if deleted else "content",
                desired_state="deleted" if deleted else "active",
                operation="delete" if deleted else "upsert",
                content_checksum=file.extraction_content_checksum,
            ),
        )
    # The genuine append may wait on its retained event-ID lock after the
    # resource-stream admission. Recheck actual authority after that last wait
    # and before any terminal receipt; refusal rolls back flushed File/intent.
    _authorize(db, actor_user_id=row.actor_user_id, execution_ref=execution_ref, file=file)
    result_digest = db.scalar(
        text(
            "SELECT public.miy_file_extraction_result_digest(CAST(:request_id AS uuid), :outcome)"
        ),
        {"request_id": row.request_id, "outcome": computed_result.outcome},
    )
    if result_digest is None:
        raise FileExtractionRefused("result_digest_unavailable")
    if expected_result_digest is not None and result_digest != expected_result_digest:
        raise FileExtractionConflict("result_digest_conflict")
    row.state = computed_result.outcome
    row.result_digest = result_digest
    row.completed_at = _clock()
    row.error_code = file.extraction_error_code
    row.hold_reason = None
    db.flush()
    return _receipt(row)


@_stage
def observe_file_extraction(
    db: Session,
    *,
    request_id: UUID,
    request_digest: str,
    actor_user_id: str,
    execution_ref: str,
    expected_result_id: UUID | None = None,
    expected_result_digest: str | None = None,
    expected_claim_token: UUID | None = None,
    expected_input_sha256: str | None = None,
    require_original_execution: bool = False,
) -> FileExtractionReceipt:
    _start(db, request_id=request_id if require_original_execution else None)
    row = _request(db, request_id, request_digest, lock=False)
    if row.actor_user_id != actor_user_id:
        raise FileExtractionRefused("historical_actor_mismatch")
    if require_original_execution and row.execution_ref != execution_ref:
        raise FileExtractionRefused("original_execution_required")
    if expected_result_id is not None and row.result_id != str(expected_result_id):
        raise FileExtractionConflict("result_identity_conflict")
    if expected_result_digest is not None and row.result_digest != expected_result_digest:
        raise FileExtractionConflict("result_digest_conflict")
    if expected_claim_token is not None and row.claim_token != str(expected_claim_token):
        raise FileExtractionConflict("claim_token_conflict")
    if expected_input_sha256 is not None and row.input_sha256 != expected_input_sha256:
        raise FileExtractionConflict("input_checksum_conflict")
    file = _file(db, row.file_id, lock=False)
    _authorize(db, actor_user_id=actor_user_id, execution_ref=execution_ref, file=file)
    return replace(_receipt(row), provisional=False)
