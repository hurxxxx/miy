from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from celery.exceptions import Ignore
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from miy_worker.task_binding import task_app

from miy_worker.runtime import (
    db_session as _db_session,
)
from miy_worker.runtime import (
    ensure_api_src_on_path as _ensure_api_src_on_path,
)
from miy_worker.runtime import (
    minio_client as _minio_client,
)
from miy_worker.settings import get_settings

_ensure_api_src_on_path()

from miy_api.core.asr import (  # noqa: E402
    PermanentError,
    TransientError,
    check_asr_health,
    get_asr_backend,
)
from miy_api.core.llm import LlmRuntimeError, LlmTaskContext  # noqa: E402
from miy_api.domains.ai.gateway import (  # noqa: E402
    LlmWorkloadContext,
    execute_llm,
)
from miy_api.domains.auth.app_gate import (  # noqa: E402
    can_use_app,
)
from miy_api.domains.recording.models import Recording, RecordingResult  # noqa: E402
from miy_api.domains.official_apps.source_guard import lock_source_writer  # noqa: E402
from miy_api.domains.recording import pipeline_commands as managed_pipeline  # noqa: E402
from miy_api.domains.recording.pipeline_contracts import (  # noqa: E402
    RecordingCommandDuplicate,
    RecordingCommandError,
)

celery_app = task_app(__name__)

logger = logging.getLogger(__name__)


class SupersededRecordingGeneration(Exception):
    """Terminal no-op for a task that no longer owns the recording attempt."""


class RecordingSummaryCommitUnknown(Exception):
    """A summary phase cannot infer whether its COMMIT was accepted."""


class RecordingPhaseCommitUnknown(Exception):
    """ASR or persistence cannot infer whether its source COMMIT was accepted."""


@dataclass(frozen=True)
class _SummaryClaim:
    recording_id: str
    attempt_id: str
    owner_id: str
    result_version: int | None
    expected_summary: str | None = None


@dataclass(frozen=True, kw_only=True)
class _SourceClaim(_SummaryClaim):
    storage_key: str


