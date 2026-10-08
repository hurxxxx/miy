"""Owner consent for an existing, unreleased private development installation."""

from typing import Literal

from pydantic import Field, field_validator

from miy_api.domains.independent_apps.contracts import (
    AppId,
    Contract,
    Digest,
    Permission,
    Revision,
)

UnavailableReason = Literal[
    "already_deployed",
    "delivery_in_progress",
    "build_in_progress",
    "already_verified",
    "company_disabled",
    "origin_configuration_required",
    "invalid_origin",
]


class OwnerPreviewPatch(Contract):
    expected_generation: int = Field(ge=1, strict=True)
    expected_definition_digest: Digest
    expected_source_revision: Revision
    enabled: bool = Field(strict=True)
    granted_permissions: list[Permission] = Field(max_length=4)

    @field_validator("granted_permissions")
    @classmethod
    def unique_permissions(cls, values: list[Permission]) -> list[Permission]:
        if len(values) != len(set(values)):
            raise ValueError("Duplicate permission")
        return sorted(values)


class OwnerPreviewOut(Contract):
    schema_version: Literal[1] = 1
    app_id: AppId
    installation_id: str
    owner_user_id: str
    display_name: str
    origin: str
    generation: int
    definition_digest: Digest
    source_revision: Revision
    runtime_profile: Literal["web-api-v1", "web-api-postgres-v1"]
    requested_permissions: list[Permission]
    granted_permissions: list[Permission]
    enabled: bool
    company_enabled: bool
    can_configure: bool
    unavailable_reason: UnavailableReason | None
