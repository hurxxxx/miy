from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import service
from miy_api.domains.independent_apps.contracts import (
    AppIdentityOut,
    AppSessionOut,
    Contract,
    DefinitionOut,
    ExchangeInput,
    InstallationInput,
    InstallationOut,
    InstallationSummary,
    LaunchInput,
    LaunchOut,
    RegisterDefinition,
    ReleaseCandidate,
    ReleaseOut,
)
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps import delivery
from miy_api.domains.independent_apps import data_api
from miy_api.domains.independent_apps import delegation_api
from miy_api.domains.independent_apps import bootstrap_api
from miy_api.domains.independent_apps import registration_api
from miy_api.domains.independent_apps import owner_preview_api
from miy_api.domains.independent_apps import file_api
from miy_api.domains.independent_apps.delivery_contracts import DeploymentInput, DeploymentOut


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/independent-apps",
    tags=["independent-apps"],
    dependencies=[Depends(no_store)],
)
router.include_router(data_api.router)
router.include_router(delegation_api.router)
router.include_router(bootstrap_api.router)
router.include_router(registration_api.router)
router.include_router(owner_preview_api.router)
router.include_router(file_api.router)


@router.post("/{app_id}/deployments", response_model=DeploymentOut, status_code=202)
def request_deployment(
    app_id: str,
    data: DeploymentInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return delivery.request_deployment(db, app_id, data, context)


@router.get("/{app_id}/deployments/{request_id}", response_model=DeploymentOut)
def deployment_status(
    app_id: str,
    request_id: str,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return delivery.read_deployment(db, app_id, request_id, context)


class CatalogItem(Contract):
    definition: DefinitionOut
    installations: list["InstallationSummary"]


class CompanyControl(Contract):
    enabled: bool


class CatalogOut(Contract):
    items: list[CatalogItem]
    total: int
    page: int
    page_size: int
    catalog_revision: str


@router.get("/catalog", response_model=CatalogOut)
def catalog(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    installations = db.scalars(select(AppInstallationRecord)).all()
    by_app: dict[str, list[AppInstallationRecord]] = {}
    for installation in installations:
        by_app.setdefault(installation.app_id, []).append(installation)
    items = []
    for definition in db.scalars(select(AppDefinitionRecord).order_by(AppDefinitionRecord.app_id)):
        managed = (
            definition.owner_user_id == context.user.id or "platform_admin" in context.system_roles
        )
        visible = [
            row
            for row in by_app.get(definition.app_id, [])
            if managed or service.admitted(db, row, context.user)
        ]
        if managed or visible:
            items.append(
                CatalogItem(
                    definition=service.definition_out(definition),
                    installations=[
                        service.installation_summary(db, row, definition, context.user)
                        for row in visible
                    ],
                )
            )
    return CatalogOut(
        items=items[(page - 1) * page_size : page * page_size],
        total=len(items),
        page=page,
        page_size=page_size,
        catalog_revision=hashlib.sha256(
            json.dumps(
                [item.model_dump(mode="json") for item in items],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    )


@router.put("/{app_id}/company-control", response_model=CompanyControl)
def set_company_control(
    app_id: str,
    data: CompanyControl,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return CompanyControl(enabled=service.set_company_enabled(db, app_id, data.enabled, context))


@router.put("/definitions", response_model=DefinitionOut)
def register_definition(
    data: RegisterDefinition,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return service.register_definition(db, data, context)


@router.post("/{app_id}/releases", response_model=ReleaseOut, status_code=201)
def register_release(
    app_id: str,
    data: ReleaseCandidate,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return service.register_release(db, app_id, data, context)


@router.post("/{app_id}/installations", response_model=InstallationOut, status_code=201)
def create_installation(
    app_id: str,
    data: InstallationInput,
    request: Request,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return service.configure_installation(
        db,
        app_id,
        data,
        context,
        platform_origin=str(request.base_url).rstrip("/"),
    )


@router.put("/{app_id}/installations/{installation_id}", response_model=InstallationOut)
def update_installation(
    app_id: str,
    installation_id: str,
    data: InstallationInput,
    request: Request,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return service.configure_installation(
        db,
        app_id,
        data,
        context,
        installation_id=installation_id,
        platform_origin=str(request.base_url).rstrip("/"),
    )


@router.post("/launch", response_model=LaunchOut)
def issue_launch(
    data: LaunchInput,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return service.issue_launch(db, data, context)


@router.post("/exchange", response_model=AppSessionOut)
def exchange_launch(
    data: ExchangeInput,
    origin: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
):
    return service.exchange_launch(db, data, origin=origin)


@router.get("/session", response_model=AppIdentityOut)
def read_session(
    installation_id: str = Query(min_length=1, max_length=36),
    audience: str = Query(min_length=1, max_length=300),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
):
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 200:
        service.fail("session_invalid", 401)
    return service.app_identity(
        db, token=authorization[7:], installation_id=installation_id, audience=audience
    )
