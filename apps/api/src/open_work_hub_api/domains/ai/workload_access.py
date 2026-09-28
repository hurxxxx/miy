"""Execution owner admission, shared by native decisions and generation runtimes."""

from sqlalchemy.orm import Session

from open_work_hub_api.core.llm_errors import LlmProviderError
from open_work_hub_api.domains.auth.app_gate import can_use_app
from open_work_hub_api.domains.auth.models import User


def require_workload_owner(db: Session, *, owner_id: str | None, app_id: str) -> User:
    user = db.get(User, owner_id) if owner_id else None
    if (
        user is None
        or user.status != "active"
        or user.login_blocked
        or not can_use_app(db, app_id=app_id, user_id=user.id)
    ):
        raise LlmProviderError("Workload owner no longer has access to this app.")
    return user
