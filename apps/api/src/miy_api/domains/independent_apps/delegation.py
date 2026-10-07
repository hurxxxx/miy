"""Narrow Workbench authority; metadata keys never become product write identities."""

from datetime import timedelta
import secrets
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from miy_api.domains.auth.access import resolve_system_roles
from miy_api.domains.auth.dependencies import AuthContext
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import hash_token
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.contracts import RegisterDefinition
from miy_api.domains.independent_apps.delegation_contracts import (
    BuildInput,
    BuildOut,
    DelegatedContext,
    DelegatedInstallation,
    DelegatedRelease,
    DelegationInput,
    DelegationSecretOut,
    PendingDeployment,
)
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppDeliveryDelegation,
    AppDeploymentRequest,
)
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord
from miy_api.domains.independent_apps.verification import trusted_release


def definition_policy(manifest: dict) -> dict:
    policy = {
        name: manifest[name]
        for name in (
            "app_id",
            "source",
            "ownership",
            "sdk_version",
            "runtime_profile",
            "requested_permissions",
        )
    }
    policy["requested_permissions"] = sorted(policy["requested_permissions"])
    return policy


def _installation(db, app_id, installation_id, context):
    item = db.get(AppInstallationRecord, installation_id, populate_existing=True)
    if item is None or item.app_id != app_id:
        service.fail("not_found", 404)
    if item.environment != "development" or not service.admitted(
        db, item, context.user, verify_current_release=False
    ):
        service.fail("forbidden")
    return item


def issue(
    db: Session, app_id: str, installation_id: str, data: DelegationInput, context: AuthContext
):
    definition = service.owned_definition(db, app_id, context)
    user, source = service._source_user(db, context.session.id)
    if user.id != context.user.id:
        service.fail("forbidden")
    installation = _installation(db, app_id, installation_id, context)
    token = "miywd_" + secrets.token_urlsafe(32)
    record = AppDeliveryDelegation(
        id=str(uuid4()),
        token_hash=hash_token(token),
        actor_user_id=user.id,
        source_session_id=source.id,
        app_id=app_id,
        installation_id=installation.id,
        environment="development",
        actions=data.actions,
        definition_policy=definition_policy(definition.manifest),
        expires_at=min(
            source.expires_at, utcnow_naive() + timedelta(seconds=data.expires_in_seconds)
        ),
    )
    db.add(record)
    service._audit(db, context, "delegation.issue", app_id)
    service._commit(db)
    return DelegationSecretOut.model_validate(
        {
            "id": record.id,
            "app_id": app_id,
            "installation_id": installation.id,
            "environment": "development",
            "actions": record.actions,
            "expires_at": record.expires_at,
            "token": token,
        }
    )


def revoke(db: Session, app_id: str, installation_id: str, grant_id: str, context: AuthContext):
    service.owned_definition(db, app_id, context)
    grant = db.get(AppDeliveryDelegation, grant_id)
    if grant is None or (grant.app_id, grant.installation_id) != (app_id, installation_id):
        service.fail("not_found", 404)
    if grant.actor_user_id != context.user.id and "platform_admin" not in context.system_roles:
        service.fail("forbidden")
    grant.revoked_at = utcnow_naive()
    service._audit(db, context, "delegation.revoke", app_id)
    service._commit(db)


def validate(
    db: Session, grant: AppDeliveryDelegation | None, action: str, app_id: str, installation_id: str
) -> AuthContext:
    if (
        grant is None
        or grant.revoked_at is not None
        or grant.expires_at <= utcnow_naive()
        or grant.environment != "development"
        or (grant.app_id, grant.installation_id) != (app_id, installation_id)
        or action not in grant.actions
    ):
        service.fail("forbidden")
    user, source = service._source_user(db, grant.source_session_id)
    if user.id != grant.actor_user_id:
        service.fail("forbidden")
    context = AuthContext(
        user=user, session=source, system_roles=frozenset(resolve_system_roles(db, user))
    )
    definition = service.owned_definition(db, app_id, context)
    if definition_policy(definition.manifest) != grant.definition_policy:
        service.fail("forbidden")
    _installation(db, app_id, installation_id, context)
    return context


def resolve(db: Session, token: str | None, action: str, app_id: str, installation_id: str):
    if not token or not token.startswith("Bearer miywd_") or len(token) > 200:
        service.fail("session_invalid", 401)
    record = db.scalar(
        select(AppDeliveryDelegation)
        .where(AppDeliveryDelegation.token_hash == hash_token(token.removeprefix("Bearer ")))
        .execution_options(populate_existing=True)
    )
    context = validate(db, record, action, app_id, installation_id)
    return record, context


