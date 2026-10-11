from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.access import record_audit_log
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.auth.security import new_id
from miy_api.domains.community.models import (
    CommunityChannel,
    CommunityComment,
    CommunityPost,
)
from miy_api.domains.community.service import DEFAULT_CHANNEL_KEY, ensure_default_channels
from miy_api.domains.docs.models import NativeDoc
from miy_api.domains.meeting.models import Meeting
from miy_api.domains.pms.models import Attachment, Task, TaskList
from miy_api.domains.usage.service import (
    USAGE_EVENT_APP_OPEN,
    USAGE_EVENT_CONTENT_VIEW,
    USAGE_EVENT_SEARCH_QUERY,
    record_usage_event,
)
from miy_api.domains.whiteboard.models import Whiteboard


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap_admin_session(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "full_name": "miy Admin",
            "email": "admin@miy.local",
            "password": "supersecret123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_usage_rows(
    *,
    user_id: str,
) -> None:
    now = utcnow_naive()
    with get_session_factory()() as db:
        doc_id = new_id()
        task_list_id = new_id()
        task_id = new_id()
        db.add(
            NativeDoc(
                id=doc_id,
                owner_id=user_id,
                title="Usage document",
                doc_type="general",
                source_app="docs",
                source_kind="manual",
                generation_kind="human",
                rag_scope="official",
            )
        )
        db.add(
            Whiteboard(
                id=new_id(),
                owner_id=user_id,
                title="Usage whiteboard",
            )
        )
        db.add(
            Meeting(
                id=new_id(),
                organizer_id=user_id,
                title="Usage meeting",
                agenda="",
                start_at=now,
                end_at=now + timedelta(hours=1),
            )
        )
        db.add(
            TaskList(
                id=task_list_id,
                key=f"usage-{task_list_id[:8]}",
                name="Usage list",
                description="",
                created_by_id=user_id,
            )
        )
        db.add(
            Task(
                id=task_id,
                list_id=task_list_id,
                task_number=1,
                title="Usage task",
                description="",
                reporter_id=user_id,
            )
        )
        db.add(
            Attachment(
                id=new_id(),
                task_id=task_id,
                filename="usage.pdf",
                content_type="application/pdf",
                size_bytes=2048,
                storage_key=f"pms/{task_id}/usage.pdf",
                uploaded_by_id=user_id,
            )
        )
        ensure_default_channels(db)
        suggestions_channel = db.scalar(
            select(CommunityChannel).where(CommunityChannel.key == DEFAULT_CHANNEL_KEY)
        )
        assert suggestions_channel is not None
        answered_post_id = new_id()
        unanswered_post_id = new_id()
        db.add_all(
            [
                CommunityPost(
                    id=answered_post_id,
                    channel_id=suggestions_channel.id,
                    author_id=user_id,
                    title="Answered usage suggestion",
                    body="Please improve usage reports.",
                    created_at=now,
                    updated_at=now,
                ),
                CommunityPost(
                    id=unanswered_post_id,
                    channel_id=suggestions_channel.id,
                    author_id=user_id,
                    title="Unanswered usage suggestion",
                    body="Please add dashboard filters.",
                    created_at=now,
                    updated_at=now,
                ),
                CommunityComment(
                    id=new_id(),
                    post_id=answered_post_id,
                    author_id=user_id,
                    body="Acknowledged.",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        record_usage_event(
            db,
            actor_user_id=user_id,
            app_id="docs",
            event_type=USAGE_EVENT_APP_OPEN,
            route_path="/apps/docs",
            source="shell.nav.docs",
        )
        record_usage_event(
            db,
            actor_user_id=user_id,
            app_id="docs",
            event_type=USAGE_EVENT_CONTENT_VIEW,
            content_kind="doc",
            content_id=doc_id,
            content_title="Usage document",
            source="docs.item.view",
        )
        record_usage_event(
            db,
            actor_user_id=user_id,
            app_id="docs",
            event_type=USAGE_EVENT_CONTENT_VIEW,
            content_kind="doc",
            content_id=doc_id,
            content_title="Usage document",
            source="docs.item.view",
        )
        record_usage_event(
            db,
            actor_user_id=user_id,
            app_id="whiteboard",
            event_type=USAGE_EVENT_CONTENT_VIEW,
            content_kind="whiteboard",
            content_id="whiteboard-usage",
            content_title="Usage whiteboard",
            source="whiteboard.item.view",
        )
        record_usage_event(
            db,
            actor_user_id=user_id,
            app_id="docs",
            event_type=USAGE_EVENT_SEARCH_QUERY,
            content_kind="doc",
            source="docs.search",
            metadata={"query_hash": "usage-test", "query_length": 5},
        )
        record_audit_log(
            db,
            actor_user_id=user_id,
            action="llm_call",
            entity_kind="llm_task",
            entity_id="usage-run",
            summary="llm_call source=test pool=local task_kind=chatbot status=ok",
            payload={
                "actor_user_id": user_id,
                "task_kind": "chatbot",
                "model": "local/test-model",
                "status": "ok",
                "latency_ms": 120,
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
        db.commit()
