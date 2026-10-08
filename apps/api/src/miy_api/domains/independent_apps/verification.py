"""Read-only trusted evidence predicate shared by admission and delivery."""

from sqlalchemy.orm import Session

from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord


def trusted_release(
    db: Session, installation: AppInstallationRecord, release_id: str
) -> AppReleaseRecord | None:
    release = db.get(AppReleaseRecord, release_id, populate_existing=True)
    proof = (
        db.get(AppBuildVerification, release.verification_id, populate_existing=True)
        if release and release.verification_id
        else None
    )
    if (
        release is None
        or release.app_id != installation.app_id
        or proof is None
        or proof.revoked_at is not None
        or release.verified_at is None
        or proof.target_environment != installation.environment
        or (proof.app_id, proof.source_revision, proof.definition_digest, proof.artifact_digest)
        != (release.app_id, release.source_revision, release.definition_digest, release.artifact)
        or not proof.checks
        or any(type(code) is not int or code != 0 for code in proof.checks.values())
    ):
        return None
    return release
