"""Private current-workset observations, not compute permits or global coverage."""

from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from miy_api.domains.files.extraction_contracts import (
    FileExtractionInput,
    FileExtractionReceipt,
    FileExtractionRequestSpec,
)

BootstrapDisposition = Literal[
    "unrequested",
    "existing_prepared",
    "existing_bound",
    "existing_terminal",
    "reserved_other_execution",
]


class FileExtractionBootstrapWorkset(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )
    actor_user_id: str = Field(min_length=1, max_length=36)
    execution_ref: str = Field(min_length=1, max_length=80, repr=False)
    file_ids: tuple[Annotated[str, Field(min_length=1, max_length=36)], ...] = Field(
        min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def normalized_ids(self):
        if any(value != value.strip() or "\x00" in value for value in self.file_ids):
            raise ValueError("invalid bootstrap File identity")
        object.__setattr__(self, "file_ids", tuple(sorted(set(self.file_ids))))
        return self


@dataclass(frozen=True, slots=True)
class FileExtractionBootstrapMember:
    file_id: str
    disposition: BootstrapDisposition
    current_input: FileExtractionInput | None = field(default=None, repr=False)
    spec: FileExtractionRequestSpec | None = field(default=None, repr=False)
    receipt: FileExtractionReceipt | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.disposition == "reserved_other_execution":
            if any(value is not None for value in (self.current_input, self.spec, self.receipt)):
                raise ValueError("reserved execution exposes status only")
        elif self.current_input is None:
            raise ValueError("bootstrap observation requires captured input")
        elif self.disposition == "unrequested":
            if self.spec is not None or self.receipt is not None:
                raise ValueError("unrequested input cannot manufacture a request")
        elif self.spec is None or self.receipt is None or self.receipt.newly_acquired:
            raise ValueError("existing bootstrap observation grants no claim")


@dataclass(frozen=True, slots=True)
class FileExtractionBootstrapProbe:
    members: tuple[FileExtractionBootstrapMember, ...]
    provisional: bool = True