def _commit_recording_phase(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise RecordingPhaseCommitUnknown("recording_phase_commit_unknown") from None


def _commit_summary_phase(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        raise RecordingSummaryCommitUnknown("recording_summary_commit_unknown") from None


def _lock_summary_claim(session: Session, claim: _SummaryClaim) -> Recording:
    # Keep the same source -> parent -> result lock order in every phase.
    with session.no_autoflush:
        lock_source_writer(session, "recordings")
        recording = _lock_current_recording_attempt(session, claim.recording_id, claim.attempt_id)
        result = session.scalar(
            select(RecordingResult)
            .where(RecordingResult.recording_id == claim.recording_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            recording.owner_id != claim.owner_id
            or recording.audio_status != "saved"
            or not recording.storage_key
            or (result.version if result is not None else None) != claim.result_version
            or (
                claim.expected_summary is not None
                and (result is None or result.summary_text != claim.expected_summary)
            )
        ):
            raise SupersededRecordingGeneration()
        managed_pipeline.check_execution(session, recording, result)
        return recording


def _fail_summary_phase(session: Session, claim: _SummaryClaim, reason: str) -> bool:
    session.rollback()
    try:
        recording = _lock_summary_claim(session, claim)
    except SupersededRecordingGeneration:
        return False
    recording.summary_status = "failed"
    recording.failure_reason = reason[:5000]
    recording.celery_task_id = None
    recording.updated_at = _utcnow()
    session.add(recording)
    managed_pipeline.finish_command(session, recording, failed=True)
    _commit_summary_phase(session)
    return True


def _require_summary_access(session: Session, claim: _SummaryClaim, recording: Recording) -> None:
    if can_use_app(session, app_id="recording", user_id=recording.owner_id):
        return
    _fail_summary_phase(
        session, claim, "Recording app execution disabled or requester membership revoked."
    )
    raise Ignore()


def _lock_source_claim(session: Session, claim: _SourceClaim) -> Recording:
    recording = _lock_summary_claim(session, claim)
    if recording.storage_key != claim.storage_key:
        raise SupersededRecordingGeneration()
    return recording


def _fail_source_phase(session: Session, claim: _SourceClaim, reason: str, *, stage: str) -> bool:
    session.rollback()
    try:
        recording = _lock_source_claim(session, claim)
    except SupersededRecordingGeneration:
        return False
    if stage == "transcript":
        recording.transcript_status = "failed"
    else:
        recording.summary_status = "failed"
    recording.failure_reason = reason[:5000]
    recording.celery_task_id = None
    recording.updated_at = _utcnow()
    session.add(recording)
    managed_pipeline.finish_command(session, recording, failed=True)
    _commit_recording_phase(session)
    return True


def _require_source_access(
    session: Session, claim: _SourceClaim, recording: Recording, *, stage: str
) -> None:
    if can_use_app(session, app_id="recording", user_id=recording.owner_id):
        return
    _fail_source_phase(
        session,
        claim,
        "Recording app execution disabled or requester membership revoked.",
        stage=stage,
    )
    raise Ignore()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _load_active_recording(session: Session, recording_id: str) -> Recording | None:
    recording = session.scalar(
        select(Recording)
        .options(selectinload(Recording.targets), selectinload(Recording.result))
        .where(Recording.id == recording_id)
        .execution_options(populate_existing=True)
    )
    if recording is None:
        return None
    if recording.trashed_at is not None:
        return None
    if recording.audio_status != "saved" or not recording.storage_key:
        return None
    return recording


def _lock_current_recording_attempt(
    session: Session,
    recording_id: str,
    expected_attempt_id: str,
) -> Recording:
    if not expected_attempt_id:
        raise SupersededRecordingGeneration()
    recording = session.scalar(
        select(Recording)
        .options(selectinload(Recording.targets), selectinload(Recording.result))
        .where(
            Recording.id == recording_id,
            Recording.celery_task_id == expected_attempt_id,
            Recording.trashed_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if recording is None:
        raise SupersededRecordingGeneration()
    return recording


def _heartbeat(
    session: Session,
    recording: Recording,
    pct: int,
    *,
    expected_attempt_id: str,
    transcript_status: str | None = None,
    summary_status: str | None = None,
    commit_phase: Callable[[Session], None] | None = None,
) -> None:
    recording = _lock_current_recording_attempt(
        session,
        recording.id,
        expected_attempt_id,
    )
    recording.progress_pct = max(0, min(100, pct))
    if transcript_status is not None:
        recording.transcript_status = transcript_status
    if summary_status is not None:
        recording.summary_status = summary_status
    recording.updated_at = _utcnow()
    session.add(recording)
    if commit_phase is None:
        session.commit()
    else:
        commit_phase(session)


def _ensure_current_attempt(recording: Recording, expected_attempt_id: str) -> None:
    if not expected_attempt_id or recording.celery_task_id != expected_attempt_id:
        raise SupersededRecordingGeneration()


def _mark_failed(
    session: Session,
    recording_id: str,
    reason: str,
    *,
    stage: str,
    expected_attempt_id: str,
) -> bool:
    session.rollback()
    try:
        recording = _lock_current_recording_attempt(
            session,
            recording_id,
            expected_attempt_id,
        )
    except SupersededRecordingGeneration:
        return False
    if stage == "transcript":
        recording.transcript_status = "failed"
    else:
        recording.summary_status = "failed"
    recording.failure_reason = reason[:5000]
    recording.celery_task_id = None
    recording.updated_at = _utcnow()
    session.add(recording)
    session.commit()
    return True


def _ensure_recording_execution_allowed(
    session: Session,
    recording: Recording,
    *,
    stage: str,
    expected_attempt_id: str,
) -> None:
    _ensure_current_attempt(recording, expected_attempt_id)
    if can_use_app(
        session,
        app_id="recording",
        user_id=recording.owner_id,
    ):
        return
    _mark_failed(
        session,
        recording.id,
        "Recording app execution disabled or requester membership revoked.",
        stage=stage,
        expected_attempt_id=expected_attempt_id,
    )
    raise Ignore()


def _download_recording_to_tmp(recording: Recording) -> str:
    settings = get_settings()
    suffix = Path(recording.storage_key or "").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    handle.close()
    _minio_client().fget_object(
        settings.minio_bucket,
        recording.storage_key,
        handle.name,
    )
    return handle.name


def _recording_title(recording: Recording) -> str:
    return recording.title.strip() or f"Recording {recording.started_at:%Y-%m-%d %H:%M:%S}"


def _analysis_messages(recording: Recording, transcript: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are meeting.transcript_summarizer, a local-only specialist agent. "
                "Use only the provided transcript. Return Korean markdown with these sections: "
                "핵심 요약, 결정사항, 액션 아이템, 리스크/이슈, 후속 확인 필요. "
                "If a section has no evidence, write '확인된 내용 없음'."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Recording title: {_recording_title(recording)}\n"
                f"Started at UTC: {recording.started_at:%Y-%m-%d %H:%M:%S}\n\n"
                "Transcript:\n"
                f"{transcript}"
            ),
        },
    ]


def _verification_messages(transcript: str, summary: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are verifier.grounding. Check whether the Korean summary is grounded "
                "in the transcript. Return Korean markdown. Start with '검증: 통과' or "
                "'검증: 수정 필요'. If correction is needed, include a corrected concise summary."
            ),
        },
        {
            "role": "user",
            "content": (f"Transcript:\n{transcript[:24000]}\n\nSummary:\n{summary}"),
        },
    ]


def _complete_local_agent(
    session: Session,
    *,
    source: str,
    actor_user_id: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    context = LlmTaskContext(
        source=source,
        actor_user_id=actor_user_id,
        task_kind="meeting_summary",
        app_id="recording",
    )
    try:
        completion = execute_llm(
            "meeting_summary",
            LlmWorkloadContext.from_task_context(context),
            session,
            messages=messages,
            temperature=0.1,
            max_tokens=max_tokens,
            reasoning_effort="none",
        ).completion
    except LlmRuntimeError as error:
        # complete_chat_text preserves its database failure as the direct cause.
        # A failed gateway DB phase must not become a provider retry.
        if isinstance(error.__cause__, SQLAlchemyError):
            raise error.__cause__ from None
        raise TransientError(str(error)) from error
    result = completion.text.strip()
    if not result:
        raise PermanentError("Local transcript agent returned an empty result.")
    return result


@celery_app.task(
    name="recording.transcribe",
    bind=True,
    acks_late=True,
    max_retries=3,
    time_limit=3600,
    soft_time_limit=3300,
)
def transcribe_recording(
    self,
    recording_id: str,
    attempt_id: str,
) -> dict[str, str]:
    session = _db_session()
    tmp_path: str | None = None
    try:
        managed_pipeline.enter_command(
            session, request=self.request, stage="transcribe", args=[recording_id, attempt_id]
        )
        recording = _load_active_recording(session, recording_id)
        if recording is None:
            raise Ignore()
        _ensure_current_attempt(recording, attempt_id)
        claim = _SourceClaim(
            recording_id,
            attempt_id,
            recording.owner_id,
            recording.result.version if recording.result is not None else None,
            storage_key=recording.storage_key,
        )
        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="transcript")
        if (
            recording.result is not None
            and recording.result.transcript_text
            and recording.transcript_status == "done"
        ):
            _heartbeat(
                session,
                recording,
                max(recording.progress_pct, 60),
                expected_attempt_id=attempt_id,
                commit_phase=_commit_recording_phase,
            )
            recording = _lock_source_claim(session, claim)
            _require_source_access(session, claim, recording, stage="transcript")
            managed_pipeline.finish_command(session, recording)
            if managed_pipeline.current_execution(session) is not None:
                _commit_recording_phase(session)
            return {"recording_id": recording.id, "attempt_id": attempt_id}

        if recording.transcribe_started_at is None:
            recording.transcribe_started_at = _utcnow()
        _heartbeat(
            session,
            recording,
            max(recording.progress_pct, 10),
            expected_attempt_id=attempt_id,
            transcript_status="transcribing",
            commit_phase=_commit_recording_phase,
        )
        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="transcript")

        health = check_asr_health(deep=True)
        if not health.ready:
            raise TransientError(health.detail or "ASR backend is not ready.")

        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="transcript")
        tmp_path = _download_recording_to_tmp(recording)
        last_pct = {"value": recording.progress_pct}

        def on_progress(value: float) -> None:
            rec = _lock_source_claim(session, claim)
            _require_source_access(session, claim, rec, stage="transcript")
            pct = int(10 + max(0.0, min(1.0, value)) * 45)
            if pct <= last_pct["value"]:
                return
            _heartbeat(
                session,
                rec,
                pct,
                expected_attempt_id=attempt_id,
                transcript_status="transcribing",
                commit_phase=_commit_recording_phase,
            )
            # A durable progress commit ends the old source transaction. Do not
            # return control to the synchronous backend until the next segment
            # has been admitted against the same original source claim.
            rec = _lock_source_claim(session, claim)
            _require_source_access(session, claim, rec, stage="transcript")
            last_pct["value"] = pct

        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="transcript")
        result = get_asr_backend().transcribe(Path(tmp_path), on_progress=on_progress)
        text = result.text.strip()
        if not text:
            raise PermanentError("ASR backend returned an empty transcript.")

        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="transcript")
        result_row = session.get(RecordingResult, recording.id)
        if result_row is None:
            result_row = RecordingResult(
                recording_id=recording.id,
                transcript_text=text,
                version=1,
            )
        elif result_row.transcript_text != text:
            result_row.transcript_text = text
            result_row.summary_text = None
            result_row.verifier_note = None
            result_row.generated_at = None
            result_row.version += 1
        result_row.updated_at = _utcnow()
        session.add(result_row)
        if recording.duration_sec is None and result.duration_sec:
            recording.duration_sec = int(result.duration_sec)
        recording.transcript_status = "done"
        recording.summary_status = "pending"
        recording.transcribe_completed_at = _utcnow()
        recording.progress_pct = max(recording.progress_pct, 60)
        recording.failure_reason = None
        recording.updated_at = _utcnow()
        session.add(recording)
        managed_pipeline.finish_command(session, recording)
        _commit_recording_phase(session)
        return {"recording_id": recording.id, "attempt_id": attempt_id}
    except RecordingCommandDuplicate:
        session.rollback()
        raise Ignore() from None
    except SupersededRecordingGeneration:
        session.rollback()
        raise Ignore()
    except Ignore:
        raise
    except PermanentError as exc:
        _fail_source_phase(session, claim, str(exc), stage="transcript")
        raise Ignore()
    except TransientError as exc:
        if managed_pipeline.current_execution(session) is not None:
            # Transient does not prove that the remote effect was not accepted.
            # Keep the durable running token; never publish a speculative retry.
            session.rollback()
            raise RecordingCommandError("recording_remote_outcome_unknown") from None
        session.rollback()
        try:
            recording = _lock_source_claim(session, claim)
        except SupersededRecordingGeneration:
            raise Ignore() from None
        _require_source_access(session, claim, recording, stage="transcript")
        if self.request.retries >= self.max_retries:
            _fail_source_phase(session, claim, str(exc), stage="transcript")
            raise Ignore()
        raise self.retry(exc=exc, countdown=min(600, 2 ** (self.request.retries + 1)))
    finally:
        session.close()
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@celery_app.task(
    name="recording.analyze_transcript",
    bind=True,
    acks_late=True,
    max_retries=3,
    time_limit=900,
)
def analyze_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(payload.get("recording_id") or "")
    attempt_id = str(payload.get("attempt_id") or "")
    session = _db_session()
    try:
        managed_pipeline.enter_command(
            session, request=self.request, stage="analyze_transcript", args=[payload]
        )
        recording = _load_active_recording(session, recording_id)
        if recording is None:
            raise Ignore()
        _ensure_current_attempt(recording, attempt_id)
        result_row = recording.result
        claim = _SummaryClaim(
            recording_id,
            attempt_id,
            recording.owner_id,
            result_row.version if result_row is not None else None,
        )
        recording = _lock_summary_claim(session, claim)
        _require_summary_access(session, claim, recording)
        result_row = recording.result
        if result_row is None or not result_row.transcript_text:
            raise PermanentError("Transcript is missing.")
        if result_row.summary_text and recording.summary_status in {"verifying", "done"}:
            managed_pipeline.finish_command(session, recording)
            if managed_pipeline.current_execution(session) is not None:
                _commit_summary_phase(session)
            return {
                "recording_id": recording.id,
                "attempt_id": attempt_id,
                "result_version": result_row.version,
                "summary": result_row.summary_text,
                "agent_flow": ["domain.meeting", "meeting.transcript_summarizer"],
            }

        _heartbeat(
            session,
            recording,
            max(recording.progress_pct, 72),
            expected_attempt_id=attempt_id,
            summary_status="analyzing",
            commit_phase=_commit_summary_phase,
        )
        recording = _lock_summary_claim(session, claim)
        _require_summary_access(session, claim, recording)
        result_version = claim.result_version
        result_row = recording.result
        summary = _complete_local_agent(
            session,
            actor_user_id=recording.owner_id,
            source="worker.recording.agent.domain_meeting",
            messages=_analysis_messages(recording, result_row.transcript_text),
            max_tokens=6000,
        )
        recording = _lock_summary_claim(session, claim)
        _require_summary_access(session, claim, recording)
        if recording.result.version != result_version:
            raise SupersededRecordingGeneration()
        recording.result.summary_text = summary
        recording.result.verifier_note = None
        recording.result.updated_at = _utcnow()
        recording.summary_status = "verifying"
        recording.progress_pct = max(recording.progress_pct, 84)
        recording.updated_at = _utcnow()
        session.add(recording.result)
        session.add(recording)
        managed_pipeline.finish_command(session, recording)
        _commit_summary_phase(session)
        return {
            "recording_id": recording.id,
            "attempt_id": attempt_id,
            "result_version": result_version,
            "summary": summary,
            "agent_flow": ["domain.meeting", "meeting.transcript_summarizer"],
        }
    except RecordingCommandDuplicate:
        session.rollback()
        raise Ignore() from None
    except SupersededRecordingGeneration:
        session.rollback()
        raise Ignore()
    except Ignore:
        raise
    except PermanentError as exc:
        _fail_summary_phase(session, claim, str(exc))
        raise Ignore()
    except TransientError as exc:
        if managed_pipeline.current_execution(session) is not None:
            # Transient does not prove that the remote effect was not accepted.
            # Keep the durable running token; never publish a speculative retry.
            session.rollback()
            raise RecordingCommandError("recording_remote_outcome_unknown") from None
        session.rollback()
        try:
            recording = _lock_summary_claim(session, claim)
        except SupersededRecordingGeneration:
            raise Ignore() from None
        _require_summary_access(session, claim, recording)
        if self.request.retries >= self.max_retries:
            _fail_summary_phase(session, claim, str(exc))
            raise Ignore()
        raise self.retry(exc=exc, countdown=min(600, 2 ** (self.request.retries + 1)))
    finally:
        session.close()


