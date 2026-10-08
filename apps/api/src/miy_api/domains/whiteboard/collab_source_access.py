"""Inactive explicit Source ACL reads, separate from room init and persistence."""

from collections.abc import Callable
from functools import partial

from anyio import CapacityLimiter
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import CompanyAppControl, User, UserSystemRole
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.meeting.models import Meeting, MeetingAttendee
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.official_apps.writer_roles import _role
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

# Columns used by current app/group/admin predicates, already within the F2
# policy contract. This module neither prepares nor widens a runtime profile.
CORE_POLICY_READ_COLUMNS = {
    "users": (
        "id",
        "status",
        "login_blocked",
        "must_change_password",
        "primary_organization_unit_id",
    ),
    "user_system_roles": ("user_id", "role"),
    "company_app_controls": ("app_id", "enabled"),
    "app_access_policies": ("app_id", "audience"),
    "app_user_grants": ("app_id", "user_id"),
    "app_group_grants": ("app_id", "group_id"),
    "groups": ("id", "source", "active"),
    "group_members": ("group_id", "user_id"),
}
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


def _fresh(db: Session) -> None:
    if getattr(db.get_bind, "__func__", None) is not Session.get_bind:
        raise WhiteboardSourceReaderRefused("standard_session_binding_required")
    try:
        engine = db.get_bind()
        if not isinstance(engine, Engine):
            raise WhiteboardSourceReaderRefused("engine_binding_required")
        for model in _MODELS:
            if (
                db.get_bind(mapper=model) is not engine
                or db.get_bind(clause=select(model.__table__)) is not engine
            ):
                raise WhiteboardSourceReaderRefused("single_engine_required")
    except SQLAlchemyError:
        raise WhiteboardSourceReaderRefused("engine_binding_required") from None
    if (
        db.in_transaction()
        or db.in_nested_transaction()
        or db.new
        or db.dirty
        or db.deleted
        or db.identity_map
    ):
        raise WhiteboardSourceReaderRefused("fresh_session_required")


def _cleanup(db: Session) -> None:
    for action in (db.rollback, db.close):
        try:
            action()
        except BaseException:
            try:
                db.invalidate()
            except BaseException:
                pass


def require_prepared_whiteboard_edit_access(
    create_session: Callable[[], Session], *, item_id: str, user: User
) -> None:
    db = create_session()
    _fresh(db)  # Rejected caller work never becomes this reader's owned Session.
    try:
        if db.get_bind().dialect.name != "postgresql":
            raise WhiteboardSourceReaderRefused("postgresql_required")
        if db.connection().connection.driver_connection.autocommit is True:
            raise WhiteboardSourceReaderRefused("read_committed_required")
        if db.scalar(text("SHOW transaction_isolation")) != "read committed":
            raise WhiteboardSourceReaderRefused("read_committed_required")
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL search_path = pg_catalog, public, pg_temp"))
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '15s'"))
        current, session = db.execute(text("SELECT CURRENT_USER, SESSION_USER")).one()
        if current != session:
            raise WhiteboardSourceReaderRefused("direct_login_required")
        # Catalog-only reuse; this does not install a principal or attest all
        # Source grants. The separate role contracts retain that responsibility.
        _role(db, session, login=True)
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
