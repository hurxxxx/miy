from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .app_sources import APP_ID_PATTERN
from .schemas import GitStatusOut, Input

AppIdPattern = APP_ID_PATTERN


class AppDescriptor(BaseModel):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(max_length=200)
    title_translations: dict[str, str] = Field(default_factory=dict)
    icon_key: str = Field(default="layout-grid", max_length=100)
    summary: str = Field(default="", max_length=1000)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    source_paths: list[str] = Field(default_factory=list, max_length=20)
    release_unit: str | None = Field(default=None, max_length=120)
    route_base: str = Field(max_length=200)
    preview_url: str | None = None
    source_status: Literal["ready", "unconfigured", "missing", "invalid"] = "unconfigured"
    discovery: Literal["checkout", "runtime", "source"] = "checkout"
    source_root: str | None = None
    source_version: int = 0
    execution_status: Literal["platform", "configured", "unconfigured"] = "unconfigured"
    preview_status: Literal["configured", "unconfigured"] = "unconfigured"
    deployment_status: Literal["configured", "unconfigured"] = "unconfigured"
    limitations: list[
        Literal[
            "source_not_configured",
            "source_missing",
            "source_invalid",
            "executor_not_configured",
            "preview_not_configured",
            "release_not_configured",
        ]
    ] = Field(default_factory=list)


class SourceBindingInput(Input):
    repository_root: str = Field(min_length=1, max_length=4096)
    version: int = Field(default=0, ge=0)


class ProjectExecutionReadinessOut(BaseModel):
    """Connection metadata at checked_at; not sandbox or Task authorization."""

    project_id: str
    app_id: str | None
    source_version: int | None = Field(ge=1)
    state: Literal["reachable", "unconfigured", "unavailable", "changed", "unsupported", "denied"]
    failure_code: str | None = Field(max_length=80)
    checked_at: datetime


class SourceCreationRoot(BaseModel):
    id: str
    label: str


class SourceStarter(BaseModel):
    id: Literal["basic", "private-notes"]
    name: str
    runtime_profile: str
    bundle_digest: str
    sdk_version: str


class SourceSetupOptions(BaseModel):
    roots: list[SourceCreationRoot]
    templates: list[SourceStarter]


class SourceSetupInput(Input):
    operation_id: UUID
    repository: str = Field(min_length=1, max_length=2048, pattern=r"^https://")
    root_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_id: Literal["basic", "private-notes"]
    expected_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SourceSetupOut(BaseModel):
    operation_id: str
    project_id: str
    app_id: str
    root_id: str
    template_id: Literal["basic", "private-notes"]
    repository: str
    bundle_digest: str
    state: Literal["preparing", "ready", "failed", "conflict"]
    source_root: str | None
    source_revision: str | None
    source_version: int | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class SourceSetupStatus(BaseModel):
    setup: SourceSetupOut | None


class SourceRegistrationDraftOut(BaseModel):
    schema_version: Literal[1] = 1
    project_id: UUID
    binding_version: int = Field(ge=1)
    app_id: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_manifest_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    definition: dict


class SourceRegistrationStatusOut(BaseModel):
    project_id: UUID
    app_id: str
    binding_version: int = Field(ge=1)
    state: Literal["unregistered", "matching", "different", "collision", "unknown"]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    platform_state: Literal["ready", "unconfigured", "unavailable", "unsupported", "denied"]
    platform_checked_at: datetime | None
    registered_source_revision: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    registered_definition_digest: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    definition_matches: bool | None
    revision_matches: bool | None


class ProjectFields(Input):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    reuse_decision: Literal["new", "extend"]
    reuse_notes: str = Field(min_length=1, max_length=4000)


class ProjectInput(ProjectFields):
    @model_validator(mode="after")
    def independent_app_id(self):
        if self.reuse_decision == "new":
            from jsonschema.exceptions import ValidationError

            from .app_sources import validator

            contract = validator()
            try:
                contract.evolve(schema=contract.schema["properties"]["app_id"]).validate(
                    self.app_id
                )
            except ValidationError:
                raise ValueError(
                    "New projects require a valid independent app identifier"
                ) from None
        return self


class ProjectOut(ProjectFields):
    id: str
    created_at: datetime


class CatalogOut(BaseModel):
    registration_authorization_available: bool = False
    items: list[AppDescriptor]
    projects: list[ProjectOut]
    source_revision: str | None
    source_dirty: bool
    checked_at: datetime


class RuntimeApp(BaseModel):
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    title: str = Field(max_length=200)
    enabled: bool
    release_unit: str | None = None
    installed_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    registered_source_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    runtime_ai: bool
    title_translations: dict[str, str] = Field(default_factory=dict)
    icon_key: str = "layout-grid"
    source_repository: str | None = None
    source_directory: str | None = None
    definition_digest: str | None = None


class RuntimeCatalog(BaseModel):
    schema_version: Literal[1]
    registration_status_version: int | None = Field(default=None, strict=True, ge=1)
    items: list[RuntimeApp] = Field(max_length=200)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    catalog_revision: str | None = None
    generated_at: datetime


class RuntimeOut(BaseModel):
    state: Literal["ready", "unconfigured", "unavailable", "unsupported", "denied"]
    checked_at: datetime | None = None
    stale: bool = True
    items: list[RuntimeApp] = []
    catalog_revision: str | None = None
    registration_status_version: int | None = None


class DeploymentObservation(BaseModel):
    request_id: UUID
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "succeeded", "failed", "unknown"]
    failure_code: str | None = Field(default=None, max_length=80)
    updated_at: datetime


class InstallationObservation(BaseModel):
    id: UUID
    environment: Literal["development", "production"]
    origin: str = Field(max_length=300)
    enabled: bool
    state: str = Field(max_length=32)
    generation: int = Field(ge=1)
    release_id: UUID | None
    source_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    artifact_digest: str | None = Field(default=None, max_length=500)
    deployment: DeploymentObservation | None
    delivery_configured: bool = False

    @field_validator("origin")
    @classmethod
    def origin_boundary(cls, value):
        from .config import Settings

        if "\\" in value or any(char.isspace() for char in value):
            raise ValueError("Invalid app origin")
        return Settings.validate_origin(value)


class InstallationCatalog(BaseModel):
    schema_version: Literal[1]
    app_id: str = Field(pattern=AppIdPattern, max_length=80)
    items: list[InstallationObservation] = Field(max_length=200)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    catalog_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime


class InstallationsOut(BaseModel):
    state: Literal["ready", "unconfigured", "unavailable", "unsupported", "denied"]
    checked_at: datetime | None = None
    stale: bool = True
    items: list[InstallationObservation] = []


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
