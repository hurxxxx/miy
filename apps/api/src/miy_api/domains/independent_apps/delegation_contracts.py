from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from miy_api.domains.independent_apps.contracts import AppDefinition, Contract, Digest, Revision

Action = Literal["read", "sync", "build", "deploy", "rollback"]


class DelegationInput(Contract):
    actions: list[Action] = Field(min_length=1, max_length=5)
    expires_in_seconds: int = Field(default=86400, ge=60, le=86400)

    @field_validator("actions")
    @classmethod
    def unique_actions(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Actions must be unique")
        return sorted(value)


class DelegationOut(Contract):
    id: str
    app_id: str
    installation_id: str
    environment: Literal["development"]
    actions: list[Action]
    expires_at: datetime


class DelegationSecretOut(DelegationOut):
    token: str


class BuildInput(Contract):
    request_id: UUID
    source_revision: Revision
    definition_digest: Digest


class BuildOut(Contract):
    id: str
    app_id: str
    source_revision: Revision
    state: Literal["queued", "running", "succeeded", "failed", "unknown"]
    failure_code: str | None
    release_id: str | None
    created_at: datetime
    updated_at: datetime


class DelegatedInstallation(Contract):
    id: str
    environment: Literal["development"]
    origin: str
    generation: int
    release_id: str | None
    state: str
    enabled: bool


class DelegatedRelease(Contract):
    id: str
    source_revision: Revision
    artifact: str
    definition_digest: Digest
    verified_at: datetime
    rollback_allowed: bool


class PendingDeployment(Contract):
    id: str
    release_id: str
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "unknown"]


class DelegatedContext(Contract):
    app_id: str
    allowed_actions: list[Action]
    definition: AppDefinition
    definition_digest: Digest
    source_revision: Revision
    installation: DelegatedInstallation
    releases: list[DelegatedRelease]
    pending_deployment: PendingDeployment | None = None
