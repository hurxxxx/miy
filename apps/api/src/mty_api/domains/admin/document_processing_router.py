from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mty_api.core.db import get_db_session
from mty_api.core.i18n import localized_http_exception
from mty_api.domains.admin.document_processing_projection import (
    build_admin_document_processing_snapshot,
)
from mty_api.domains.admin.document_processing_schemas import (
    AdminDocumentProcessingResponse,
)
from mty_api.domains.auth.access import is_platform_admin_user
from mty_api.domains.auth.dependencies import AuthContext, require_permission

router = APIRouter(prefix="/admin/document-processing", tags=["admin"])


@router.get("", response_model=AdminDocumentProcessingResponse)
def get_admin_document_processing(
    context: AuthContext = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db_session),
) -> AdminDocumentProcessingResponse:
    if not is_platform_admin_user(context.user, db):
        raise localized_http_exception(
            status_code=403,
            code="admin.platform_admin_required",
        )
    return build_admin_document_processing_snapshot(db)


__all__ = ["router"]
