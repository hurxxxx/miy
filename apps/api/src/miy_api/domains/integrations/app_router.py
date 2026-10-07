import hashlib
import json
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from miy_api.core.app_contracts_generated import APP_CONTRACT_BY_ID
from miy_api.core.db import get_db_session
from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.independent_apps.observations import installation_observations
from miy_api.domains.integrations.app_projection import app_catalog, app_usage
from miy_api.domains.integrations.platform_api_keys import (
    PlatformApiPrincipal,
    platform_api_scope_openapi,
    require_platform_api_scope,
)

router = APIRouter(prefix="/integrations/apps", tags=["app-integrations"])


class ManagedAppResponse(BaseModel):
    app_id: str
    title: str
    enabled: bool
    release_unit: str | None
    installed_revision: str | None
    registered_source_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    runtime_ai: bool
    title_translations: dict[str, str] = Field(default_factory=dict)
    icon_key: str = "layout-grid"
    source_repository: str | None = None
    source_directory: str | None = None
    definition_digest: str | None = None


class ManagedAppsResponse(BaseModel):
    schema_version: Literal[1] = 1
    registration_status_version: Literal[1] = 1
    items: list[ManagedAppResponse]
    total: int
    page: int
    page_size: int
    catalog_revision: str
    generated_at: datetime


class AppUsageResponse(BaseModel):
    schema_version: Literal[1] = 1
    app_id: str
    month: str
    app_opens: int
    llm_calls: int
    llm_errors: int
    total_tokens: int | None
    unreported_calls: int
    complete: bool
    amount_minor: int | None
    currency: str | None
    cost_basis: Literal["not_reported"]
    generated_at: datetime


class DeploymentObservationResponse(BaseModel):
    request_id: str
    action: Literal["deploy", "rollback"]
    state: Literal["queued", "running", "cleanup", "succeeded", "failed", "unknown"]
    failure_code: str | None
    updated_at: datetime


class InstallationObservationResponse(BaseModel):
    id: str
    environment: Literal["development", "production"]
    origin: str
    enabled: bool
    state: str
    generation: int
    release_id: str | None
    source_revision: str | None
    artifact_digest: str | None
    deployment: DeploymentObservationResponse | None


class InstallationObservationsResponse(BaseModel):
    schema_version: Literal[1] = 1
    app_id: str
    items: list[InstallationObservationResponse]
    total: int
    page: int
    page_size: int
    catalog_revision: str
    generated_at: datetime


def audit(db, response, principal, action, app_id=None):
    response.headers["Cache-Control"] = "private, no-store"
    record_audit_log(
        db,
        actor_user_id=None,
        action=action,
        entity_kind="app_integration",
        entity_id=app_id,
        summary="Read app management projection",
        payload={"api_key_id": principal.key_id, "outcome": "succeeded"},
    )
    db.commit()


@router.get(
    "",
    response_model=ManagedAppsResponse,
    openapi_extra=platform_api_scope_openapi("app-catalog:read"),
)
def list_apps(
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    principal: PlatformApiPrincipal = Depends(require_platform_api_scope("app-catalog:read")),
    db: Session = Depends(get_db_session),
):
    items = app_catalog(db)
    # Changes to admission or a release invalidate an in-flight traversal too.
    revision = hashlib.sha256(
        json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    audit(db, response, principal, "integration.apps.catalog.read")
    return ManagedAppsResponse(
        items=items[(page - 1) * page_size : page * page_size],
        total=len(items),
        page=page,
        page_size=page_size,
        catalog_revision=revision,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/{app_id}/installations",
    response_model=InstallationObservationsResponse,
    openapi_extra=platform_api_scope_openapi("app-catalog:read"),
)
def read_installations(
    app_id: str,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    principal: PlatformApiPrincipal = Depends(require_platform_api_scope("app-catalog:read")),
    db: Session = Depends(get_db_session),
):
    items = installation_observations(db, app_id)
    if items is None:
        raise localized_http_exception(status_code=404, code="app.not_found")
    revision = hashlib.sha256(
        json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    audit(db, response, principal, "integration.apps.installations.read", app_id)
    return InstallationObservationsResponse(
        app_id=app_id,
        items=items[(page - 1) * page_size : page * page_size],
        total=len(items),
        page=page,
        page_size=page_size,
        catalog_revision=revision,
        generated_at=datetime.now(UTC),
    )


@router.get(
    "/{app_id}/usage",
    response_model=AppUsageResponse,
    openapi_extra=platform_api_scope_openapi("app-usage:read"),
)
def read_usage(
    app_id: str,
    response: Response,
    month: date | None = Query(default=None, ge=date(2000, 1, 1), le=date(9998, 12, 31)),
    principal: PlatformApiPrincipal = Depends(require_platform_api_scope("app-usage:read")),
    db: Session = Depends(get_db_session),
):
    if app_id not in APP_CONTRACT_BY_ID:
        raise localized_http_exception(status_code=404, code="app.not_found")
    result = app_usage(db, app_id, month)
    audit(db, response, principal, "integration.apps.usage.read", app_id)
    return AppUsageResponse(**result, generated_at=datetime.now(UTC))