def current_context(
    db: Session, grant: AppDeliveryDelegation, context: AuthContext
) -> DelegatedContext:
    definition = service.owned_definition(db, grant.app_id, context)
    installation = _installation(db, grant.app_id, grant.installation_id, context)
    pending = db.scalar(
        select(AppDeploymentRequest).where(
            AppDeploymentRequest.installation_id == installation.id,
            AppDeploymentRequest.state.in_(("queued", "running", "cleanup", "unknown")),
        )
    )
    previous = set(
        db.scalars(
            select(AppDeploymentRequest.release_id).where(
                AppDeploymentRequest.installation_id == installation.id,
                AppDeploymentRequest.state == "succeeded",
            )
        )
    )
    candidates = db.scalars(
        select(AppReleaseRecord)
        .where(
            AppReleaseRecord.app_id == grant.app_id,
            AppReleaseRecord.verified_at.is_not(None),
        )
        .order_by(AppReleaseRecord.created_at.desc(), AppReleaseRecord.id.desc())
        .limit(50)
    ).all()
    releases = [
        DelegatedRelease(
            id=item.id,
            source_revision=item.source_revision,
            artifact=item.artifact,
            definition_digest=item.definition_digest,
            verified_at=item.verified_at,
            rollback_allowed=item.id in previous,
        )
        for item in candidates
        if trusted_release(db, installation, item.id) is not None
    ]
    return DelegatedContext(
        app_id=grant.app_id,
        allowed_actions=grant.actions,
        definition=definition.manifest,
        definition_digest=definition.definition_digest,
        source_revision=definition.source_revision,
        installation=DelegatedInstallation.model_validate(installation, from_attributes=True),
        releases=releases,
        pending_deployment=(
            PendingDeployment.model_validate(pending, from_attributes=True) if pending else None
        ),
    )


def sync_definition(
    db: Session, grant: AppDeliveryDelegation, context: AuthContext, data: RegisterDefinition
):
    if definition_policy(data.definition.model_dump(mode="json")) != grant.definition_policy:
        service.fail("forbidden")
    return service.register_definition(db, data, context)


def build_out(job: AppBuildJob) -> BuildOut:
    return BuildOut.model_validate(job, from_attributes=True)


def request_build(
    db: Session, grant: AppDeliveryDelegation, context: AuthContext, data: BuildInput
) -> BuildOut:
    definition = service.owned_definition(db, grant.app_id, context)
    expected = (
        grant.app_id,
        data.source_revision,
        data.definition_digest,
        grant.id,
        grant.installation_id,
        context.user.id,
    )

    def matching(job):
        if (
            job.app_id,
            job.source_revision,
            job.definition_digest,
            job.delegation_id,
            job.installation_id,
            job.actor_user_id,
        ) != expected:
            service.fail("conflict", 409)
        return build_out(job)

    existing = db.get(AppBuildJob, str(data.request_id))
    if existing:
        return matching(existing)
    if (data.source_revision, data.definition_digest) != (
        definition.source_revision,
        definition.definition_digest,
    ):
        service.fail("conflict", 409)
    job = AppBuildJob(
        id=str(data.request_id),
        app_id=grant.app_id,
        source_revision=data.source_revision,
        definition_digest=data.definition_digest,
        delegation_id=grant.id,
        actor_user_id=context.user.id,
        source_session_id=context.session.id,
        installation_id=grant.installation_id,
    )
    db.add(job)
    service._audit(db, context, "build.request", grant.app_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(AppBuildJob, str(data.request_id))
        if existing:
            return matching(existing)
        service.fail("conflict", 409)
    return build_out(job)


def read_build(db: Session, grant: AppDeliveryDelegation, build_id: str):
    job = db.get(AppBuildJob, build_id)
    if job is None or (job.app_id, job.installation_id, job.actor_user_id) != (
        grant.app_id,
        grant.installation_id,
        grant.actor_user_id,
    ):
        service.fail("not_found", 404)
    return build_out(job)


def require_build_authority(db: Session, job: AppBuildJob):
    if job.delegation_id is None:
        return  # Explicit trusted operator build, not a delegated user request.
    grant = db.get(AppDeliveryDelegation, job.delegation_id, populate_existing=True)
    context = validate(db, grant, "build", job.app_id, job.installation_id)
    if (job.actor_user_id, job.source_session_id) != (context.user.id, context.session.id):
        service.fail("forbidden")
