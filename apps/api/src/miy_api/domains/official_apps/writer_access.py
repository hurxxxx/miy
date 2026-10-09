"""Inactive explicit Core writer admission read; never a Source write fence."""

from collections.abc import Callable
from functools import partial

from anyio import CapacityLimiter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.owned_read_session import (
    OwnedReadSessionRefused,
    cleanup_owned_read_session,
    require_fresh_owned_read_session,
    require_owned_read_transaction,
)
from miy_api.domains.official_apps.writer import (
    WriterControlError,
    WriterIdentity,
    require_active_writer,
)
from miy_api.domains.official_apps.writer_models import RuntimeOwnership

_MODELS = (RuntimeOwnership,)


class CoreWriterReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("core_writer_reader_refused")


def require_prepared_active_writer(
    create_session: Callable[[], Session], *, writer_identity: WriterIdentity
) -> None:
    if not isinstance(writer_identity, WriterIdentity):
        raise CoreWriterReaderRefused("pinned_writer_identity_required")
    db = create_session()
    try:
        require_fresh_owned_read_session(db, models=_MODELS)
    except OwnedReadSessionRefused as exc:
        raise CoreWriterReaderRefused(exc.reason) from None
    try:
        require_owned_read_transaction(db)
        require_active_writer(db, writer_identity)
    except OwnedReadSessionRefused as exc:
        raise CoreWriterReaderRefused(exc.reason) from None
    except WriterControlError:
        raise CoreWriterReaderRefused("core_reader_role_required") from None
    except SQLAlchemyError:
        raise CoreWriterReaderRefused("core_writer_read_failed") from None
    finally:
        cleanup_owned_read_session(db)


def build_prepared_official_writer_access(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    if not callable(session_factory):
        raise ValueError("Prepared Core writer read requires a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared Core writer read requires a positive read budget")
    limiter: CapacityLimiter | None = None

    async def require_writer(*, writer_identity: WriterIdentity) -> None:
        nonlocal limiter
        if limiter is None:
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            await run_owned_read(
                partial(
                    require_prepared_active_writer, session_factory, writer_identity=writer_identity
                ),
                limiter=limiter,
            )
        except (CoreWriterReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None

    return require_writer
