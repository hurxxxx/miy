"""Operator-owned limits for development workspaces; never manifest fields."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from miy_api.core.app_origins import exact_origin
from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget, overlap


class WorkspaceOriginSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    origin: str
    port: int = Field(strict=True, ge=1024, le=65535)

    @field_validator("origin")
    @classmethod
    def canonical_origin(cls, value):
        origin = exact_origin(value)
        if not origin.startswith("https://"):
            raise ValueError("Managed workspace slots require a prepared HTTPS ingress")
        return origin

    @field_validator("port")
    @classmethod
    def available_port(cls, value):
        return IndependentDeliveryTarget.reserved_service_port(value)


class IndependentWorkspaceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    repository_root: Path
    repository: str
    worktree_root: Path
    work_root: Path
    state_root: Path
    toolchain_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    ingress_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    platform_origin: str
    platform_api_origin: str | None = None
    origins: list[WorkspaceOriginSlot] = Field(min_length=1, max_length=4)

    @field_validator("repository_root", "worktree_root", "work_root", "state_root")
    @classmethod
    def canonical_root(cls, value):
        return IndependentDeliveryTarget.canonical_root(value)

    @field_validator("repository")
    @classmethod
    def repository_identity(cls, value):
        from miy_api.domains.independent_apps.contracts import Source

        return Source(repository=value).repository

    @field_validator("platform_origin", "platform_api_origin")
    @classmethod
    def canonical_origin(cls, value):
        return exact_origin(value) if value is not None else None

    @model_validator(mode="after")
    def disjoint(self):
        paths = (self.repository_root, self.worktree_root, self.work_root, self.state_root)
        if any(overlap(a, b) for i, a in enumerate(paths) for b in paths[i + 1 :]):
            raise ValueError("Workspace repository, sources, scratch and state must be disjoint")
        origins, ports = [s.origin for s in self.origins], [s.port for s in self.origins]
        if len(set(origins)) != len(origins) or len(set(ports)) != len(ports):
            raise ValueError("Workspace origins and ports must be distinct")
        if any(s.origin in {self.platform_origin, self.platform_api_origin} for s in self.origins):
            raise ValueError("Workspace app origins must differ from the platform")
        return self

    def identity(self):
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
