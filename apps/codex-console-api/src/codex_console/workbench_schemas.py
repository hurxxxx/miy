from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .schemas import GitStatusOut, Input

AppIdPattern = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class AppDescriptor(BaseModel):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(max_length=200)
    summary: str = Field(max_length=1000)
    capabilities: list[str] = Field(max_length=20)
    source_paths: list[str] = Field(max_length=20)
    release_unit: Literal["miy-app", "miy-workbench"]
    route_base: str = Field(max_length=200)
    preview_url: str | None = None


class ProjectInput(Input):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    reuse_decision: Literal["new", "extend"]
    reuse_notes: str = Field(min_length=1, max_length=4000)


class ProjectOut(ProjectInput):
    id: str
    created_at: datetime


class CatalogOut(BaseModel):
    items: list[AppDescriptor]
    projects: list[ProjectOut]
    source_revision: str | None
    source_dirty: bool
    checked_at: datetime


class RuntimeApp(BaseModel):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(max_length=200)
    enabled: bool
    release_unit: Literal["miy-app", "miy-workbench"]
    installed_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    runtime_ai: bool


class RuntimeCatalog(BaseModel):
    schema_version: Literal[1]
    items: list[RuntimeApp] = Field(max_length=200)
    total: int = Field(ge=0, le=200)
    page: Literal[1]
    page_size: Literal[200]
    generated_at: datetime


class RuntimeOut(BaseModel):
    state: Literal["ready", "unconfigured", "unavailable", "unsupported", "denied"]
    checked_at: datetime | None = None
    stale: bool = True
    items: list[RuntimeApp] = []


class RuntimeUsage(BaseModel):
    schema_version: Literal[1]
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    app_opens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    llm_errors: int = Field(ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    unreported_calls: int = Field(ge=0)
    complete: bool
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    cost_basis: Literal["not_reported", "reported"]
    generated_at: datetime


class BudgetInput(Input):
    development_tokens: int | None = Field(default=None, ge=1, le=10**12)
    runtime_tokens: int | None = Field(default=None, ge=1, le=10**12)
    amount_minor: int | None = Field(default=None, ge=1, le=10**12)
    currency: str = Field(default="KRW", pattern=r"^[A-Z]{3}$")
    version: int = Field(default=0, ge=0)


class UsageOut(BaseModel):
    month: str
    development_tokens: int | None
    development_tasks: int
    unreported_tasks: int
    development_amount_minor: None = None
    runtime: RuntimeUsage | None = None
    runtime_state: str
    runtime_checked_at: datetime | None = None
    stale: bool = True
    budget: BudgetInput
    alerts: list[str]


class MaintenanceInput(Input):
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=4000)
    owner: str = Field(default="", max_length=120)
    due_on: date | None = None
    state: Literal["open", "planned", "cancelled"] = "open"
    target_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    task_id: UUID | None = None
    version: int = Field(default=0, ge=0)


class MaintenanceOut(MaintenanceInput):
    id: str
    app_id: str
    updated_at: datetime
    state: Literal["open", "planned", "cancelled", "verified"]
    verification: dict | None = None


class VerifyMaintenance(Input):
    version: int = Field(ge=1)


class GitLabItem(BaseModel):
    id: int | None = None
    name: str
    revision: str | None = None
    status: str | None = None
    url: str | None = None


class GitLabOut(BaseModel):
    state: str
    checked_at: datetime | None = None
    stale: bool = True
    branches: list[GitLabItem] = []
    merge_requests: list[GitLabItem] = []
    pipelines: list[GitLabItem] = []


class CommitOut(BaseModel):
    revision: str
    subject: str


class ReleaseIdentity(BaseModel):
    source_revision: str
    source_dirty: bool
    digest: str


class PlatformOut(BaseModel):
    git: GitStatusOut | None
    commits: list[CommitOut]
    worktrees: list[str]
    gitlab: GitLabOut
    workbench_release: ReleaseIdentity | None = None
