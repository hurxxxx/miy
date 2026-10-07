"""Core-only bindings for the optional independent-app delivery consumer."""

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from miy_api.core.app_origins import exact_origin


class IndependentDeliveryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    app_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    installation_id: UUID
    source_root: Path
    work_root: Path
    state_root: Path
    toolchain_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    ingress_image: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    platform_origin: str
    platform_api_origin: str | None = None

    @field_validator("source_root", "work_root", "state_root")
    @classmethod
    def canonical_root(cls, value: Path) -> Path:
        if not value.is_absolute() or value.resolve() != value or value == Path("/"):
            raise ValueError("Delivery roots must be canonical absolute paths without symlinks")
        return value

    @field_validator("platform_origin", "platform_api_origin")
    @classmethod
    def origin(cls, value: str | None) -> str | None:
        return exact_origin(value) if value is not None else None


def overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_targets(
    targets: list[IndependentDeliveryTarget], *, platform_root: Path, platform_origins: list[str]
) -> list[IndependentDeliveryTarget]:
    """Also run before each poll so a replaced path cannot inherit an old binding."""
    ids = [target.installation_id for target in targets]
    if len(ids) != len(set(ids)):
        raise ValueError("Each delivery installation needs exactly one operator binding")
    for target in targets:
        for path in (target.source_root, target.work_root, target.state_root):
            IndependentDeliveryTarget.canonical_root(path)
        if overlap(target.source_root, platform_root):
            raise ValueError("App source roots must be outside the platform checkout")
        if target.platform_origin not in platform_origins:
            raise ValueError("Delivery browser origins must be in the platform origin allowlist")
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
    return targets
