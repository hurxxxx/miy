from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from open_work_hub_api.core.db import get_db_session
from open_work_hub_api.domains.auth.app_gate import require_app_access
from open_work_hub_api.domains.auth.dependencies import require_current_user
from open_work_hub_api.domains.auth.models import User

from . import ai
from .schemas import TetrisDecisionRequest, TetrisDecisionResponse

router = APIRouter(
    prefix="/tetris", tags=["tetris"], dependencies=[Depends(require_app_access("tetris"))]
)


@router.post("/decision", response_model=TetrisDecisionResponse)
def decision(
    payload: TetrisDecisionRequest,
    db: Session = Depends(get_db_session),
    user: User = Depends(require_current_user),
) -> TetrisDecisionResponse:
    return ai.decide(db, user=user, payload=payload)
