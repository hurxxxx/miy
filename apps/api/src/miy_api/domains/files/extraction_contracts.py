"""Fixed internal Source extraction controls; no execution authority is granted."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from miy_api.domains.files.artifact_contract import FileExtractionArtifact

LOCAL_EXTRACTION_POLICY = "files-retrieval-v2/local-only-10m-v1"
MAX_EXTRACTION_SOURCE_BYTES = 10 * 1024 * 1024
ExtractionState = Literal["prepared", "claimed", "input_bound", "ready", "unsupported", "failed"]
TERMINAL_STATES = frozenset({"ready", "unsupported", "failed"})


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class FileExtractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    storage_key: str = Field(min_length=1, max_length=1024)
    size_bytes: int = Field(ge=0, le=MAX_EXTRACTION_SOURCE_BYTES)
    updated_at: str = Field(min_length=1, max_length=40)
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=160)
    owner_id: str = Field(min_length=1, max_length=36)
    visibility: Literal["private", "company"]
    corpus_id: str | None = Field(default=None, max_length=36)
    folder_id: str | None = Field(default=None, max_length=36)
    retrieval_partition_id: UUID
    source_version: str | None = Field(default=None, max_length=4096)
    source_content_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pending_event_id: UUID
    pending_event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self):
        stamp = datetime.fromisoformat(self.updated_at)
        if stamp.tzinfo is not None or stamp.isoformat(timespec="microseconds") != self.updated_at:
            raise ValueError("input timestamp must be canonical naive UTC")
        if "\x00" in self.storage_key or "\x00" in self.filename:
            raise ValueError("input contains an invalid string")
        return self

    def canonical(self) -> str:
        return canonical_json(self.model_dump(mode="json"))

    def fingerprint(self) -> str:
        return sha256(self.canonical().encode("utf-8")).hexdigest()


class FileExtractionRequestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    result_id: UUID
    event_id: UUID
    file_id: str = Field(min_length=1, max_length=36)
    actor_user_id: str = Field(min_length=1, max_length=36)
    execution_ref: str = Field(min_length=1, max_length=80)
    parser_policy: Literal["files-retrieval-v2/local-only-10m-v1"] = LOCAL_EXTRACTION_POLICY
    expected_input: FileExtractionInput

    @model_validator(mode="after")
    def validate_envelope(self):
        if len({self.request_id, self.result_id, self.event_id}) != 3:
            raise ValueError("request/result/event identities must be distinct")
        if len(self.canonical().encode("utf-8")) > 8192:
            raise ValueError("extraction request exceeds byte bound")
        return self

    def canonical(self) -> str:
        return canonical_json(
            {
                "protocol_version": 1,
                "request_id": str(self.request_id),
                "result_id": str(self.result_id),
                "event_id": str(self.event_id),
                "file_id": self.file_id,
                "actor_user_id": self.actor_user_id,
                "execution_ref": self.execution_ref,
                "parser_policy": self.parser_policy,
                "input_canonical": self.expected_input.canonical(),
            }
        )

    def digest(self) -> str:
        return sha256(self.canonical().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FileExtractionReceipt:
    request_id: UUID
    result_id: UUID
    event_id: UUID
    request_digest: str
    state: ExtractionState
    input_sha256: str | None = None
    input_byte_count: int | None = None
    result_digest: str | None = None
    hold_reason: str | None = None
    newly_acquired: bool = False
    provisional: bool = True
    claim_token: UUID | None = None
    producer_role_oid: int | None = None
    historical: bool = False


@dataclass(frozen=True, slots=True)
class FileExtractionParserInput:
    id: str
    filename: str
    content_type: str


@dataclass(frozen=True, slots=True)
class FileExtractionComputedResult:
    outcome: Literal["ready", "unsupported", "failed", "ocr_required"]
    input_sha256: str
    artifact: FileExtractionArtifact | None = None


@dataclass(frozen=True, slots=True)
class FileExtractionBoundInput:
    receipt: FileExtractionReceipt
    parser_input: FileExtractionParserInput
    content: bytes = field(repr=False)


class FileExtractionControlError(RuntimeError):
    """Stable control identifiers contain no source bytes or provider response."""

    code = "file_extraction_control"

    def __init__(self, reason: str = "control") -> None:
        self.reason = reason
        super().__init__(self.code)


class FileExtractionNeedsOcr(FileExtractionControlError):
    code = "file_extraction_ocr_required"


class FileExtractionRefused(FileExtractionControlError):
    code = "file_extraction_refused"


class FileExtractionConflict(FileExtractionControlError):
    code = "file_extraction_conflict"


class FileExtractionCommitUnknown(FileExtractionControlError):
    code = "file_extraction_commit_unknown"

    def __init__(
        self, phase: str, receipt: FileExtractionReceipt | None, *, retained_result=None
    ) -> None:
        self.phase = phase
        self.receipt = receipt
        self._retained_result = retained_result
        super().__init__(phase)