@celery_app.task(
    name="recording.verify_transcript_summary",
    bind=True,
    acks_late=True,
    max_retries=3,
    time_limit=600,
)
def verify_transcript_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(payload.get("recording_id") or "")
    attempt_id = str(payload.get("attempt_id") or "")
    session = _db_session()
    try:
        managed_pipeline.enter_command(
            session, request=self.request, stage="verify_transcript_summary", args=[payload]
        )
        recording = _load_active_recording(session, recording_id)
        if recording is None:
            raise Ignore()
        _ensure_current_attempt(recording, attempt_id)
        summary = str(payload.get("summary") or "").strip()
        result_version = int(payload.get("result_version") or 0)
        claim = _SummaryClaim(recording_id, attempt_id, recording.owner_id, result_version, summary)
        recording = _lock_summary_claim(session, claim)
        _require_summary_access(session, claim, recording)
        result_row = recording.result
        transcript = (result_row.transcript_text if result_row is not None else "").strip()
        if not transcript or not summary:
            raise PermanentError("Transcript summary verification input is missing.")
        if result_row is None or result_row.version != result_version:
            raise SupersededRecordingGeneration()

        if (
            result_row is not None
            and result_row.verifier_note
            and recording.summary_status == "done"
        ):
            managed_pipeline.finish_command(session, recording)
            if managed_pipeline.current_execution(session) is not None:
                _commit_summary_phase(session)
            return {
                **payload,
                "verifier_note": result_row.verifier_note,
            }

        verifier_note = _complete_local_agent(
            session,
            actor_user_id=recording.owner_id,
            source="worker.recording.agent.verifier_grounding",
            messages=_verification_messages(transcript, summary),
            max_tokens=2500,
        )
        recording = _lock_summary_claim(session, claim)
        _require_summary_access(session, claim, recording)
        if recording.result.version != result_version:
            raise SupersededRecordingGeneration()
        recording.result.verifier_note = verifier_note
        recording.result.updated_at = _utcnow()
        recording.summary_status = "verifying"
        recording.progress_pct = max(recording.progress_pct, 94)
        recording.updated_at = _utcnow()
        session.add(recording.result)
        session.add(recording)
        managed_pipeline.finish_command(session, recording)
        _commit_summary_phase(session)
        return {
            "recording_id": recording.id,
            "attempt_id": attempt_id,
            "result_version": result_version,
            "summary": summary,
            "verifier_note": verifier_note,
            "agent_flow": [
                *list(payload.get("agent_flow") or []),
                "verifier.grounding",
            ],
        }
    except RecordingCommandDuplicate:
        session.rollback()
        raise Ignore() from None
    except SupersededRecordingGeneration:
        session.rollback()
        raise Ignore()
    except Ignore:
        raise
    except PermanentError as exc:
        _fail_summary_phase(session, claim, str(exc))
        raise Ignore()
    except TransientError as exc:
        if managed_pipeline.current_execution(session) is not None:
            # Transient does not prove that the remote effect was not accepted.
            # Keep the durable running token; never publish a speculative retry.
            session.rollback()
            raise RecordingCommandError("recording_remote_outcome_unknown") from None
        session.rollback()
        try:
            recording = _lock_summary_claim(session, claim)
        except SupersededRecordingGeneration:
            raise Ignore() from None
        _require_summary_access(session, claim, recording)
        if self.request.retries >= self.max_retries:
            _fail_summary_phase(session, claim, str(exc))
            raise Ignore()
        raise self.retry(exc=exc, countdown=min(600, 2 ** (self.request.retries + 1)))
    finally:
        session.close()


