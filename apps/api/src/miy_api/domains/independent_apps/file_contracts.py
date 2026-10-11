"""Selected-file protocol: opaque capabilities, never platform credentials."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from miy_api.core.app_origins import exact_origin
from miy_api.domains.independent_apps.contracts import Contract

OpaqueFileToken = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"^[A-Za-z0-9_.-]+$")]
FileVersion = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MAX_FILE_BYTES = 10 * 1024 * 1024


class FileSelectionContext(Contract):
    schema_version: Literal[1]
    installation_id: UUID
    audience: str = Field(max_length=300)
    selection_id: UUID

    @field_validator("schema_version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("Use integer version 1")
        return value

    @field_validator("audience")
    @classmethod
    def canonical_audience(cls, value: str) -> str:
        if exact_origin(value) != value:
            raise ValueError("Use an exact origin")
        return value


class FileSelectionRequestOut(FileSelectionContext):
    selection_request: OpaqueFileToken
    expires_at: datetime
    max_bytes: Literal[10485760] = MAX_FILE_BYTES


class FileCandidatesInput(FileSelectionContext):
    selection_request: OpaqueFileToken
    query: str = Field(default="", max_length=120)
    cursor: str | None = Field(default=None, max_length=2048)
    limit: int = Field(default=25, ge=1, le=25, strict=True)


class FileSelectionMetadata(Contract):
    file_id: UUID
    name: str = Field(max_length=255)
    content_type: str = Field(max_length=255)
    size_bytes: int = Field(ge=0, le=MAX_FILE_BYTES, strict=True)
    version: FileVersion


class FileCandidatesOut(FileSelectionContext):
    items: list[FileSelectionMetadata] = Field(max_length=25)
    next_cursor: str | None
    incomplete: bool


class FileAuthorizeInput(FileSelectionContext):
    selection_request: OpaqueFileToken
    file_id: UUID
    expected_version: FileVersion


class SelectedFileReadOut(FileSelectionContext):
    file: FileSelectionMetadata
    read_grant: OpaqueFileToken
    expires_at: datetime
