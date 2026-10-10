"""Core-only bindings for the optional independent-app delivery consumer."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from miy_api.core.app_origins import exact_origin


class IndependentDeliveryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    installation_id: UUID
    environment: Literal["development", "production"] = "development"
    source_root: Path
    work_root: Path
    state_root: Path
    toolchain_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    ingress_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    platform_origin: str
    platform_api_origin: str | None = None
    app_origin: str | None = None
    loopback_port: int | None = Field(default=None, strict=True, ge=1024, le=65535)

    @field_validator("source_root", "work_root", "state_root")
    @classmethod
    def canonical_root(cls, value: Path) -> Path:
        if not value.is_absolute() or value.resolve() != value or value == Path("/"):
            raise ValueError("Delivery roots must be canonical absolute paths without symlinks")
        return value

    @field_validator("loopback_port")
    @classmethod
    def reserved_service_port(cls, value: int | None) -> int | None:
        if value in {18779, 18780, 18781}:
            raise ValueError("Delivery cannot use a reserved first-party service port")
        return value

    @field_validator("platform_origin", "platform_api_origin", "app_origin")
    @classmethod
    def origin(cls, value: str | None) -> str | None:
        return exact_origin(value) if value is not None else None

    @model_validator(mode="after")
    def public_ingress(self) -> "IndependentDeliveryTarget":
        if (
            self.environment == "production"
            or self.app_origin is not None
            or self.loopback_port is not None
        ):
            if (
                not self.app_origin
                or not self.app_origin.startswith("https://")
                or self.loopback_port is None
            ):
                raise ValueError(
                    "Public delivery requires an HTTPS app origin and a fixed loopback port"
                )
            if self.app_origin in {self.platform_origin, self.platform_api_origin}:
                raise ValueError("Public apps require an origin separate from the platform")
        return self


def overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_targets(
    targets: list[IndependentDeliveryTarget], *, platform_root: Path, platform_origins: list[str]
) -> list[IndependentDeliveryTarget]:
    """Also run before each poll so a replaced path cannot inherit an old binding."""
    ids = [target.installation_id for target in targets]
    if len(ids) != len(set(ids)):
        raise ValueError("Each delivery installation needs exactly one operator binding")
    public = [target for target in targets if target.app_origin is not None]
    for values in (
        [target.app_origin for target in public],
        [target.loopback_port for target in public],
    ):
        if len(values) != len(set(values)):
            raise ValueError("Public apps require distinct HTTPS origins and loopback ports")
    for target in targets:
        for path in (target.source_root, target.work_root, target.state_root):
            IndependentDeliveryTarget.canonical_root(path)
        if overlap(target.source_root, platform_root):
            raise ValueError("App source roots must be outside the platform checkout")
        if target.platform_origin not in platform_origins:
            raise ValueError("Delivery browser origins must be in the platform origin allowlist")
        if target.app_origin is not None and target.app_origin in platform_origins:
            raise ValueError("Public app origins cannot be platform origins")
        for other in targets:
            if any(
                overlap(left, right)
                for left, right in (
                    (target.source_root, other.work_root),
                    (target.source_root, other.state_root),
                    (target.work_root, other.state_root),
                )
            ):
                raise ValueError("App sources, build scratch and runtime state must be disjoint")
            if target.installation_id != other.installation_id and any(
                overlap(left, right)
                for left, right in (
                    (target.work_root, other.work_root),
                    (target.state_root, other.state_root),
                )
            ):
                raise ValueError("Each installation needs separate build scratch and runtime state")
    return targets
