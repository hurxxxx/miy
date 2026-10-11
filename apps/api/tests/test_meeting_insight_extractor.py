from __future__ import annotations

from types import SimpleNamespace

from dev_accounts import dev_login
from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.access import load_user_graph
from miy_api.domains.auth.security import new_id
from miy_api.domains.meeting.models import (
    Meeting,
    MeetingAttendee,
    MeetingRecording,
)
from miy_api.domains.planner.event_time import parse_iso_or_date


def _dev_login(client: TestClient, account_key: str) -> dict:
    return dev_login(client, account_key)


def _create_meeting_and_recording(
    client: TestClient,
    *,
    recording_id: str | None = None,
) -> tuple[dict, str]:
    session = _dev_login(client, "delivery-hub-admin")
    with get_session_factory()() as db:
        user = load_user_graph(db, session["user"]["id"])
        assert user is not None

        meeting = Meeting(
            id=new_id(),
            organizer_id=user.id,
            title="Insight Source Meeting",
            agenda="AI insight extraction",
            start_at=parse_iso_or_date("2026-05-20T01:00:00+00:00"),
            end_at=parse_iso_or_date("2026-05-20T02:00:00+00:00"),
            status="scheduled",
        )
        db.add(meeting)
        db.flush()
        db.add(
            MeetingAttendee(
                id=new_id(),
                meeting_id=meeting.id,
                user_id=user.id,
                role="required",
                response="accepted",
            )
        )
        recording = MeetingRecording(
            id=recording_id or new_id(),
            meeting_id=meeting.id,
            storage_key=f"meeting-recordings/{meeting.id}/recording.webm",
            duration_sec=120,
            file_size=256,
            mime_type="audio/webm",
            idempotency_key=f"idem-{meeting.id}",
            uploaded_by_id=user.id,
            source="manual_upload",
            transcription_status="done",
            progress_pct=100,
            transcript_text="로그인 플로우를 정리하고 후속 회의를 잡자.",
            summary_text="액션과 후속 회의가 필요하다.",
        )
        db.add(recording)
        db.commit()
        return session, recording.id


def _response_with_content(content: str):
    return SimpleNamespace(completion=SimpleNamespace(text=content))
