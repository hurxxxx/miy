from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import AuthContext, require_auth_context
from miy_api.domains.independent_apps import bootstrap
from miy_api.domains.independent_apps.bootstrap_contracts import BootstrapInput, BootstrapReceipt

router = APIRouter(tags=["independent-app-bootstrap"])


@router.post("/bootstrap", response_model=BootstrapReceipt, status_code=201)
def bootstrap_independent_app(
    data: BootstrapInput,
    request: Request,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return bootstrap.create(db, data, context, platform_origin=str(request.base_url).rstrip("/"))


@router.get("/bootstrap/{operation_id}", response_model=BootstrapReceipt)
def independent_app_bootstrap_receipt(
    operation_id: UUID,
    context: AuthContext = Depends(require_auth_context),
    db: Session = Depends(get_db_session),
):
    return bootstrap.read(db, str(operation_id), context)
