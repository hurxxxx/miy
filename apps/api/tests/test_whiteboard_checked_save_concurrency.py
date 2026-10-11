"""Checked-save concurrency against disposable migrated PostgreSQL authority.

Actual row blockers, caller COMMIT/rollback and historical receipts are observed;
no native service, operational role/config, customer fixture or factory is used.
The shared yielding fixtures own databases, roles and connection cleanup.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_prepared_official_http_auth import (
    authority as authority,  # noqa: F401
)
from test_prepared_official_http_auth import (
    bound_official as bound_official,  # noqa: F401
)
from test_prepared_official_http_auth import (
    client as client,  # noqa: F401
)
from test_prepared_official_http_auth import (
    http_world as http_world,  # noqa: F401
)
from test_prepared_official_http_auth import (
    isolated_data_cluster as isolated_data_cluster,  # noqa: F401
)
from test_prepared_official_http_auth import (
    role_template as role_template,  # noqa: F401
)
from test_whiteboard_actor_acl_writer import (
    _seed,
)
from test_whiteboard_actor_acl_writer import (
    acl_boundary as acl_boundary,  # noqa: F401
)
from test_whiteboard_actor_writer import (
    _wait_for_blocker,
)
from test_whiteboard_actor_writer import (
    actor_boundary as actor_boundary,  # noqa: F401
)
from whiteboard_checked_fixture import (
    checked_boundary as checked_boundary,  # noqa: F401
)
from whiteboard_checked_fixture import (
    checked_prepared as checked_prepared,  # noqa: F401
)
from whiteboard_checked_fixture import (
    content,
    ledger,
    resolve,
    seal,
    stage,
)

from miy_api.domains.auth.models import AuthSession
from miy_api.domains.independent_apps.models import AppSession
from miy_api.domains.official_apps.whiteboard_actor_writer import capture_whiteboard_write_execution
from miy_api.domains.whiteboard.checked_save import WhiteboardCheckedWriterRefused
from miy_api.domains.whiteboard.models import WhiteboardCollabDocument


def _bounded(db):
    db.execute(text("SET LOCAL statement_timeout='8s'"))
    db.execute(text("SET LOCAL lock_timeout='7s'"))
    return db.scalar(text("SELECT pg_backend_pid()"))


def _call(engine, ready, operation):
    """The test caller owns and observes this actual transaction's COMMIT."""
    with Session(engine) as db:
        ready.put(_bounded(db))
        result = operation(db)
        db.commit()
        return result


def _refused(operation):
    with pytest.raises(WhiteboardCheckedWriterRefused) as caught:
        operation()
    assert str(caught.value) == "whiteboard_checked_writer_refused"
    return caught.value.reason


def _second_original_execution(c):
    """Capture a distinct real synthetic delegation, never forge a descriptor."""
    source_id = str(uuid4())
    delegated_token = "checked-synthetic-" + uuid4().hex
    delegated_digest = hashlib.sha256(delegated_token.encode()).hexdigest()
    expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
    with Session(c.engine) as db:
        original = db.get(AppSession, c.execution.delegated_token_digest)
        db.add(
            AuthSession(
                id=source_id,
                user_id=c.execution.actor_user_id,
                token_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                expires_at=expiry,
            )
        )
        db.flush()
        db.add(
            AppSession(
                token_hash=delegated_digest,
                installation_id=original.installation_id,
                source_session_id=source_id,
                generation=original.generation,
                permissions=list(original.permissions),
                expires_at=expiry,
            )
        )
        db.commit()
    return capture_whiteboard_write_execution(
        c.world.factory,
        token=delegated_token,
        original_user_id=c.execution.actor_user_id,
        original_source_session_id=source_id,
    )


