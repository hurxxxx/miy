from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from time import monotonic
from typing import Any

from sqlalchemy import Engine, case, event, select, text, update
from sqlalchemy.orm import Session

from miy_api.core.settings import get_settings
from miy_api.core.transaction_outcome import commit_was_rejected
from miy_api.domains.auth.security import new_id
from miy_api.domains.whiteboard.models import (
    Whiteboard,
    WhiteboardCollabDocument,
    empty_scene,
)

PERSISTED_SCENE_APP_STATE_KEYS = frozenset(
    {
        "gridModeEnabled",
        "gridSize",
        "viewBackgroundColor",
    }
)


@dataclass(frozen=True)
class WhiteboardSceneStateResult:
    whiteboard_changed: bool
    collab_changed: bool
    collab: WhiteboardCollabDocument | None


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def make_whiteboard_room_key(whiteboard_id: str) -> str:
    return f"whiteboard:{whiteboard_id}"


def make_fresh_whiteboard_room_key(whiteboard_id: str) -> str:
    return f"whiteboard:{whiteboard_id}:{new_id()}"


def scene_for_compare(scene: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(scene, dict):
        scene = empty_scene()
    elements = scene.get("elements")
    app_state = scene.get("appState")
    files = scene.get("files")
    comparable_app_state = (
        {key: app_state[key] for key in PERSISTED_SCENE_APP_STATE_KEYS if key in app_state}
        if isinstance(app_state, dict)
        else {}
    )
    return {
        "elements": elements if isinstance(elements, list) else [],
        "appState": comparable_app_state,
        "files": files if isinstance(files, dict) else {},
    }


def scene_matches(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return json.dumps(scene_for_compare(left), sort_keys=True, separators=(",", ":")) == json.dumps(
        scene_for_compare(right),
        sort_keys=True,
        separators=(",", ":"),
    )


def get_collab_document(
    db: Session,
    *,
    whiteboard_id: str,
) -> WhiteboardCollabDocument | None:
    return db.scalar(
        select(WhiteboardCollabDocument).where(
            WhiteboardCollabDocument.whiteboard_id == whiteboard_id,
        )
    )


def ensure_collab_session_state(
    db: Session,
    *,
    whiteboard: Whiteboard,
    reset_stale_yjs_state: bool = True,
) -> WhiteboardSceneStateResult:
    room_key = make_whiteboard_room_key(whiteboard.id)
    collab = get_collab_document(db, whiteboard_id=whiteboard.id)
    snapshot_scene = whiteboard.scene or empty_scene()
    if collab is None:
        collab = WhiteboardCollabDocument(
            id=new_id(),
            room_key=room_key,
            whiteboard_id=whiteboard.id,
            snapshot_scene=snapshot_scene,
            last_snapshot_at=whiteboard.updated_at,
        )
        db.add(collab)
        db.flush()
        return WhiteboardSceneStateResult(
            whiteboard_changed=False,
            collab_changed=True,
            collab=collab,
        )

    if collab.snapshot_scene is None:
        collab.snapshot_scene = snapshot_scene
        collab.last_snapshot_at = whiteboard.updated_at
        db.add(collab)
        db.flush()
        return WhiteboardSceneStateResult(
            whiteboard_changed=False,
            collab_changed=True,
            collab=collab,
        )

    if reset_stale_yjs_state and collab.updated_at < whiteboard.updated_at:
        collab.room_key = make_fresh_whiteboard_room_key(whiteboard.id)
        collab.yjs_state = None
        collab.snapshot_scene = snapshot_scene
        collab.last_snapshot_at = whiteboard.updated_at
        db.add(collab)
        db.flush()
        return WhiteboardSceneStateResult(
            whiteboard_changed=False,
            collab_changed=True,
            collab=collab,
        )

    return WhiteboardSceneStateResult(
        whiteboard_changed=False,
        collab_changed=False,
        collab=collab,
    )


def apply_rest_scene_update(
    db: Session,
    *,
    whiteboard: Whiteboard,
    scene: dict[str, Any] | None,
) -> WhiteboardSceneStateResult:
    next_scene = scene or empty_scene()
    if scene_matches(whiteboard.scene or empty_scene(), next_scene):
        return WhiteboardSceneStateResult(
            whiteboard_changed=False,
            collab_changed=False,
            collab=get_collab_document(db, whiteboard_id=whiteboard.id),
        )

    whiteboard.scene = next_scene
    whiteboard.updated_at = utcnow()
    db.add(whiteboard)

    collab = get_collab_document(db, whiteboard_id=whiteboard.id)
    if collab is None:
        return WhiteboardSceneStateResult(
            whiteboard_changed=True,
            collab_changed=False,
            collab=None,
        )

    collab.room_key = make_fresh_whiteboard_room_key(whiteboard.id)
    collab.yjs_state = None
    collab.snapshot_scene = next_scene
    collab.last_snapshot_at = utcnow()
    db.add(collab)
    db.flush()
    return WhiteboardSceneStateResult(
        whiteboard_changed=True,
        collab_changed=True,
        collab=collab,
    )


def apply_collab_snapshot(
    db: Session,
    *,
    whiteboard: Whiteboard,
    scene: dict[str, Any] | None,
    yjs_state: bytes | None,
) -> WhiteboardSceneStateResult:
    next_scene = scene or empty_scene()
    state = ensure_collab_session_state(
        db,
        whiteboard=whiteboard,
        reset_stale_yjs_state=False,
    )
    assert state.collab is not None
    collab = state.collab
    whiteboard_changed = not scene_matches(whiteboard.scene or empty_scene(), next_scene)
    collab_changed = (
        not scene_matches(collab.snapshot_scene or empty_scene(), next_scene)
        or collab.yjs_state != yjs_state
    )

    if whiteboard_changed:
        whiteboard.scene = next_scene
        whiteboard.updated_at = utcnow()
        db.add(whiteboard)
    if whiteboard_changed or collab_changed:
        collab.snapshot_scene = next_scene
        collab.yjs_state = yjs_state
        collab.last_snapshot_at = utcnow()
        db.add(collab)
        db.flush()
        collab_changed = True

    return WhiteboardSceneStateResult(
        whiteboard_changed=whiteboard_changed,
        collab_changed=collab_changed,
        collab=collab,
    )


def persist_runtime_yjs_state(
    session_factory: Any,
    *,
    whiteboard_id: str,
    yjs_state: bytes,
    expected_room_key: str | None = None,
    expected_collab_id: str | None = None,
    timeout_seconds: float | None = None,
) -> WhiteboardPersistenceResult | None:
    """Trusted compatibility or an exact existing-incarnation runtime mutation.

    The hub always supplies both captured values. Neither value deliberately
    preserves the existing trusted helper; it is never a runtime recovery path.
    """
    if expected_room_key is None and expected_collab_id is None:
        _persist_trusted_current_room_state(
            session_factory, whiteboard_id=whiteboard_id, yjs_state=yjs_state
        )
        return None
    identity = persistence_identity(whiteboard_id, expected_collab_id, expected_room_key)
    if type(yjs_state) is not bytes:
        raise WhiteboardPersistenceRefused("invalid_state")
    seconds = (
        get_settings().collab_cleanup_timeout_seconds
        if timeout_seconds is None
        else timeout_seconds
    )
    if type(seconds) not in (float, int) or not isfinite(seconds) or seconds <= 0:
        raise WhiteboardPersistenceRefused("invalid_budget")
    db = session_factory()
    _require_fresh_persistence_session(db)  # Rejected caller work has no cleanup owner.
    result = WhiteboardPersistenceResult("refused", "not_attempted")
    commit_attempted = False
    try:
        connection = db.connection()
        if (
            connection.dialect.name != "postgresql"
            or connection.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
            or getattr(connection.connection.dbapi_connection, "autocommit", False)
        ):
            raise WhiteboardPersistenceRefused("transaction_required")
        with _persistence_sql_deadline(connection, float(seconds)) as refresh_commit:
            db.execute(text("SET LOCAL search_path TO pg_catalog, public, pg_temp"))
            if db.scalar(text("SHOW transaction_isolation")) != "read committed":
                raise WhiteboardPersistenceRefused("transaction_required")
            if db.scalar(text("SHOW transaction_read_only")) != "off":
                raise WhiteboardPersistenceRefused("write_transaction_required")
            # Match native scene-update ordering; keep this board live until COMMIT.
            board_id = db.scalar(
                select(Whiteboard.id)
                .where(
                    Whiteboard.id == identity.whiteboard_id,
                    Whiteboard.trashed_at.is_(None),
                )
                .with_for_update(read=True)
            )
            if board_id is None:
                result = WhiteboardPersistenceResult("refused", "board_unavailable")
            else:
                changed_at = case(
                    (WhiteboardCollabDocument.yjs_state.is_distinct_from(yjs_state), utcnow()),
                    else_=WhiteboardCollabDocument.updated_at,
                )
                saved_id = db.execute(
                    update(WhiteboardCollabDocument)
                    .where(
                        WhiteboardCollabDocument.id == identity.collab_document_id,
                        WhiteboardCollabDocument.whiteboard_id == identity.whiteboard_id,
                        WhiteboardCollabDocument.room_key == identity.room_key,
                    )
                    .values(yjs_state=yjs_state, updated_at=changed_at)
                    .returning(WhiteboardCollabDocument.id)
                    .execution_options(synchronize_session=False)
                ).scalar_one_or_none()
                if saved_id is None:
                    result = WhiteboardPersistenceResult("refused", "incarnation_unavailable")
                else:
                    refresh_commit()
                    commit_attempted = True
                    db.commit()
                    # Capture ACK in this worker, before event removal or Session cleanup.
                    result = WhiteboardPersistenceResult("acknowledged", "commit_acknowledged")
    except BaseException as exc:
        if result.status != "acknowledged":
            rolled_back = _rollback_persistence(db)
            if isinstance(exc, WhiteboardPersistenceRefused) and not commit_attempted:
                result = WhiteboardPersistenceResult("refused", exc.reason)
            elif rolled_back and (not commit_attempted or commit_was_rejected(exc)):
                result = WhiteboardPersistenceResult("rejected", "transaction_rejected")
            else:
                result = WhiteboardPersistenceResult("unknown", "commit_outcome_unknown")
    finally:
        _cleanup_persistence_session(db)
    return result


@dataclass(frozen=True)
class WhiteboardPersistenceIdentity:
    whiteboard_id: str
    collab_document_id: str
    room_key: str


@dataclass(frozen=True)
class WhiteboardPersistenceResult:
    status: str
    reason: str


class WhiteboardPersistenceRefused(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("whiteboard_persistence_refused")


class WhiteboardPersistenceDeadline(TimeoutError):
    def __init__(self):
        super().__init__("whiteboard_persistence_deadline")


def persistence_identity(whiteboard_id, collab_document_id, room_key):
    # These existing String(36) identities are opaque, including native fixture IDs.
    if any(
        type(value) is not str or not value or len(value) > 36
        for value in (whiteboard_id, collab_document_id)
    ):
        raise WhiteboardPersistenceRefused("invalid_identity")
    prefix = make_whiteboard_room_key(whiteboard_id)
    if (
        type(room_key) is not str
        or len(room_key) > 128
        or not (
            room_key == prefix
            or room_key.startswith(prefix + ":")
            and len(room_key) > len(prefix) + 1
        )
    ):
        raise WhiteboardPersistenceRefused("invalid_identity")
    return WhiteboardPersistenceIdentity(whiteboard_id, collab_document_id, room_key)


def _require_fresh_persistence_session(db):
    if (
        not isinstance(db, Session)
        or getattr(db.get_bind, "__func__", None) is not Session.get_bind
    ):
        raise WhiteboardPersistenceRefused("owned_session_required")
    try:
        engine = db.get_bind()
        if not isinstance(engine, Engine) or any(
            db.get_bind(mapper=model) is not engine
            or db.get_bind(clause=select(model.__table__)) is not engine
            for model in (Whiteboard, WhiteboardCollabDocument)
        ):
            raise WhiteboardPersistenceRefused("single_engine_required")
    except Exception:
        raise WhiteboardPersistenceRefused("single_engine_required") from None
    if (
        db.in_transaction()
        or db.in_nested_transaction()
        or db.new
        or db.dirty
        or db.deleted
        or db.identity_map
    ):
        raise WhiteboardPersistenceRefused("fresh_session_required")


def _rollback_persistence(db):
    try:
        db.rollback()
        return True
    except BaseException:
        return False


def _cleanup_persistence_session(db):
    for action in (db.rollback, db.close):
        try:
            action()
        except BaseException:
            try:
                db.invalidate()
            except BaseException:
                pass


@contextmanager
def _persistence_sql_deadline(connection, seconds):
    """Local decreasing PostgreSQL budgets; no driver or network hard-stop claim."""
    deadline = monotonic() + seconds

    def refresh(cursor):
        remaining = int((deadline - monotonic()) * 1000)
        if remaining <= 0:
            raise WhiteboardPersistenceDeadline()
        cursor.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, true), "
            "pg_catalog.set_config('lock_timeout', %s, true)",
            (str(remaining), str(remaining)),
        )

    def before_statement(_conn, cursor, *_):
        refresh(cursor)

    def before_commit(_conn=None):
        with connection.connection.cursor() as cursor:
            refresh(cursor)

    event.listen(connection, "before_cursor_execute", before_statement)
    event.listen(connection, "commit", before_commit)
    try:
        yield before_commit
    finally:
        for name, callback in (
            ("before_cursor_execute", before_statement),
            ("commit", before_commit),
        ):
            try:
                event.remove(connection, name, callback)
            except BaseException:
                pass


def _persist_trusted_current_room_state(session_factory, *, whiteboard_id, yjs_state):
    db = session_factory()
    try:
        whiteboard = db.scalar(select(Whiteboard).where(Whiteboard.id == whiteboard_id))
        if whiteboard is None:
            return
        state = ensure_collab_session_state(
            db,
            whiteboard=whiteboard,
            reset_stale_yjs_state=False,
        )
        assert state.collab is not None
        state.collab.yjs_state = yjs_state
        db.add(state.collab)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
