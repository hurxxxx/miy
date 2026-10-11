from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from miy_api.core.db import Base
from miy_api.domains.auth.models import User
from miy_api.domains.notifications import read_service
from miy_api.domains.notifications import visibility as notification_visibility
from miy_api.domains.pms.models import Notification


@pytest.fixture(autouse=True)
def _isolate_read_service_from_source_policy(monkeypatch) -> None:
    """These unit tests exercise read state; source-policy tests own visibility."""

    def _visible(_db, *, user, rows):
        return [row for row in rows if row.user_id == user.id]

    monkeypatch.setattr(notification_visibility, "visible_notifications", _visible)
    monkeypatch.setattr(
        read_service,
        "notification_is_visible",
        lambda _db, *, notification, user: notification.user_id == user.id,
    )


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[User.__table__, Notification.__table__])
    return Session(engine)


def _add_user(session: Session, user_id: str) -> None:
    session.add(
        User(
            id=user_id,
            login_id=user_id,
            email=f"{user_id}@miy.local",
            full_name=user_id.title(),
            password_hash="hash",
            status="active",
        )
    )


def _add_notification(
    session: Session,
    *,
    notification_id: str,
    user_id: str,
    created_at: datetime,
    action_url: str = "/dm/conversations/conversation-1",
    is_read: bool = False,
) -> None:
    session.add(
        Notification(
            id=notification_id,
            user_id=user_id,
            type="test_notification",
            title=f"Notification {notification_id}",
            body="Body",
            source_type="community_post",
            source_id="post-1",
            origin_app_id="community",
            action_url=action_url,
            is_read=is_read,
            created_at=created_at,
        )
    )


def test_notification_visibility_scan_uses_bounded_batches(monkeypatch) -> None:
    session = _session()
    try:
        _add_user(session, "user-1")
        created_at = datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
        for index in range(5):
            _add_notification(
                session,
                notification_id=f"notification-{index}",
                user_id="user-1",
                created_at=created_at + timedelta(minutes=index),
            )
        session.commit()
        user = session.get(User, "user-1")
        assert user is not None
        batch_sizes: list[int] = []

        def _visible(_db, *, user, rows):
            batch_sizes.append(len(rows))
            return [row for row in rows if row.user_id == user.id]

        monkeypatch.setattr(notification_visibility, "visible_notifications", _visible)

        batches = list(
            notification_visibility.iter_visible_notification_batches(
                session,
                user=user,
                statement=select(Notification).order_by(Notification.created_at.desc()),
                batch_size=2,
            )
        )

        assert batch_sizes == [2, 2, 1]
        assert [row.id for batch in batches for row in batch] == [
            "notification-4",
            "notification-3",
            "notification-2",
            "notification-1",
            "notification-0",
        ]
    finally:
        session.close()


class _FakeNotificationPublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish_notification(
        self,
        user_id: str,
        *,
        event_type: str,
        notification: dict[str, Any] | None,
        unread_count: int,
    ) -> None:
        self.published.append(
            {
                "user_id": user_id,
                "event_type": event_type,
                "notification": notification,
                "unread_count": unread_count,
            }
        )
