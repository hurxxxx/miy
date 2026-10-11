"""Fixed Recording stage delivery; no generic workflow or activation authority."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

Stage = Literal["transcribe", "analyze_transcript", "verify_transcript_summary", "persist_result"]
STAGES: tuple[Stage, ...] = (
    "transcribe",
    "analyze_transcript",
    "verify_transcript_summary",
    "persist_result",
)
COMMAND_TABLE = "recording_stage_commands"
PUBLICATION_TABLE = "core_recording_publications"
MANAGED_HEADER = "miy_recording"
MANAGED_QUEUE = "miy.official.meeting_transcribe"


class RecordingCommandError(RuntimeError):
    """Stable control failure: never provider retry or source failure mutation."""


class RecordingCommandCommitUnknown(RecordingCommandError):
    pass


class RecordingCommandDuplicate(RecordingCommandError):
    pass


class RecordingEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1]
    command_id: UUID
    publication_id: UUID
    payload_digest: str

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("invalid recording envelope version")
        return value

    @field_validator("payload_digest")
    @classmethod
    def digest_shape(cls, value):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid recording envelope digest")
        return value


def text_digest(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value is not None else None


def payload_digest(args: list) -> str:
    return hashlib.sha256(
        json.dumps(
            args, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
    ).hexdigest()


def stage_args(stage: Stage, recording_id: str, attempt_id: str, result) -> list:
    """Render only the existing four task argument shapes from source bytes."""
    if stage == "transcribe":
        return [recording_id, attempt_id]
    value = {"recording_id": recording_id, "attempt_id": attempt_id}
    if stage != "analyze_transcript":
        if result is None or not result.summary_text:
            raise RecordingCommandError("recording_command_result_missing")
        value.update(
            result_version=result.version,
            summary=result.summary_text,
            agent_flow=["domain.meeting", "meeting.transcript_summarizer"],
        )
    if stage == "persist_result":
        if result.verifier_note is None:
            raise RecordingCommandError("recording_command_result_missing")
        value.update(verifier_note=result.verifier_note)
        value["agent_flow"].append("verifier.grounding")
    return [value]