def test_selected_share_revocation_after_real_wait_never_stages_a_save(checked_prepared):
    c = checked_prepared
    _seed(c, "direct_edit")
    attempt = seal(c)
    before = content(c)
    with c.connect(autocommit=True) as observer, c.connect() as revoker:
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        revoker.execute(
            "SELECT 1 FROM whiteboard_user_shares WHERE whiteboard_id=%s AND user_id=%s FOR UPDATE",
            (c.board_id, c.execution.actor_user_id),
        )
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call, c.source_engine, ready, lambda db: stage(c, db, attempt))
            try:
                _wait_for_blocker(observer, ready.get(timeout=5), revoker_pid)
                revoker.execute(
                    "DELETE FROM whiteboard_user_shares WHERE whiteboard_id=%s AND user_id=%s",
                    (c.board_id, c.execution.actor_user_id),
                )
                revoker.commit()
                _refused(lambda: future.result(timeout=5))
            finally:
                revoker.rollback()
    assert content(c) == before
    assert ledger(c, attempt)[:3] == ("sealed", None, None)


@pytest.mark.parametrize("first_finish", ["commit", "rollback"])
def test_same_base_cas_competition_has_one_successful_content_revision(
    checked_prepared, first_finish
):
    c = checked_prepared
    before = content(c)
    first = seal(c, yjs=b"first-writer")
    second = seal(c, yjs=b"second-writer")
    with c.connect(autocommit=True) as observer, Session(c.source_engine) as first_db:
        first_pid = _bounded(first_db)
        staged = stage(c, first_db, first)
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call, c.source_engine, ready, lambda db: stage(c, db, second))
            try:
                _wait_for_blocker(observer, ready.get(timeout=5), first_pid)
                assert not future.done()
                getattr(first_db, first_finish)()
                if first_finish == "commit":
                    _refused(lambda: future.result(timeout=5))
                else:
                    winner = future.result(timeout=5)
                    assert winner.content_revision == before[1] + 1
            finally:
                first_db.rollback()
    live = content(c)
    assert live[0] == before[0] and live[1] == before[1] + 1
    if first_finish == "commit":
        assert live[2] == b"first-writer"
        assert ledger(c, first)[:3] == (
            "committed",
            staged.content_incarnation_id,
            staged.content_revision,
        )
        assert ledger(c, second)[:3] == ("sealed", None, None)
    else:
        assert live[2] == b"second-writer"
        assert ledger(c, first)[:3] == ("sealed", None, None)
        assert ledger(c, second)[0] == "committed"


@pytest.mark.parametrize("mutation", ["content_restore", "delete_recreate"])
def test_same_content_bytes_cannot_hide_revision_or_incarnation_aba(checked_prepared, mutation):
    c = checked_prepared
    original = content(c)
    attempt = seal(c)
    with Session(c.engine) as core:
        if mutation == "delete_recreate":
            core.delete(core.get(WhiteboardCollabDocument, c.collab_id))
            core.flush()
            core.add(
                WhiteboardCollabDocument(
                    id=c.collab_id,
                    whiteboard_id=c.board_id,
                    room_key=c.room_key,
                    yjs_state=original[2],
                    snapshot_scene=original[3],
                )
            )
            core.commit()
        else:
            field = "yjs_state" if mutation == "content_restore" else "room_key"
            temporary = (
                b"temporary-history"
                if mutation == "content_restore"
                else "temporary-" + uuid4().hex
            )
            prior = original[2] if mutation == "content_restore" else c.room_key
            core.execute(
                text(f"UPDATE whiteboard_collab_documents SET {field}=:value WHERE id=:id"),
                {"value": temporary, "id": c.collab_id},
            )
            core.commit()
            core.execute(
                text(f"UPDATE whiteboard_collab_documents SET {field}=:value WHERE id=:id"),
                {"value": prior, "id": c.collab_id},
            )
            core.commit()
    changed = content(c)
    assert changed[2:4] == original[2:4]
    if mutation == "delete_recreate":
        assert changed[0] != original[0] and changed[1] == 0
    else:
        assert changed[0] == original[0] and changed[1] == original[1] + 2
    with Session(c.source_engine) as db:
        _refused(lambda: stage(c, db, attempt))
        db.rollback()
    assert content(c) == changed
    assert ledger(c, attempt)[:3] == ("sealed", None, None)


