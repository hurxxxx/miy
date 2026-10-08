"""Separate versioned authority for one personal app's initial registration."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_serializer, field_validator, model_validator

from miy_api.core.app_origins import exact_origin
from miy_api.core.registration_audience import registration_audience
from miy_api.domains.independent_apps.contracts import AppId, Contract, Permission


class RegistrationPolicy(Contract):
    app_id: AppId
    origin: str = Field(max_length=300)
    runtime_profile: Literal["web-api-v1", "web-api-postgres-v1"]
    requested_permissions: list[Permission] = Field(max_length=4)

    _origin = field_validator("origin")(exact_origin)

    @field_validator("requested_permissions")
    @classmethod
    def permission_set(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Permissions must be unique")
        return sorted(values)

    @model_validator(mode="after")
    def profile_permissions(self):
        if self.runtime_profile != "web-api-postgres-v1" and any(
            permission.startswith("data:") for permission in self.requested_permissions
        ):
            raise ValueError("Data permissions require the data runtime profile")
        return self


class RegistrationVersion(Contract):
    schema_version: Literal[1]

    @field_validator("schema_version", mode="before")
    @classmethod
    def numeric_version(cls, value):
        if isinstance(value, bool):
            raise ValueError("Version must be numeric")
        return value


class RegistrationAuthorizationInput(RegistrationVersion):
    request_id: UUID
    operation_id: UUID
    audience: str = Field(max_length=500)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    policy: RegistrationPolicy

    _audience = field_validator("audience")(registration_audience)


class RegistrationAuthorizationOut(RegistrationVersion):
    id: UUID
    request_id: UUID
    operation_id: UUID
    actor_user_id: UUID
    audience: str
    policy: RegistrationPolicy
    expires_at: datetime


class RegistrationCodeOut(RegistrationAuthorizationOut):
    callback_url: str
    code: str = Field(repr=False)
    code_expires_at: datetime

    @field_serializer("code_expires_at")
    def code_timestamp(self, value):
        return self.utc_timestamps(value)


class RegistrationExchangeInput(RegistrationVersion):
    request_id: UUID
    audience: str = Field(max_length=500)
    code: str = Field(min_length=1, max_length=100, repr=False)
    code_verifier: str = Field(min_length=43, max_length=128, repr=False)

    _audience = field_validator("audience")(registration_audience)


class RegistrationTokenOut(RegistrationAuthorizationOut):
    token: str = Field(repr=False)
