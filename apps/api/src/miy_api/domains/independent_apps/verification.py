"""Read-only trusted evidence predicate shared by admission and delivery."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.domains.independent_apps.delivery_models import (
    AppBuildVerification,
    AppDeploymentRequest,
)
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord


def verified_artifact(
    db: Session, app_id: str, release_id: str, *, target_environment: str
) -> AppReleaseRecord | None:
    release = db.get(AppReleaseRecord, release_id, populate_existing=True)
    proof = (
        db.get(AppBuildVerification, release.verification_id, populate_existing=True)
        if release and release.verification_id
        else None
    )
    if (
        release is None
        or release.app_id != app_id
        or proof is None
        or proof.revoked_at is not None
        or release.verified_at is None
        or proof.target_environment != target_environment
        or (proof.app_id, proof.source_revision, proof.definition_digest, proof.artifact_digest)
        != (release.app_id, release.source_revision, release.definition_digest, release.artifact)
        or not proof.checks
        or any(type(code) is not int or code != 0 for code in proof.checks.values())
    ):
        return None
    return release


def promotable_release(
    db: Session, installation: AppInstallationRecord, release_id: str
) -> AppReleaseRecord | None:
    """Promote exact observed development bytes; never relabel their build proof."""
    release = verified_artifact(
        db, installation.app_id, release_id, target_environment="development"
    )
    if (
        release is None
        or not release.artifact.startswith("sha256:")
        or release.definition_snapshot.get("ownership") != "personal"
    ):
        return None
    observed = db.scalar(
        select(AppDeploymentRequest.id)
        .join(
            AppInstallationRecord,
            AppInstallationRecord.id == AppDeploymentRequest.installation_id,
        )
        .where(
            AppInstallationRecord.app_id == installation.app_id,
            AppInstallationRecord.environment == "development",
            AppDeploymentRequest.release_id == release.id,
            AppDeploymentRequest.state == "succeeded",
            AppDeploymentRequest.observed_image_id == release.artifact,
        )
        .limit(1)
    )
    return release if observed is not None else None


def trusted_release(
    db: Session, installation: AppInstallationRecord, release_id: str
) -> AppReleaseRecord | None:
    if installation.environment != "production":
        return verified_artifact(
            db, installation.app_id, release_id, target_environment=installation.environment
        )
    # Preserve the existing explicit production-proof contract used by owned
    # official adapters. Personal promotion never manufactures this proof.
    production_release = verified_artifact(
        db, installation.app_id, release_id, target_environment="production"
    )
    if production_release is not None:
        return production_release
    release = promotable_release(db, installation, release_id)
    receipt = (
        db.get(AppDeploymentRequest, installation.runtime_ref, populate_existing=True)
        if installation.runtime_ref
        else None
    )
    if (
        release is None
        or installation.state != "ready"
        or installation.release_id != release_id
        or receipt is None
        or receipt.delegation_id is not None
        or receipt.installation_id != installation.id
        or receipt.release_id != release_id
        or receipt.state not in {"cleanup", "succeeded", "unknown"}
        or receipt.observed_image_id != release.artifact
        or not isinstance(receipt.runtime_config, dict)
    ):
        return None
    expected = {
        "request_id": receipt.id,
        "installation_id": installation.id,
        "app_id": installation.app_id,
        "image_id": release.artifact,
        "origin": installation.origin,
        "health_path": release.definition_snapshot["entrypoints"]["health"],
        "environment": "production",
        "runtime_profile": release.definition_snapshot["runtime_profile"],
    }
    if (
        any(receipt.runtime_config.get(key) != value for key, value in expected.items())
        or type(receipt.runtime_config.get("loopback_port")) is not int
        or not 1024 <= receipt.runtime_config["loopback_port"] <= 65535
        or not isinstance(receipt.runtime_config.get("operator_binding_digest"), str)
        or not re.fullmatch("[a-f0-9]{64}", receipt.runtime_config["operator_binding_digest"])
    ):
        return None
    return release
