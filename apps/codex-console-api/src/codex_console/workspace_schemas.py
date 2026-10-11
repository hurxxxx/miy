"""Public workspace actions contain intent and versions, never execution credentials."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .schemas import Input


class WorkspaceCreate(Input):
    operation_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    profile: Literal["app"] = "app"
    auto_refresh: bool = True


class WorkspaceAction(Input):
    operation_id: UUID
    expected_version: int = Field(ge=1)


class WorkspaceOperationOut(BaseModel):
    operation_id: str
    kind: str
    state: str
    source_revision: str | None = None
    failure_code: str | None = None
    retryable: bool = False
    unknown: bool = False
    continuable: bool = False
    created_at: datetime
    updated_at: datetime


class WorkspacePreviewOut(BaseModel):
    state: str = "unconfigured"
    portal_url: str | None = None
    installation_id: str | None = None
    source_revision: str | None = None
    runtime_revision: str | None = None
    failure_code: str | None = None


class WorkspaceIntegrationOut(BaseModel):
    state: str = "not_requested"
    mr_url: str | None = None
    mr_id: int | None = None
    source_revision: str | None = None
    merged_revision: str | None = None
    dev_runtime_revision: str | None = None
    failure_code: str | None = None


class WorkspaceCleanupOut(BaseModel):
    state: str = "not_requested"
    failure_code: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    project_id: str
    app_id: str
    title: str
    profile: str
    state: str
    version: int
    admission_open: bool
    auto_refresh: bool
    branch: str
    base_revision: str | None
    source_revision: str | None
    preview: WorkspacePreviewOut
    integration: WorkspaceIntegrationOut
    cleanup: WorkspaceCleanupOut
    failure_code: str | None
    operations: list[WorkspaceOperationOut]
    created_at: datetime
    updated_at: datetime


class WorkspaceList(BaseModel):
    available: bool
    items: list[WorkspaceOut]