@pytest.mark.parametrize("save_finish", ["commit", "rollback"])
def test_unknown_save_resolves_only_after_the_original_attempt_lock(checked_prepared, save_finish):
    c = checked_prepared
    before = content(c)
    attempt = seal(c)
    with c.connect(autocommit=True) as observer, Session(c.source_engine) as saver:
        source_pid = _bounded(saver)
        staged = stage(c, saver, attempt)
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call, c.core_engine, ready, lambda db: resolve(c, db, attempt))
            try:
                _wait_for_blocker(observer, ready.get(timeout=5), source_pid)
                assert not future.done()
                assert content(c) == before
                assert ledger(c, attempt)[:3] == ("sealed", None, None)
                getattr(saver, save_finish)()
                resolution = future.result(timeout=5)
            finally:
                saver.rollback()
    if save_finish == "commit":
        assert resolution.state == "committed" and resolution.receipt == staged
        historical = resolution.receipt
        with Session(c.engine) as core:
            core.execute(
                text("UPDATE whiteboard_collab_documents SET yjs_state=:value WHERE id=:id"),
                {"value": b"later-committed-history", "id": c.collab_id},
            )
            core.commit()
        with Session(c.core_engine) as core:
            again = resolve(c, core, attempt)
            core.commit()
        assert again.receipt == historical
        assert content(c)[1] > historical.content_revision
    else:
        assert resolution.state == "cancelled_not_committed" and resolution.receipt is None
        assert content(c) == before
        with Session(c.source_engine) as db:
            _refused(lambda: stage(c, db, attempt))
            db.rollback()


def test_resolver_timeout_never_proves_cancellation_or_commit(checked_prepared):
    c = checked_prepared
    before = content(c)
    attempt = seal(c)
    with Session(c.source_engine) as saver:
        _bounded(saver)
        staged = stage(c, saver, attempt)
        with Session(c.core_engine) as resolver:
            resolver.execute(text("SET LOCAL lock_timeout='100ms'"))
            assert _refused(lambda: resolve(c, resolver, attempt)) == "current_resolve_unavailable"
            resolver.rollback()
        assert content(c) == before
        assert ledger(c, attempt)[:3] == ("sealed", None, None)
        saver.commit()
    with Session(c.core_engine) as resolver:
        historical = resolve(c, resolver, attempt)
        resolver.commit()
    assert historical.state == "committed" and historical.receipt == staged


@pytest.mark.parametrize("resolve_finish", ["commit"])
def test_locked_cancellation_fences_a_late_queued_saver_only_after_real_commit(
    checked_prepared, resolve_finish
):
    c = checked_prepared
    before = content(c)
    attempt = seal(c)
    with c.connect(autocommit=True) as observer, Session(c.core_engine) as resolver:
        resolver_pid = _bounded(resolver)
        cancellation = resolve(c, resolver, attempt)
        assert cancellation.state == "cancelled_not_committed"
        assert ledger(c, attempt)[:3] == ("sealed", None, None)
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call, c.source_engine, ready, lambda db: stage(c, db, attempt))
            try:
                _wait_for_blocker(observer, ready.get(timeout=5), resolver_pid)
                assert not future.done()
                getattr(resolver, resolve_finish)()
                if resolve_finish == "commit":
                    _refused(lambda: future.result(timeout=5))
                else:
                    saved = future.result(timeout=5)
                    assert saved.content_revision == before[1] + 1
            finally:
                resolver.rollback()
    if resolve_finish == "commit":
        assert content(c) == before
        assert ledger(c, attempt)[:3] == ("cancelled_not_committed", None, None)
    else:
        assert content(c)[1] == before[1] + 1
        assert ledger(c, attempt)[0] == "committed"
