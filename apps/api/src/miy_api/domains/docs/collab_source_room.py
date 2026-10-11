"""Inactive existing Docs room reads; no initialization, repair, codec or writes."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
import json

from anyio import CapacityLimiter
from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.models import User
from miy_api.domains.docs import collab_source_access as access
from miy_api.domains.docs.access_context import (
    PAGE_SOURCE_NATIVE_DOC,
    ensure_docs_app_access,
    load_native_page_for_acl_or_404,
    split_prefixed_id,
)
from miy_api.domains.docs.collab import CollabPageContext, make_page_ref, make_room_key
from miy_api.domains.docs.models import DocsCollabDocument, NativeDoc, NativeDocPage
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.owned_read_session import (
    OwnedReadSessionRefused,
    cleanup_owned_read_session,
    require_fresh_owned_read_session,
    require_owned_read_transaction,
)
from miy_api.domains.official_apps.writer import WriterControlError

ROOM_STATE_MAX_BYTES = 8 * 1024 * 1024
_ROOM_MODELS = (*access._MODELS, DocsCollabDocument)


class DocsRoomReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("docs_room_reader_refused")


@dataclass(frozen=True)
class PreparedDocsRoomState:
    context: CollabPageContext
    yjs_state: bytes | None
    snapshot_content_blocks: list[dict] | None


def _paired_room_query(page_id: str):
    page_text = cast(NativeDocPage.content_blocks, Text)
    snapshot_text = cast(DocsCollabDocument.snapshot_content_blocks, Text)

    def json_size(value):
        return func.coalesce(
            func.pg_catalog.octet_length(func.pg_catalog.convert_to(value, "UTF8")), 0
        )

    total = (
        json_size(page_text)
        + json_size(snapshot_text)
        + func.coalesce(func.pg_catalog.octet_length(DocsCollabDocument.yjs_state), 0)
    )
    permitted = total <= ROOM_STATE_MAX_BYTES
    return (
        select(
            NativeDocPage.id.label("page_id"),
            NativeDocPage.doc_id,
            NativeDocPage.content_format,
            NativeDocPage.trashed_at.label("page_trash"),
            NativeDocPage.created_by_id,
            NativeDoc.id.label("parent_id"),
            NativeDoc.trashed_at.label("doc_trash"),
            DocsCollabDocument.id.label("collab_id"),
            DocsCollabDocument.source_type,
            DocsCollabDocument.source_page_id,
            DocsCollabDocument.room_key,
            total.label("body_bytes"),
            case((permitted, page_text)).label("page_text"),
            case((permitted, snapshot_text)).label("snapshot_text"),
            case((permitted, DocsCollabDocument.yjs_state)).label("yjs_state"),
        )
        .select_from(NativeDocPage)
        .join(NativeDoc, NativeDoc.id == NativeDocPage.doc_id)
        .outerjoin(
            DocsCollabDocument,
            (DocsCollabDocument.source_type == PAGE_SOURCE_NATIVE_DOC)
            & (DocsCollabDocument.source_page_id == NativeDocPage.id),
        )
        .where(NativeDocPage.id == page_id)
    )


def _room_state(row: Mapping, *, page_id: str) -> PreparedDocsRoomState:
    if row["page_trash"] is not None or row["doc_trash"] is not None:
        raise localized_http_exception(status_code=403, code="docs.page_access_required")
    if row["content_format"] != "block":
        raise localized_http_exception(status_code=404, code="docs.page_not_found")
    if row["collab_id"] is None:
        raise DocsRoomReaderRefused("room_state_missing")
    if (
        row["page_id"] != page_id
        or row["source_page_id"] != page_id
        or row["source_type"] != PAGE_SOURCE_NATIVE_DOC
        or row["room_key"] != make_room_key(PAGE_SOURCE_NATIVE_DOC, page_id)
        or row["doc_id"] != row["parent_id"]
        or not isinstance(row["created_by_id"], str)
        or not row["created_by_id"]
        or not isinstance(row["doc_id"], str)
        or not row["doc_id"]
    ):
        raise DocsRoomReaderRefused("room_state_invalid")
    if type(row["body_bytes"]) is not int or not 0 <= row["body_bytes"] <= ROOM_STATE_MAX_BYTES:
        raise DocsRoomReaderRefused("room_state_too_large")
    texts = (row["page_text"], row["snapshot_text"])
    raw_yjs = row["yjs_state"]
    if (
        any(value is not None and not isinstance(value, str) for value in texts)
        or raw_yjs is not None
        and not isinstance(raw_yjs, (bytes, bytearray, memoryview))
    ):
        raise DocsRoomReaderRefused("room_state_invalid")
    yjs = None if raw_yjs is None else bytes(raw_yjs)
    try:
        # SQL NULL transfers zero JSON bytes; JSON text null transfers four.
        transferred = sum(len(value.encode("utf-8")) for value in texts if value is not None) + len(
            yjs or b""
        )
        if transferred != row["body_bytes"] or transferred > ROOM_STATE_MAX_BYTES:
            raise DocsRoomReaderRefused("room_state_too_large")
        page, snapshot = (None if value is None else json.loads(value) for value in texts)
        if any(
            value is not None
            and (not isinstance(value, list) or any(not isinstance(block, dict) for block in value))
            for value in (page, snapshot)
        ):
            raise DocsRoomReaderRefused("room_state_invalid")
        # Match native initializer writes; [] is not None. b'' stays distinct.
        if page is not None and (snapshot is None or yjs is None):
            raise DocsRoomReaderRefused("room_state_needs_repair")
        if not yjs and (page or snapshot):
            raise DocsRoomReaderRefused("room_state_missing_content")
        dto_bytes = sum(
            len(
                json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            )
            for value in (page, snapshot)
        ) + len(yjs or b"")
        if dto_bytes > ROOM_STATE_MAX_BYTES:
            raise DocsRoomReaderRefused("room_state_too_large")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, DocsRoomReaderRefused):
            raise
        raise DocsRoomReaderRefused("room_state_invalid") from None
    return PreparedDocsRoomState(
        CollabPageContext(
            make_page_ref(PAGE_SOURCE_NATIVE_DOC, page_id),
            PAGE_SOURCE_NATIVE_DOC,
            page_id,
            row["room_key"],
            True,
            page,
            row["created_by_id"],
        ),
        yjs,
        snapshot,
    )


def load_prepared_docs_room_state(
    create_session: Callable[[], Session], *, page_ref: str, user: User
) -> PreparedDocsRoomState:
    db = create_session()
    if not isinstance(db, Session):
        raise DocsRoomReaderRefused("standard_session_required")
    try:
        require_fresh_owned_read_session(db, models=_ROOM_MODELS)
    except OwnedReadSessionRefused as exc:
        raise DocsRoomReaderRefused(exc.reason) from None
    try:
        require_owned_read_transaction(db)
        ensure_docs_app_access(db, user)
        prefix, page_id = split_prefixed_id(page_ref)
        if prefix != PAGE_SOURCE_NATIVE_DOC:
            raise localized_http_exception(status_code=404, code="docs.page_not_found")
        first = load_native_page_for_acl_or_404(db, page_id=page_id, user=user)
        normalized_id = first.page.id
        row = db.execute(_paired_room_query(normalized_id)).mappings().one_or_none()
        if row is None:
            raise localized_http_exception(status_code=404, code="docs.page_not_found")
        result = _room_state(row, page_id=normalized_id)
        db.expunge_all()
        ensure_docs_app_access(db, user)
        final = load_native_page_for_acl_or_404(db, page_id=page_id, user=user)
        if final.page.id != normalized_id or final.page.doc_id != row["doc_id"]:
            raise DocsRoomReaderRefused("room_binding_changed")
        return result
    except OwnedReadSessionRefused as exc:
        raise DocsRoomReaderRefused(exc.reason) from None
    except WriterControlError:
        raise DocsRoomReaderRefused("source_role_required") from None
    except SQLAlchemyError:
        raise DocsRoomReaderRefused("source_read_failed") from None
    finally:
        cleanup_owned_read_session(db)


def build_prepared_docs_room_loader(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    if not callable(session_factory):
        raise ValueError("Prepared Docs room reads require a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared Docs room reads require a positive read budget")
    limiter: CapacityLimiter | None = None

    async def load_room(*, page_ref: str, user: User) -> PreparedDocsRoomState:
        nonlocal limiter
        if limiter is None:
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            return await run_owned_read(
                partial(
                    load_prepared_docs_room_state, session_factory, page_ref=page_ref, user=user
                ),
                limiter=limiter,
            )
        except (DocsRoomReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None

    return load_room
