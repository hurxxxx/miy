"""Fixed inactive native-root deletion; no execution authority or ID allocation."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from miy_api.domains.files.extraction_contracts import (
    FileExtractionConflict as FileSourceMutationConflict,
    FileExtractionRefused as FileSourceMutationRefused,
)

__all__ = [
    "FileSourceDeleteExpected",
    "FileSourceDeleteSpec",
    "FileSourceMutationConflict",
    "FileSourceMutationReceipt",
    "FileSourceMutationRefused",
]


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _stamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None or parsed.isoformat(timespec="microseconds") != value:
        raise ValueError("Source timestamp must be canonical naive UTC")


class FileSourceDeleteExpected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    owner_id: str = Field(min_length=1, max_length=36, strict=True)
    retrieval_partition_id: UUID
    storage_key: str = Field(min_length=1, max_length=1024, strict=True, repr=False)
    filename: str = Field(min_length=1, max_length=512, strict=True)
    content_type: str = Field(min_length=1, max_length=160, strict=True)
    size_bytes: int = Field(ge=0, le=2_147_483_647, strict=True)
    visibility: Literal["private"] = "private"
    corpus_id: None = None
    folder_id: None = None
    deleted_at: None = None
    created_at: str = Field(min_length=1, max_length=40, strict=True)
    updated_at: str = Field(min_length=1, max_length=40, strict=True)
    extraction_status: Literal["pending", "ready", "unsupported", "failed"]
    extraction_content_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    extraction_error_code: str | None = Field(default=None, max_length=120, strict=True)
    extracted_at: str | None = Field(default=None, max_length=40, strict=True)
    tip_event_id: UUID
    tip_event_digest: str = Field(pattern=r"^[0-9a-f]{64}$", strict=True)
    tip_source_revision: int = Field(ge=1, le=9_223_372_036_854_775_806, strict=True)

    @model_validator(mode="after")
    def validate_expected(self):
        for stamp in (self.created_at, self.updated_at, self.extracted_at):
            if stamp is not None:
                _stamp(stamp)
        for value in (self.owner_id, self.storage_key, self.filename, self.content_type):
            if "\x00" in value:
                raise ValueError("invalid Source identity")
        return self

    def canonical(self) -> str:
        return _canonical(self.model_dump(mode="json"))

    def digest(self) -> str:
        return sha256(self.canonical().encode()).hexdigest()


class FileSourceDeleteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    file_id: str = Field(min_length=1, max_length=36, strict=True)
    actor_user_id: str = Field(min_length=1, max_length=36, strict=True)
    execution_ref: str = Field(min_length=1, max_length=36, strict=True)
    event_id: UUID
    expected: FileSourceDeleteExpected = Field(repr=False)

    @model_validator(mode="after")
    def validate_spec(self):
        for value in (self.file_id, self.actor_user_id, self.execution_ref):
            if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("invalid Source identity")
        if (
            self.actor_user_id != self.expected.owner_id
            or self.event_id == self.expected.tip_event_id
        ):
            raise ValueError("native root deletion identity mismatch")
        if len(self.canonical().encode()) > 8192:
            raise ValueError("Source deletion spec exceeds byte bound")
        return self

    def canonical(self) -> str:
        return _canonical(
            {
                "protocol_version": 1,
                "command": "native_root_file_soft_delete",
                **self.model_dump(mode="json"),
            }
        )

    def digest(self) -> str:
        return sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class FileSourceMutationReceipt:
    file_id: str
    event_id: UUID
    event_digest: str
    source_revision: int
    spec_digest: str
    producer_role_oid: int
    producer_role_name: str
    producer_generation: int
    producer_artifact: str | None
    provisional: bool = True
    historical: bool = False
