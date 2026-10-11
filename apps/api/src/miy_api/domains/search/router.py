from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.auth.dependencies import require_current_user
from miy_api.domains.auth.models import User
from miy_api.domains.retrieval import application as retrieval_application
from miy_api.domains.search.schemas import KeywordSearchRequest, KeywordSearchResponse

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/query", response_model=KeywordSearchResponse)
def query_search(
    payload: KeywordSearchRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(require_current_user),
) -> KeywordSearchResponse:
    return retrieval_application.query_keyword_search_response(
        db,
        user=current_user,
        request=payload,
    )
