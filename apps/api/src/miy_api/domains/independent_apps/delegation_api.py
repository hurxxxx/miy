"""Owner login mints narrow tokens; delegated calls only create durable intents."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import delegation, delivery, service
from miy_api.domains.independent_apps.contracts import DefinitionOut, RegisterDefinition
from miy_api.domains.independent_apps.delegation_contracts import (
    BuildInput,
    BuildOut,
    DelegatedContext,
    DelegationInput,
    DelegationOut,
    DelegationSecretOut,
)
from miy_api.domains.independent_apps.delivery_contracts import DeploymentInput, DeploymentOut
from miy_api.domains.independent_apps.delivery_models import (
    AppDeliveryDelegation,
    AppDeploymentRequest,
)

router = APIRouter(tags=["independent-app-delivery"])
_OWNER = "/{app_id}/installations/{installation_id}/delegations"
_DELEGATED = "/delegated/{app_id}/installations/{installation_id}"


@router.post(_OWNER, response_model=DelegationSecretOut, status_code=201)
def issue(
    app_id: str,
    installation_id: UUID,
    data: DelegationInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return delegation.issue(db, app_id, str(installation_id), data, context)


@router.get(_OWNER, response_model=list[DelegationOut])
def issued(
    app_id: str,
    installation_id: UUID,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    service.owned_definition(db, app_id, context)
    return [
        DelegationOut.model_validate(row, from_attributes=True)
        for row in db.scalars(
            select(AppDeliveryDelegation)
            .where(
                AppDeliveryDelegation.app_id == app_id,
                AppDeliveryDelegation.installation_id == str(installation_id),
                AppDeliveryDelegation.actor_user_id == context.user.id,
                AppDeliveryDelegation.revoked_at.is_(None),
            )
            .order_by(AppDeliveryDelegation.created_at.desc())
            .limit(100)
        )
    ]


@router.delete(_OWNER + "/{grant_id}", status_code=204)
def revoke(
    app_id: str,
    installation_id: UUID,
    grant_id: UUID,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    delegation.revoke(db, app_id, str(installation_id), str(grant_id), context)


@router.get(_DELEGATED + "/context", response_model=DelegatedContext)
def current_context(
    app_id: str,
    installation_id: UUID,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(db, authorization, "read", app_id, str(installation_id))
    return delegation.current_context(db, grant, context)


@router.post(_DELEGATED + "/sync", response_model=DefinitionOut)
def sync(
    app_id: str,
    installation_id: UUID,
    data: RegisterDefinition,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(db, authorization, "sync", app_id, str(installation_id))
    return delegation.sync_definition(db, grant, context, data)


@router.post(_DELEGATED + "/builds", response_model=BuildOut, status_code=202)
def request_build(
    app_id: str,
    installation_id: UUID,
    data: BuildInput,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(db, authorization, "build", app_id, str(installation_id))
    return delegation.request_build(db, grant, context, data)


@router.get(_DELEGATED + "/builds/{build_id}", response_model=BuildOut)
def build_status(
    app_id: str,
    installation_id: UUID,
    build_id: UUID,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, _ = delegation.resolve(db, authorization, "read", app_id, str(installation_id))
    return delegation.read_build(db, grant, str(build_id))


@router.post(_DELEGATED + "/deployments", response_model=DeploymentOut, status_code=202)
def request_delegated_deployment(
    app_id: str,
    installation_id: UUID,
    data: DeploymentInput,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(
        db, authorization, data.action, app_id, str(installation_id)
    )
    if data.installation_id != installation_id:
        service.fail("forbidden")
    return delivery.request_deployment(db, app_id, data, context, delegation_id=grant.id)


@router.get(_DELEGATED + "/deployments/{request_id}", response_model=DeploymentOut)
def delegated_deployment_status(
    app_id: str,
    installation_id: UUID,
    request_id: UUID,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(db, authorization, "read", app_id, str(installation_id))
    record = db.get(AppDeploymentRequest, str(request_id))
    if record is None or (record.installation_id, record.actor_user_id) != (
        grant.installation_id,
        grant.actor_user_id,
    ):
        service.fail("not_found", 404)
    return delivery.read_deployment(db, app_id, str(request_id), context)