@celery_app.task(
    name="recording.persist_result",
    bind=True,
    acks_late=True,
    max_retries=3,
    time_limit=300,
)
def persist_recording_result(self, payload: dict[str, Any]) -> str:
    recording_id = str(payload.get("recording_id") or "")
    attempt_id = str(payload.get("attempt_id") or "")
    summary = str(payload.get("summary") or "").strip()
    result_version = int(payload.get("result_version") or 0)
    session = _db_session()
    try:
        managed_pipeline.enter_command(
            session, request=self.request, stage="persist_result", args=[payload]
        )
        recording = _load_active_recording(session, recording_id)
        if recording is None:
            raise Ignore()
        if (
            recording.summary_status == "done"
            and recording.result is not None
            and recording.result.version == result_version
            and recording.result.summary_text == summary
        ):
            if not can_use_app(session, app_id="recording", user_id=recording.owner_id):
                raise Ignore()
            if managed_pipeline.current_execution(session) is not None:
                # Managed final success is acknowledged only by its own durable command.
                raise RecordingCommandError("recording_command_source_changed")
            return recording.id
        claim = _SourceClaim(
            recording_id,
            attempt_id,
            recording.owner_id,
            result_version,
            summary,
            storage_key=recording.storage_key,
        )
        recording = _lock_source_claim(session, claim)
        _require_source_access(session, claim, recording, stage="summary")
        if not summary:
            raise PermanentError("Recording summary is missing.")
        verifier_note = str(payload.get("verifier_note") or "").strip()
        if recording.result is None:
            raise PermanentError("Recording transcript result is missing.")
        if recording.result.version != result_version:
            raise SupersededRecordingGeneration()
        if recording.result.summary_text != summary:
            raise SupersededRecordingGeneration()
        recording.result.verifier_note = verifier_note
        recording.result.generated_at = _utcnow()
        recording.result.updated_at = _utcnow()
        recording.summary_status = "done"
        recording.meeting_insight_status = "none"
        recording.progress_pct = 100
        recording.failure_reason = None
        recording.celery_task_id = None
        recording.updated_at = _utcnow()
        session.add(recording.result)
        session.add(recording)
        managed_pipeline.finish_command(session, recording)
        _commit_recording_phase(session)
        return recording.id
    except RecordingCommandDuplicate:
        session.rollback()
        raise Ignore() from None
    except SupersededRecordingGeneration:
        session.rollback()
        raise Ignore()
    except Ignore:
        raise
    except PermanentError as exc:
        _fail_source_phase(session, claim, str(exc), stage="summary")
        raise Ignore()
    finally:
        session.close()
