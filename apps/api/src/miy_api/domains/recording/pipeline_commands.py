"""Explicit source transactions for the fixed four-stage Recording protocol.

No HTTP binding, publisher, credential discovery or role preparation is here.
Every mutation uses the caller's Session; progress COMMIT keeps its durable token.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from miy_api.domains.auth.app_gate import can_use_app
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.official_apps.recording_publication_models import CoreRecordingPublication
from miy_api.domains.official_apps.source_guard import lock_source_writer
from miy_api.domains.recording.models import Recording, RecordingResult
from miy_api.domains.recording.pipeline_contracts import (
    MANAGED_HEADER,
    MANAGED_QUEUE,
    STAGES,
    RecordingCommandCommitUnknown,
    RecordingCommandDuplicate,
    RecordingCommandError,
    RecordingEnvelope,
    Stage,
    payload_digest,
    stage_args,
    text_digest,
)
from miy_api.domains.recording.pipeline_models import RecordingStageCommand

_EXECUTION = "recording_managed_execution"


def require_transaction(db: Session) -> None:
    connection = db.connection()
    if (
        connection.dialect.name != "postgresql"
        or connection.connection.driver_connection.autocommit
    ):
        raise RecordingCommandError("recording_transaction_required")
    if db.scalar(text("SELECT current_setting('transaction_isolation')")) != "read committed":
        raise RecordingCommandError("recording_read_committed_required")


def commit_command(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise RecordingCommandCommitUnknown("recording_command_commit_unknown") from None


def _locked_source(db: Session, recording_id: str):
    lock_source_writer(db, "recordings")
    recording = db.scalar(
        select(Recording)
        .where(Recording.id == recording_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    result = db.scalar(
        select(RecordingResult)
        .where(RecordingResult.recording_id == recording_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        recording is None
        or recording.trashed_at is not None
        or recording.audio_status != "saved"
        or not recording.storage_key
    ):
        raise RecordingCommandError("recording_command_source_unavailable")
    return recording, result


def _access(db: Session, recording: Recording) -> None:
    if not can_use_app(db, app_id="recording", user_id=recording.owner_id):
        raise RecordingCommandError("recording_command_access_denied")


def _new_command(
    recording, result, *, stage: Stage, attempt_id: str, predecessor_id: str | None = None
) -> RecordingStageCommand:
    return RecordingStageCommand(
        command_id=str(uuid4()),
        recording_id=recording.id,
        attempt_id=attempt_id,
        stage=stage,
        retry_ordinal=0,
        task_id=attempt_id if stage == "persist_result" else str(uuid4()),
        predecessor_id=predecessor_id,
        owner_id=recording.owner_id,
        storage_key=recording.storage_key,
        result_version=result.version if result is not None else None,
        transcript_digest=text_digest(result.transcript_text) if result is not None else None,
        summary_digest=text_digest(result.summary_text) if result is not None else None,
        verifier_digest=text_digest(result.verifier_note) if result is not None else None,
        payload_digest=payload_digest(stage_args(stage, recording.id, attempt_id, result)),
        due_at=utcnow_naive(),
        state="pending",
    )


def create_managed_recording_attempt(db: Session, *, recording_id: str, owner_id: str) -> str:
    """Explicit owner composition only. Source attempt + first command, one COMMIT."""
    require_transaction(db)
    recording, result = _locked_source(db, recording_id)
    _access(db, recording)
    if recording.owner_id != owner_id:
        raise RecordingCommandError("recording_command_owner_mismatch")
    if recording.celery_task_id or (
        recording.transcript_status == "done" and recording.summary_status == "done"
    ):
        raise RecordingCommandError("recording_command_attempt_exists")
    attempt_id = str(uuid4())
    recording.celery_task_id = attempt_id
    recording.transcript_status = "pending"
    recording.summary_status = "pending"
    recording.failure_reason = None
    recording.progress_pct = 0
    recording.updated_at = utcnow_naive()
    if result is not None:
        result.summary_text = None
        result.verifier_note = None
        result.generated_at = None
    command = _new_command(recording, result, stage="transcribe", attempt_id=attempt_id)
    db.add(command)
    db.flush()
    command_id = command.command_id
    commit_command(db)
    return command_id


def render_command_args(db: Session, command: RecordingStageCommand) -> list:
    """Read-only Core rendering: bytes must match immutable source metadata."""
    recording = db.get(Recording, command.recording_id, populate_existing=True)
    result = db.get(RecordingResult, command.recording_id, populate_existing=True)
    if (
        recording is None
        or recording.owner_id != command.owner_id
        or recording.storage_key != command.storage_key
        or recording.audio_status != "saved"
        or recording.trashed_at is not None
        or recording.celery_task_id != command.attempt_id
        or (result.version if result is not None else None) != command.result_version
        or (text_digest(result.transcript_text) if result is not None else None)
        != command.transcript_digest
        or (text_digest(result.summary_text) if result is not None else None)
        != command.summary_digest
        or (text_digest(result.verifier_note) if result is not None else None)
        != command.verifier_digest
    ):
        raise RecordingCommandError("recording_command_source_changed")
    args = stage_args(command.stage, command.recording_id, command.attempt_id, result)
    if payload_digest(args) != command.payload_digest:
        raise RecordingCommandError("recording_command_payload_changed")
    return args


@dataclass(frozen=True)
class Execution:
    command_id: str
    token: str
    recording_id: str
    attempt_id: str
    stage: Stage
    owner_id: str
    storage_key: str
    result_version: int | None


def enter_command(db: Session, *, request, stage: Stage, args: list) -> Execution | None:
    """Validate source/publication identity before durable exclusive execution."""
    attempt_id = str(args[1] if stage == "transcribe" else args[0].get("attempt_id", ""))
    headers = request.headers or {}
    if MANAGED_HEADER not in headers:
        try:
            UUID(attempt_id)
        except ValueError:
            return None
        # No protocol auto-adoption: an old message cannot execute a managed attempt.
        # Missing schema is an error, not an implicit legacy fallback.
        if db.scalar(
            select(RecordingStageCommand.command_id)
            .where(RecordingStageCommand.attempt_id == attempt_id)
            .limit(1)
        ):
            raise RecordingCommandError("recording_managed_header_required")
        return None
    require_transaction(db)
    try:
        envelope = RecordingEnvelope.model_validate(headers[MANAGED_HEADER])
    except (ValueError, TypeError):
        raise RecordingCommandError("recording_managed_header_invalid") from None
    if any(getattr(request, key, None) for key in ("chain", "callbacks", "errbacks")):
        raise RecordingCommandError("recording_managed_canvas_forbidden")
    command = db.get(RecordingStageCommand, str(envelope.command_id))
    if command is None:
        raise RecordingCommandError("recording_command_missing")
    recording, _ = _locked_source(db, command.recording_id)
    command = db.scalar(
        select(RecordingStageCommand)
        .where(RecordingStageCommand.command_id == command.command_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    publication = db.get(
        CoreRecordingPublication, str(envelope.publication_id), populate_existing=True
    )
    predecessor = (
        db.get(RecordingStageCommand, command.predecessor_id) if command.predecessor_id else None
    )
    if (
        command.stage != stage
        or command.attempt_id != attempt_id
        or str(request.id) != command.task_id
        or getattr(request, "root_id", None) != command.attempt_id
        or getattr(request, "parent_id", None)
        != (predecessor.task_id if predecessor is not None else None)
        or request.retries != command.retry_ordinal
        or (request.delivery_info or {}).get("routing_key") != MANAGED_QUEUE
        or publication is None
        or publication.command_id != command.command_id
        or publication.task_id != command.task_id
        or publication.payload_digest != command.payload_digest
        or publication.queue != MANAGED_QUEUE
        or publication.profile != "official"
        or publication.state not in {"publishing", "acknowledged", "unknown", "consumed"}
        or envelope.payload_digest != command.payload_digest
        or payload_digest(args) != command.payload_digest
        or command.due_at > utcnow_naive()
    ):
        raise RecordingCommandError("recording_command_binding_mismatch")
    if command.state != "pending":
        raise RecordingCommandDuplicate("recording_command_already_claimed")
    _access(db, recording)
    render_command_args(db, command)
    command.state = "running"
    command.execution_token = str(uuid4())
    command.started_at = utcnow_naive()
    execution = Execution(
        command.command_id,
        command.execution_token,
        command.recording_id,
        command.attempt_id,
        command.stage,
        command.owner_id,
        command.storage_key,
        command.result_version,
    )
    commit_command(db)
    db.info[_EXECUTION] = execution
    return execution


def current_execution(db: Session) -> Execution | None:
    return db.info.get(_EXECUTION)


def check_execution(db: Session, recording: Recording, result: RecordingResult | None) -> None:
    execution = current_execution(db)
    if execution is None:
        return
    if (
        recording.id != execution.recording_id
        or recording.celery_task_id != execution.attempt_id
        or recording.owner_id != execution.owner_id
        or recording.storage_key != execution.storage_key
    ):
        raise RecordingCommandError("recording_command_execution_stale")
    _access(db, recording)
    command = db.scalar(
        select(RecordingStageCommand)
        .where(RecordingStageCommand.command_id == execution.command_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        command is None
        or (result.version if result is not None else None) != execution.result_version
        or (text_digest(result.transcript_text) if result is not None else None)
        != command.transcript_digest
        or (text_digest(result.summary_text) if result is not None else None)
        != command.summary_digest
        or (text_digest(result.verifier_note) if result is not None else None)
        != command.verifier_digest
    ):
        raise RecordingCommandError("recording_command_source_changed")
    # Trigger revalidates original producer and current consumer authority on
    # every handoff, including a no-op/repeated progress callback.
    changed = db.execute(
        update(RecordingStageCommand)
        .where(
            RecordingStageCommand.command_id == execution.command_id,
            RecordingStageCommand.state == "running",
            RecordingStageCommand.execution_token == execution.token,
        )
        .values(state="running")
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        raise RecordingCommandError("recording_command_execution_stale")


def finish_command(db: Session, recording: Recording, *, failed: bool = False) -> None:
    execution = current_execution(db)
    if execution is None:
        return
    # Caller admitted source+result+execution before applying its final changes.
    # Do not reload/overwrite those staged source bytes.
    command = db.scalar(
        select(RecordingStageCommand)
        .where(RecordingStageCommand.command_id == execution.command_id)
        .with_for_update()
    )
    if command is None or command.state != "running" or command.execution_token != execution.token:
        raise RecordingCommandError("recording_command_execution_stale")
    command.state = "failed" if failed else "succeeded"
    command.finished_at = utcnow_naive()
    if not failed and execution.stage != "persist_result":
        result = db.get(RecordingResult, recording.id)
        following = STAGES[STAGES.index(execution.stage) + 1]
        db.add(
            _new_command(
                recording,
                result,
                stage=following,
                attempt_id=execution.attempt_id,
                predecessor_id=command.command_id,
            )
        )
