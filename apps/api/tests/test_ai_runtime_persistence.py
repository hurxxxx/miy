from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from miy_api.domains.ai.runtime.models import AgentRun, AgentTraceEvent
from miy_api.domains.ai.runtime.persistence import (
    append_trace_event,
)
from miy_api.domains.ai.runtime.retention import scrub_completed_runtime_records
from miy_api.domains.auth.models import User
from miy_api.domains.auth.security import new_id
from miy_api.domains.conversations.models import Conversation
from miy_api.domains.meeting.models import utcnow_naive


@pytest.fixture
def runtime_session_factory(
    monkeypatch: pytest.MonkeyPatch,
    application_postgres_dsn: str,
) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("MIY_POSTGRES_DSN", application_postgres_dsn)
    monkeypatch.setenv("MIY_LLM_HEALTHCHECK_ON_STARTUP", "0")

    from miy_api.core.db import get_engine, get_session_factory
    from miy_api.core.settings import get_settings

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    factory = get_session_factory()
    engine = factory.kw["bind"]
    try:
        yield factory
    finally:
        engine.dispose()
        get_session_factory.cache_clear()
        get_engine.cache_clear()
        get_settings.cache_clear()


def _seed_scope(db: Session) -> tuple[User, Conversation]:
    suffix = new_id()[:8]
    user = User(
        id=new_id(),
        login_id=f"runtime-{suffix}",
        email=f"runtime-{suffix}@miy.local",
        full_name="Runtime Test User",
        password_hash="test",
    )
    db.add_all([user])
    db.flush()
    conversation = Conversation(
        id=new_id(),
        user_id=user.id,
        title="Runtime persistence",
    )
    db.add(conversation)
    db.commit()
    return user, conversation


def _runtime_run(
    *,
    user: User,
    conversation: Conversation,
    status: str = "running",
) -> AgentRun:
    return AgentRun(
        id=new_id(),
        conversation_id=conversation.id,
        requested_by_user_id=user.id,
        status=status,
        runtime_profile="interactive_read",
    )


def _trace_events_by_type(db: Session, run_id: str) -> dict[str, AgentTraceEvent]:
    trace_events = list(
        db.scalars(
            select(AgentTraceEvent)
            .where(AgentTraceEvent.agent_run_id == run_id)
            .order_by(AgentTraceEvent.event_seq)
        )
    )
    return {event.event_type: event for event in trace_events}


def test_trace_event_append_serializes_concurrent_writers(
    runtime_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from miy_api.core.settings import get_settings

    monkeypatch.setenv("MIY_AI_RUNTIME_TRACE_PAYLOAD_MAX_BYTES", "1024")
    get_settings.cache_clear()
    with runtime_session_factory() as db:
        user, conversation = _seed_scope(db)
        run = _runtime_run(user=user, conversation=conversation)
        db.add(run)
        db.commit()
        run_id = run.id
        conversation_id = conversation.id

    first_inserted = Event()
    release_first = Event()

    def append_first() -> int:
        with runtime_session_factory() as db:
            with db.begin():
                event = append_trace_event(
                    db,
                    agent_run_id=run_id,
                    conversation_id=conversation_id,
                    event_type="first",
                    payload={
                        "prompt": "must-not-leak",
                        "nested": [{"token": "must-not-leak", "count": 2}],
                        "result_refs": ["artifact-1"],
                    },
                )
                event_seq = event.event_seq
                first_inserted.set()
                assert release_first.wait(timeout=5)
                return event_seq

    def append_second() -> int:
        assert first_inserted.wait(timeout=5)
        with runtime_session_factory() as db:
            with db.begin():
                event = append_trace_event(
                    db,
                    agent_run_id=run_id,
                    conversation_id=conversation_id,
                    event_type="second",
                    payload={"token": "must-not-leak", "large": "x" * 2048},
                )
                return event.event_seq

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(append_first)
        second = executor.submit(append_second)
        time.sleep(0.2)
        assert not second.done()
        release_first.set()
        event_seqs = [first.result(timeout=5), second.result(timeout=5)]

    assert sorted(event_seqs) == [0, 1]
    with runtime_session_factory() as db:
        stored = list(db.scalars(select(AgentTraceEvent).order_by(AgentTraceEvent.event_seq)))
        assert stored[0].payload_json == {
            "prompt": "[redacted]",
            "nested": [{"token": "[redacted]", "count": 2}],
            "result_refs": ["artifact-1"],
        }
        assert set(stored[1].payload_json) == {"truncated", "reason", "original_size_bytes"}
        assert stored[1].payload_json["truncated"] is True
        assert stored[1].payload_json["reason"] == "payload_too_large"
        assert stored[1].payload_json["original_size_bytes"] > 1024
        assert "must-not-leak" not in str([row.payload_json for row in stored])


def test_scrub_completed_runtime_records_keeps_active_and_recent_runs(
    runtime_session_factory: sessionmaker[Session],
) -> None:
    with runtime_session_factory() as db:
        user, conversation = _seed_scope(db)
        active_run = _runtime_run(
            user=user,
            conversation=conversation,
            status="running",
        )
        old_timestamp = utcnow_naive() - timedelta(days=120)
        active_run.metadata_json = {"keep": True}
        active_run.updated_at = old_timestamp
        db.add(active_run)

        recent_conversation = Conversation(
            id=new_id(),
            user_id=user.id,
            title="Recent runtime persistence",
        )
        db.add(recent_conversation)
        db.flush()
        recent_run = _runtime_run(
            user=user,
            conversation=recent_conversation,
            status="completed",
        )
        recent_run.metadata_json = {"keep": True}
        db.add(recent_run)
        db.commit()

        assert scrub_completed_runtime_records(db, older_than_days=90) == 0
        db.commit()

        assert db.get(AgentRun, active_run.id).metadata_json == {"keep": True}
        assert db.get(AgentRun, recent_run.id).metadata_json == {"keep": True}
