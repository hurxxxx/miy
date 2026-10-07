"""Separate credentials and routes for owner consent and delegated bootstrap."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import registration
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput, BootstrapReceipt
from miy_api.domains.independent_apps.registration_contracts import (
    RegistrationAuthorizationInput,
    RegistrationCodeOut,
    RegistrationExchangeInput,
    RegistrationTokenOut,
)

router = APIRouter(prefix="/bootstrap-authorizations", tags=["independent-app-registration"])


@router.post("", response_model=RegistrationCodeOut, status_code=201)
def authorize_registration(
    data: RegistrationAuthorizationInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return registration.issue(db, data, context)


@router.post("/exchange", response_model=RegistrationTokenOut)
def exchange_registration_authorization(
    data: RegistrationExchangeInput, db: Session = Depends(get_db_session)
):
    return registration.exchange(db, data)


@router.delete("/{authorization_id}", status_code=204)
def revoke_registration_authorization(
    authorization_id: UUID,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    registration.revoke(db, str(authorization_id), context)


@router.post("/{authorization_id}/bootstrap", response_model=BootstrapReceipt, status_code=201)
def bootstrap_with_registration_authorization(
    authorization_id: UUID,
    data: BootstrapInput,
    request: Request,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    return registration.create(
        db,
        str(authorization_id),
        authorization,
        data,
        platform_origin=str(request.base_url).rstrip("/"),
    )


@router.get("/{authorization_id}/receipt", response_model=BootstrapReceipt)
def read_registration_authorization_receipt(
    authorization_id: UUID,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    return registration.receipt(db, str(authorization_id), authorization)
