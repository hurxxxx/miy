"""Inactive explicit Docs ACL reads; initial rooms and persistence stay native."""

from collections.abc import Callable
from functools import partial

from anyio import CapacityLimiter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppGroupGrant, AppUserGrant
from miy_api.domains.auth.models import CompanyAppControl, User, UserSystemRole
from miy_api.domains.docs.access_context import (
    PAGE_SOURCE_NATIVE_DOC,
    ensure_docs_app_access,
    load_native_page_for_acl_or_404,
    split_prefixed_id,
)
from miy_api.domains.docs.models import (
    DocMeetingAccess,
    NativeDoc,
    NativeDocGroupShare,
    NativeDocPage,
    NativeDocTarget,
    NativeDocUserShare,
)
from miy_api.domains.groups.models import Group, GroupMember
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.owned_read_session import (
    OwnedReadSessionRefused,
    cleanup_owned_read_session,
    require_fresh_owned_read_session,
    require_owned_read_transaction,
)
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.pms.space_models import SpaceGroupBinding, Team, TeamMember

_MODELS = (
    User,
    UserSystemRole,
    CompanyAppControl,
    AppAccessPolicy,
    AppUserGrant,
    AppGroupGrant,
    Group,
    GroupMember,
    NativeDoc,
    NativeDocPage,
    NativeDocTarget,
    NativeDocUserShare,
    NativeDocGroupShare,
    DocMeetingAccess,
    Team,
    TeamMember,
    SpaceGroupBinding,
)


class DocsSourceReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("docs_source_reader_refused")


def require_prepared_docs_edit_access(
    create_session: Callable[[], Session], *, page_ref: str, user: User
) -> None:
    db = create_session()
    try:
        require_fresh_owned_read_session(db, models=_MODELS)
    except OwnedReadSessionRefused as exc:
        # Rejected borrowed work does not become this reader's cleanup property.
        raise DocsSourceReaderRefused(exc.reason) from None
    try:
        require_owned_read_transaction(db)
        ensure_docs_app_access(db, user)
        prefix, page_id = split_prefixed_id(page_ref)
        if prefix != PAGE_SOURCE_NATIVE_DOC:
            raise localized_http_exception(status_code=404, code="docs.page_not_found")
        load_native_page_for_acl_or_404(db, page_id=page_id, user=user)
    except OwnedReadSessionRefused as exc:
        raise DocsSourceReaderRefused(exc.reason) from None
    except WriterControlError:
        raise DocsSourceReaderRefused("source_role_required") from None
    except SQLAlchemyError:
        raise DocsSourceReaderRefused("source_read_failed") from None
    finally:
        cleanup_owned_read_session(db)


def build_prepared_docs_source_access(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    if not callable(session_factory):
        raise ValueError("Prepared Docs Source access requires a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared Docs Source access requires a positive read budget")
    limiter: CapacityLimiter | None = None

    async def require_access(*, page_ref: str, user: User) -> None:
        nonlocal limiter
        if limiter is None:
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            await run_owned_read(
                partial(
                    require_prepared_docs_edit_access, session_factory, page_ref=page_ref, user=user
                ),
                limiter=limiter,
            )
        except (DocsSourceReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None

    return require_access
