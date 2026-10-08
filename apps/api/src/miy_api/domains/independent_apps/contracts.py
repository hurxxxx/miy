"""Framework-independent wire contracts; app input cannot configure the host."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from miy_api.core.app_origins import exact_origin

AppId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
Revision = Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
Permission = Literal["identity:read", "data:read", "data:write", "files:read-selected"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("expires_at", "created_at", "updated_at", "verified_at", check_fields=False)
    def utc_timestamps(self, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Display(Contract):
    name: str = Field(min_length=1, max_length=200)
    translations: dict[str, str] = Field(default_factory=dict, max_length=20)
    icon: str = Field(default="app-window", pattern=r"^[a-z][a-z0-9-]{0,63}$")

    @field_validator("translations")
    @classmethod
    def bounded_translations(cls, values: dict[str, str]) -> dict[str, str]:
        if any(
            len(locale) > 35 or not label or len(label) > 200 for locale, label in values.items()
        ):
            raise ValueError("Invalid locale or translated name")
        return values


class Source(Contract):
    repository: str = Field(min_length=1, max_length=500)
    directory: str = Field(default=".", max_length=200)

    @field_validator("repository")
    @classmethod
    def repository_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Use a credential-free HTTPS repository URL")
        return value

    @field_validator("directory")
    @classmethod
    def relative_directory(cls, value: str) -> str:
        if value != "." and (
            not value
            or value.startswith("/")
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Use a repository-relative directory")
        return value


class Entrypoints(Contract):
    ui: str = "/"
    api: str = "/api"
    health: str = "/healthz"

    @field_validator("ui", "api", "health")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or value.rstrip("/") == "/__miy_release"
            or len(value) > 200
            or any(char in value for char in ("?", "#", "\\", "%"))
            or any(part in {".", ".."} for part in value.split("/"))
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Use a plain absolute path on the app origin")
        return value


class AppDefinition(Contract):
    schema_version: Literal[1] = 1
    app_id: AppId
    display: Display
    source: Source
    ownership: Literal["personal", "official"] = "personal"
    sdk_version: Literal[1] = 1
    runtime_profile: Literal["web-api-v1", "web-api-postgres-v1"] = "web-api-v1"
    entrypoints: Entrypoints = Field(default_factory=Entrypoints)
    requested_permissions: list[Permission] = Field(default_factory=list, max_length=4)

    @field_validator("schema_version", "sdk_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        # Literal[1] alone treats True as 1, unlike the published integer schema.
        if isinstance(value, bool):
            raise ValueError("Version must be an integer")
        return value

    @model_validator(mode="after")
    def data_permissions_require_profile(self) -> AppDefinition:
        if self.runtime_profile != "web-api-postgres-v1" and any(
            permission.startswith("data:") for permission in self.requested_permissions
        ):
            raise ValueError("Data permissions require the PostgreSQL runtime profile")
        if len(set(self.requested_permissions)) != len(self.requested_permissions):
            raise ValueError("Permissions must be unique")
        return self

    def content_digest(self) -> str:
        data = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(data.encode()).hexdigest()


class RegisterDefinition(Contract):
    definition: AppDefinition
    source_revision: Revision
    expected_digest: Digest | None = None
    expected_source_revision: Revision | None = None


class DefinitionOut(Contract):
    definition: AppDefinition
    definition_digest: Digest
    source_revision: Revision
    owner_user_id: str
    updated_at: datetime


class ReleaseCandidate(Contract):
    definition_digest: Digest
    source_revision: Revision
    artifact: str = Field(
        pattern=r"^(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[a-f0-9]{64})$",
        max_length=500,
    )


class ReleaseOut(ReleaseCandidate):
    id: str
    app_id: AppId
    created_at: datetime
    verification_id: str | None
    verified_at: datetime | None


class InstallationInput(Contract):
    environment: Literal["development", "production"]
    origin: str = Field(max_length=300)
    enabled: bool = False
    audience: Literal["selected", "all"] = "selected"
    user_ids: list[str] = Field(default_factory=list, max_length=1000)
    group_ids: list[str] = Field(default_factory=list, max_length=1000)
    granted_permissions: list[Permission] = Field(default_factory=list, max_length=4)

    _origin = field_validator("origin")(exact_origin)

    @model_validator(mode="after")
    def no_development_broadcast(self) -> InstallationInput:
        if self.environment == "development" and (self.audience != "selected" or self.group_ids):
            raise ValueError("Development installations use explicit individual access")
        return self


class InstallationOut(InstallationInput):
    id: str
    app_id: AppId
    release_id: str | None
    state: Literal["configured", "ready", "disabled"]
    generation: int


class InstallationSummary(Contract):
    id: str
    app_id: str
    environment: str
    origin: str
    enabled: bool
    release_id: str | None
    state: str
    generation: int
    granted_permissions: list[str]
    launchable: bool
    ui_entrypoint: str | None


class LaunchInput(Contract):
    installation_id: str = Field(min_length=1, max_length=36)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class LaunchOut(Contract):
    code: str
    expires_at: datetime
    app_origin: str


class ExchangeInput(Contract):
    installation_id: str = Field(min_length=1, max_length=36)
    code: str = Field(min_length=40, max_length=128)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


class AppSessionOut(Contract):
    token: str
    expires_at: datetime
    installation_id: str
    app_id: AppId
    environment: Literal["development", "production"]
    audience: str
    permissions: list[Permission]


class AppIdentityOut(Contract):
    user_id: str
    display_name: str
    app_id: AppId
    installation_id: str
    environment: Literal["development", "production"]
    audience: str
    permissions: list[Permission]
    expires_at: datetime
