from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from miy_api.core.db import get_engine
from miy_api.domains.ai.runtime.models import AgentInvocation, AgentRun, AgentTraceEvent
from miy_api.domains.auth.models import User
from miy_api.domains.auth.security import new_id
from miy_api.domains.conversations.models import Conversation
from miy_api.domains.meeting.models import utcnow_naive


def _seed_old_terminal_runtime_payload(admin_user_id: str) -> tuple[str, str, str]:
    old_timestamp = utcnow_naive() - timedelta(days=120)
    with Session(get_engine()) as db:
        admin_user = db.get(User, admin_user_id)
        assert admin_user is not None

        conversation = Conversation(
            id=new_id(),
            user_id=admin_user.id,
            title="Runtime retention",
            created_at=old_timestamp,
            updated_at=old_timestamp,
        )
        run = AgentRun(
            id=new_id(),
            conversation_id=conversation.id,
            requested_by_user_id=admin_user.id,
            status="completed",
            runtime_profile="grounded_report",
            graph_enabled=True,
            metadata_json={"prompt": "must-not-leak"},
            created_at=old_timestamp,
            updated_at=old_timestamp,
        )
        db.add(conversation)
        db.flush()
        db.add(run)
        db.flush()

        invocation = AgentInvocation(
            id=new_id(),
            agent_run_id=run.id,
            conversation_id=conversation.id,
            invocation_seq=0,
            agent_id="graph.adapter.node_runner",
            status="completed",
            purpose="retention test",
            usage_json={"tokens": 12},
            error="Authorization: Bearer must-not-leak",
            created_at=old_timestamp,
            updated_at=old_timestamp,
        )
        db.add(invocation)
        db.flush()

        trace_event = AgentTraceEvent(
            id=new_id(),
            agent_run_id=run.id,
            agent_invocation_id=invocation.id,
            conversation_id=conversation.id,
            run_seq=0,
            invocation_seq=0,
            event_seq=0,
            event_type="run_completed",
            payload_json={"prompt": "must-not-leak"},
            created_at=old_timestamp,
        )
        db.add(trace_event)
        db.commit()
        return run.id, invocation.id, trace_event.id
