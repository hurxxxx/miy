"""Create-only personal registration; input cannot widen the fixed installation policy."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from miy_api.core.app_origins import exact_origin
from miy_api.domains.independent_apps.contracts import (
    AppDefinition,
    AppId,
    Contract,
    Digest,
    Permission,
    Revision,
)


class BootstrapInput(Contract):
    operation_id: UUID
    definition: AppDefinition
    source_revision: Revision
    origin: str = Field(max_length=300)
    granted_permissions: list[Permission] = Field(default_factory=list, max_length=4)

    _origin = field_validator("origin")(exact_origin)

    @field_validator("definition")
    @classmethod
    def personal_definition(cls, value: AppDefinition) -> AppDefinition:
        if value.ownership != "personal":
            raise ValueError("Initial registration supports personal apps only")
        # AppDefinition digest treats its arrays as ordered. Keep exactly the
        # registered manifest representation consumed by trusted builds.
        return value

    @field_validator("granted_permissions")
    @classmethod
    def unique_permissions(cls, value: list[Permission]) -> list[Permission]:
        if len(set(value)) != len(value):
            raise ValueError("Permissions must be unique")
        return sorted(value)


class BootstrapReceipt(Contract):
    operation_id: UUID
    app_id: AppId
    installation_id: UUID
    definition_digest: Digest
    source_revision: Revision
    created_at: datetime
