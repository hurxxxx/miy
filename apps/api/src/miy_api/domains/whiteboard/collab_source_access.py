"""Inactive explicit Source ACL reads, separate from room init and persistence."""

from collections.abc import Callable
from functools import partial

from anyio import CapacityLimiter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import CompanyAppControl, User, UserSystemRole
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.owned_read_session import (
    CORE_POLICY_READ_COLUMNS as CORE_POLICY_READ_COLUMNS,
    OwnedReadSessionRefused,
    cleanup_owned_read_session,
    require_fresh_owned_read_session,
    require_owned_read_transaction,
)
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.pms.models import TaskList
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember
from miy_api.domains.whiteboard.access import (
    ensure_whiteboard_app_access,
    load_whiteboard_for_acl_or_404,
)
from miy_api.domains.whiteboard.models import (
    Whiteboard,
    WhiteboardGroupShare,
    WhiteboardTarget,
    WhiteboardUserShare,
)

_MODELS = (
    User,
    UserSystemRole,
    CompanyAppControl,
    AppAccessPolicy,
    AppUserGrant,
    AppGroupGrant,
    Group,
    GroupMember,
    Whiteboard,
    WhiteboardTarget,
    WhiteboardUserShare,
    WhiteboardGroupShare,
    Team,
    TeamMember,
    SpaceGroupBinding,
    TaskList,
    Meeting,
    MeetingAttendee,
)


class WhiteboardSourceReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_source_reader_refused")


def _fresh(db: Session, *, models: tuple = _MODELS) -> None:
    try:
        require_fresh_owned_read_session(db, models=models)
    except OwnedReadSessionRefused as exc:
        raise WhiteboardSourceReaderRefused(exc.reason) from None


def _cleanup(db: Session) -> None:
    cleanup_owned_read_session(db)


def require_whiteboard_source_read_transaction(db: Session) -> None:
    """Admit the existing owned read transaction; this is not a grant profile."""
    try:
        require_owned_read_transaction(db)
    except OwnedReadSessionRefused as exc:
        raise WhiteboardSourceReaderRefused(exc.reason) from None


def require_prepared_whiteboard_edit_access(
    create_session: Callable[[], Session], *, item_id: str, user: User
) -> None:
    db = create_session()
    _fresh(db)  # Rejected caller work never becomes this reader's owned Session.
    try:
        require_whiteboard_source_read_transaction(db)
        ensure_whiteboard_app_access(db, user)
        context = load_whiteboard_for_acl_or_404(db, item_id=item_id, current_user=user)
        if not context.access.can_edit:
            raise localized_http_exception(status_code=403, code="whiteboard.edit_access_required")
    except WriterControlError:
        raise WhiteboardSourceReaderRefused("source_role_required") from None
    except SQLAlchemyError:
        raise WhiteboardSourceReaderRefused("source_read_failed") from None
    finally:
        _cleanup(db)


def build_prepared_whiteboard_source_access(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    if not callable(session_factory):
        raise ValueError("Prepared Whiteboard Source access requires a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared Whiteboard Source access requires a positive read budget")
    limiter: CapacityLimiter | None = None

    async def require_access(*, item_id: str, user: User) -> None:
        nonlocal limiter
        if limiter is None:
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            await run_owned_read(
                partial(
                    require_prepared_whiteboard_edit_access,
                    session_factory,
                    item_id=item_id,
                    user=user,
                ),
                limiter=limiter,
            )
        except (WhiteboardSourceReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None

    return require_access
