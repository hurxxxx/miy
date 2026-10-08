"""Fixed private native flat-folder deletion; no discovery or execution authority."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from miy_api.domains.files.source_mutation_contracts import (
    FileSourceDeleteExpected,
    FileSourceMutationReceipt,
    _canonical,
    _stamp,
)

MAX_FLAT_FOLDER_FILES = 16
MAX_FLAT_FOLDER_SPEC_BYTES = 128 * 1024


def _identity(value: str) -> None:
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid Source identity")


class FileSourceFolderDeleteExpected(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    owner_id: str = Field(min_length=1, max_length=36, strict=True)
    retrieval_partition_id: UUID
    name: str = Field(min_length=1, max_length=255, strict=True)
    visibility: Literal["private"] = "private"
    corpus_id: None = None
    parent_id: None = None
    deleted_at: None = None
    created_at: str = Field(min_length=1, max_length=40, strict=True)
    updated_at: str = Field(min_length=1, max_length=40, strict=True)

    @model_validator(mode="after")
    def validate_expected(self):
        _identity(self.owner_id)
        if "\x00" in self.name:
            raise ValueError("invalid Source identity")
        _stamp(self.created_at)
        _stamp(self.updated_at)
        return self

    def canonical(self) -> str:
        return _canonical(self.model_dump(mode="json"))

    def digest(self) -> str:
        return sha256(self.canonical().encode()).hexdigest()


class FileSourceFolderFileExpected(FileSourceDeleteExpected):
    folder_id: str = Field(min_length=1, max_length=36, strict=True)

    @model_validator(mode="after")
    def validate_folder(self):
        _identity(self.folder_id)
        return self


class FileSourceFolderDeleteMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    file_id: str = Field(min_length=1, max_length=36, strict=True)
    event_id: UUID
    expected: FileSourceFolderFileExpected = Field(repr=False)

    @model_validator(mode="after")
    def validate_member(self):
        _identity(self.file_id)
        return self


class FileSourceFolderDeleteSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    folder_id: str = Field(min_length=1, max_length=36, strict=True)
    actor_user_id: str = Field(min_length=1, max_length=36, strict=True)
    execution_ref: str = Field(min_length=1, max_length=36, strict=True)
    expected: FileSourceFolderDeleteExpected = Field(repr=False)
    members: tuple[FileSourceFolderDeleteMember, ...] = Field(
        min_length=1, max_length=MAX_FLAT_FOLDER_FILES, repr=False
    )

    @model_validator(mode="after")
    def validate_spec(self):
        for value in (self.folder_id, self.actor_user_id, self.execution_ref):
            _identity(value)
        identifiers = [member.file_id for member in self.members]
        events = {member.event_id for member in self.members}
        previous = {member.expected.tip_event_id for member in self.members}
        if (
            identifiers != sorted(set(identifiers))
            or len(events) != len(self.members)
            or len(previous) != len(self.members)
            or events & previous
            or self.actor_user_id != self.expected.owner_id
            or any(
                member.expected.owner_id != self.actor_user_id
                or member.expected.folder_id != self.folder_id
                or member.expected.retrieval_partition_id != self.expected.retrieval_partition_id
                for member in self.members
            )
        ):
            raise ValueError("native flat-folder deletion identity mismatch")
        if len(self.canonical().encode()) > MAX_FLAT_FOLDER_SPEC_BYTES:
            raise ValueError("Source deletion spec exceeds byte bound")
        return self

    def canonical(self) -> str:
        return _canonical(
            {
                "protocol_version": 1,
                "command": "native_root_flat_folder_soft_delete",
                **self.model_dump(mode="json"),
            }
        )

    def digest(self) -> str:
        return sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class FileSourceFolderDeleteReceipt:
    folder_id: str
    spec_digest: str
    events: tuple[FileSourceMutationReceipt, ...]
    provisional: bool = True
    historical: bool = False
