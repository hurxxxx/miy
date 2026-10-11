"""Normal MIY owner login only; no registration or delivery bearer is accepted."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import owner_preview
from miy_api.domains.independent_apps.owner_preview_contracts import (
    OwnerPreviewOut,
    OwnerPreviewPatch,
)

router = APIRouter()
PATH = "/{app_id}/installations/{installation_id}/owner-preview"


@router.get(PATH, response_model=OwnerPreviewOut)
def read_owner_preview(
    app_id: str,
    installation_id: str,
    request: Request,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return owner_preview.read(
        db, app_id, installation_id, context, platform_origin=str(request.base_url).rstrip("/")
    )


@router.patch(PATH, response_model=OwnerPreviewOut)
def configure_owner_preview(
    app_id: str,
    installation_id: str,
    data: OwnerPreviewPatch,
    request: Request,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return owner_preview.configure(
        db,
        app_id,
        installation_id,
        data,
        context,
        platform_origin=str(request.base_url).rstrip("/"),
    )
