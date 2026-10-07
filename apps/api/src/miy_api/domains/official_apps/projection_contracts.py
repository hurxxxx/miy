"""Fixed source-change contract; neither an ACL grant nor a generic event bus."""

from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Compatibility export; fixed cross-transport ownership lives with writer contracts.
from miy_api.domains.official_apps.writer_contracts import (
    WRITER_TRANSPORT_TABLES as WRITER_TRANSPORT_TABLES,
)

OUTBOX_TABLE = "official_projection_outbox"
RECEIPT_TABLE = "official_projection_receipts"

SOURCE_TABLE_BY_RESOURCE = {
    "docs_native_doc": "docs_native_docs",
    "pms_task": "pms_tasks",
    "meeting": "meetings",
    "file_manager_file": "file_manager_files",
}


class ProjectionOutboxError(RuntimeError):
    """Stable internal failure code; callers retain the original event ID."""


class ProjectionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_type: Literal["docs_native_doc", "pms_task", "meeting", "file_manager_file"]
    resource_id: str = Field(min_length=1, max_length=255)
    retrieval_partition_id: UUID
    change_kind: Literal["content", "visibility", "delete", "repair"]
    desired_state: Literal["active", "deleted"]
    operation: Literal["upsert", "delete", "visibility_update"]
    content_checksum: str | None = Field(default=None, max_length=128)
    visibility_checksum: str | None = Field(default=None, max_length=128)
    trace_context: dict | None = None

    @model_validator(mode="after")
    def validate_intent(self):
        if (
            not self.resource_id.strip()
            or self.resource_id != self.resource_id.strip()
            or "\x00" in self.resource_id
        ):
            raise ValueError("resource_id is invalid")
        if (self.operation == "delete") != (self.desired_state == "deleted"):
            raise ValueError("operation and desired state disagree")
        if self.change_kind == "delete" and self.desired_state != "deleted":
            raise ValueError("delete requires a tombstone")
        if self.desired_state == "deleted" and self.change_kind not in {"delete", "repair"}:
            raise ValueError("deleted requires delete or repair")
        if len(self.canonical().encode()) > 8192:
            raise ValueError("projection intent exceeds its byte bound")
        return self

    def canonical(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def digest(self) -> str:
        return sha256(self.canonical().encode()).hexdigest()
