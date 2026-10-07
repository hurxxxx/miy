from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from miy_api.domains.independent_apps.contracts import Contract


class DeploymentInput(Contract):
    request_id: UUID
    installation_id: UUID
    release_id: UUID
    action: Literal["deploy", "rollback"] = "deploy"
    expected_generation: int = Field(ge=1)
    expected_release_id: UUID | None = None


class DeploymentOut(Contract):
    id: str
    installation_id: str
    release_id: str
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "succeeded", "failed", "unknown"]
    failure_code: str | None
    previous_release_id: str | None
    observed_image_id: str | None
    created_at: datetime
    updated_at: datetime
