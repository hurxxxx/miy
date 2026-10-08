"""Prepared existing room-state reads; no creation, repair or persistence."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import json
from typing import Any

from anyio import CapacityLimiter
from sqlalchemy import Text, case, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from miy_api.core.i18n import localized_http_exception
from miy_api.domains.auth.models import User
from miy_api.domains.official_apps.owned_read import run_owned_read
from miy_api.domains.official_apps.writer import WriterControlError
from miy_api.domains.whiteboard.collab import WhiteboardCollabContext
from miy_api.domains.whiteboard import collab_source_access as access
from miy_api.domains.whiteboard.models import Whiteboard, WhiteboardCollabDocument, empty_scene
from miy_api.domains.whiteboard.scene_state import make_whiteboard_room_key

ROOM_STATE_MAX_BYTES = 8 * 1024 * 1024
_ROOM_MODELS = (*access._MODELS, WhiteboardCollabDocument)


class WhiteboardRoomReaderRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_room_reader_refused")


@dataclass(frozen=True)
class PreparedWhiteboardRoomState:
    context: WhiteboardCollabContext
    yjs_state: bytes | None
    snapshot_scene: dict[str, Any]


def _paired_room_query(item_id: str):
    scene_text = cast(Whiteboard.scene, Text)
    snapshot_text = cast(WhiteboardCollabDocument.snapshot_scene, Text)

    # Measure the same paired SELECT's UTF-8 text and raw binary columns.
    # CASE keeps oversized bodies out of the driver/Python materialization.
    def json_size(value):
        return func.coalesce(
            func.pg_catalog.octet_length(func.pg_catalog.convert_to(value, "UTF8")), 0
        )

    total = (
        json_size(scene_text)
        + json_size(snapshot_text)
        + func.coalesce(func.pg_catalog.octet_length(WhiteboardCollabDocument.yjs_state), 0)
    )
    permitted = total <= ROOM_STATE_MAX_BYTES
    return (
        select(
            Whiteboard.id.label("board_id"),
            Whiteboard.owner_id.label("owner_id"),
            Whiteboard.updated_at.label("board_updated_at"),
            Whiteboard.trashed_at.label("trashed_at"),
            WhiteboardCollabDocument.id.label("collab_id"),
            WhiteboardCollabDocument.whiteboard_id.label("collab_board_id"),
            WhiteboardCollabDocument.room_key,
            WhiteboardCollabDocument.updated_at.label("collab_updated_at"),
            total.label("body_bytes"),
            case((permitted, scene_text)).label("scene_text"),
            case((permitted, snapshot_text)).label("snapshot_text"),
            case((permitted, WhiteboardCollabDocument.yjs_state)).label("yjs_state"),
        )
        .select_from(Whiteboard)
        .outerjoin(
            WhiteboardCollabDocument, WhiteboardCollabDocument.whiteboard_id == Whiteboard.id
        )
        .where(Whiteboard.id == item_id)
    )


def _room_state(row: Mapping, *, item_id: str) -> PreparedWhiteboardRoomState:
    if row["trashed_at"] is not None:
        raise localized_http_exception(status_code=404, code="whiteboard.not_found")
    if row["collab_id"] is None:
        raise WhiteboardRoomReaderRefused("room_state_missing")
    board_at, collab_at = row["board_updated_at"], row["collab_updated_at"]
    key = row["room_key"]
    base_key = make_whiteboard_room_key(item_id)
    if (
        row["board_id"] != item_id
        or row["collab_board_id"] != item_id
        or not isinstance(key, str)
        or not key
        or len(key) > 128
        or not (key == base_key or key.startswith(base_key + ":") and len(key) > len(base_key) + 1)
        or not isinstance(row["owner_id"], str)
        or not row["owner_id"]
        or not isinstance(board_at, datetime)
        or not isinstance(collab_at, datetime)
    ):
        raise WhiteboardRoomReaderRefused("room_state_invalid")
    try:
        stale = collab_at < board_at
    except TypeError:
        raise WhiteboardRoomReaderRefused("room_state_invalid") from None
    if stale:
        raise WhiteboardRoomReaderRefused("room_state_stale")
    if type(row["body_bytes"]) is not int or not 0 <= row["body_bytes"] <= ROOM_STATE_MAX_BYTES:
        raise WhiteboardRoomReaderRefused("room_state_too_large")
    scene_text, snapshot_text, raw_yjs = row["scene_text"], row["snapshot_text"], row["yjs_state"]
    if (
        not isinstance(scene_text, str)
        or not isinstance(snapshot_text, str)
        or raw_yjs is not None
        and not isinstance(raw_yjs, (bytes, bytearray, memoryview))
    ):
        raise WhiteboardRoomReaderRefused("room_state_invalid")
    yjs = None if raw_yjs is None else bytes(raw_yjs)
    try:
        transferred = len(scene_text.encode("utf-8")) + len(snapshot_text.encode("utf-8"))
        transferred += len(yjs or b"")
        if transferred != row["body_bytes"] or transferred > ROOM_STATE_MAX_BYTES:
            raise WhiteboardRoomReaderRefused("room_state_too_large")
        scene, snapshot = json.loads(scene_text), json.loads(snapshot_text)
        if not isinstance(scene, dict) or not isinstance(snapshot, dict):
            raise WhiteboardRoomReaderRefused("room_state_invalid")
        scene = scene or empty_scene()
        dto_bytes = sum(
            len(
                json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            for value in (scene, snapshot)
        ) + len(yjs or b"")
        if dto_bytes > ROOM_STATE_MAX_BYTES:
            raise WhiteboardRoomReaderRefused("room_state_too_large")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, WhiteboardRoomReaderRefused):
            raise
        raise WhiteboardRoomReaderRefused("room_state_invalid") from None
    return PreparedWhiteboardRoomState(
        WhiteboardCollabContext(item_id, key, True, scene, row["owner_id"]), yjs, snapshot
    )


def load_prepared_whiteboard_room_state(
    create_session: Callable[[], Session], *, item_id: str, user: User
) -> PreparedWhiteboardRoomState:
    db = create_session()
    access._fresh(db, models=_ROOM_MODELS)  # No cleanup ownership for rejected caller work.
    try:
        access.require_whiteboard_source_read_transaction(db)
        access.ensure_whiteboard_app_access(db, user)
        first = access.load_whiteboard_for_acl_or_404(db, item_id=item_id, current_user=user)
        if not first.access.can_edit:
            raise localized_http_exception(status_code=403, code="whiteboard.edit_access_required")
        normalized_id = first.whiteboard.id
        row = db.execute(_paired_room_query(normalized_id)).mappings().one_or_none()
        if row is None:
            raise localized_http_exception(status_code=404, code="whiteboard.not_found")
        result = _room_state(row, item_id=normalized_id)
        # Current ACL queries must not reuse the first ORM identity snapshot.
        db.expunge_all()
        access.ensure_whiteboard_app_access(db, user)
        final = access.load_whiteboard_for_acl_or_404(db, item_id=item_id, current_user=user)
        if final.whiteboard.trashed_at is not None:
            raise localized_http_exception(status_code=404, code="whiteboard.not_found")
        if not final.access.can_edit:
            raise localized_http_exception(status_code=403, code="whiteboard.edit_access_required")
        return result
    except WriterControlError:
        raise WhiteboardRoomReaderRefused("source_role_required") from None
    except SQLAlchemyError:
        raise WhiteboardRoomReaderRefused("source_read_failed") from None
    finally:
        access._cleanup(db)


def build_prepared_whiteboard_room_loader(
    *, session_factory: Callable[[], Session], max_concurrent_reads: int
):
    if not callable(session_factory):
        raise ValueError("Prepared Whiteboard room reads require a Session factory")
    if type(max_concurrent_reads) is not int or max_concurrent_reads < 1:
        raise ValueError("Prepared Whiteboard room reads require a positive read budget")
    limiter: CapacityLimiter | None = None

    async def load_room(*, item_id: str, user: User) -> PreparedWhiteboardRoomState:
        nonlocal limiter
        if limiter is None:
            limiter = CapacityLimiter(max_concurrent_reads)
        try:
            return await run_owned_read(
                partial(
                    load_prepared_whiteboard_room_state, session_factory, item_id=item_id, user=user
                ),
                limiter=limiter,
            )
        except (WhiteboardRoomReaderRefused, access.WhiteboardSourceReaderRefused, SQLAlchemyError):
            raise localized_http_exception(
                status_code=503, code="official_apps.authority_unavailable"
            ) from None

    return load_room
