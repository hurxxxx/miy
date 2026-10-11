from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from dev_accounts import dev_login

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import User
from miy_api.domains.auth.security import new_id
from miy_api.domains.docs.models import DocMeetingAccess, NativeDoc
from miy_api.domains.meeting.models import Meeting


def _create_docs_meeting_access_context(
    client: TestClient,
    *,
    include_revoked: bool = False,
) -> dict[str, object]:
    dev_login(client, "delivery-hub-admin")
    dev_login(client, "delivery-hub-member")

    with get_session_factory()() as db:
        owner = db.scalar(select(User).where(User.email == "delivery-hub-admin@miy.local"))
        recipient = db.scalar(select(User).where(User.email == "delivery-hub-member@miy.local"))
        assert owner is not None
        assert recipient is not None

        meeting = Meeting(
            id=new_id(),
            organizer_id=owner.id,
            title="Docs access grant refactor",
            agenda="",
            start_at=datetime(2026, 5, 20, 1, 0),
            end_at=datetime(2026, 5, 20, 2, 0),
        )
        docs = [
            NativeDoc(
                id=new_id(),
                owner_id=owner.id,
                title=f"Grant doc {index}",
                source_kind="grant_refactor",
            )
            for index in range(2)
        ]
        grants = [
            DocMeetingAccess(
                id=new_id(),
                doc_id=doc.id,
                user_id=recipient.id,
                granted_by_user_id=owner.id,
                granted_by_meeting_id=meeting.id,
                access_level="read",
                reason="meeting_attendee",
            )
            for doc in docs
        ]
        if include_revoked:
            revoked_doc = NativeDoc(
                id=new_id(),
                owner_id=owner.id,
                title="Revoked grant doc",
                source_kind="grant_refactor",
            )
            docs.append(revoked_doc)
            grants.append(
                DocMeetingAccess(
                    id=new_id(),
                    doc_id=revoked_doc.id,
                    user_id=recipient.id,
                    granted_by_user_id=owner.id,
                    granted_by_meeting_id=meeting.id,
                    access_level="read",
                    reason="meeting_attendee",
                    revoked_at=datetime(2026, 5, 20, 3, 0),
                    revoked_by_user_id=owner.id,
                    revoke_reason="already_revoked",
                )
            )

        db.add_all([meeting, *docs, *grants])
        db.commit()
        return {
            "meeting_id": meeting.id,
            "owner_id": owner.id,
            "recipient_id": recipient.id,
            "doc_ids": [doc.id for doc in docs[:2]],
        }
