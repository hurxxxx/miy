from __future__ import annotations

from miy_api.core.db import get_session_factory
from miy_api.core.i18n import localized_http_exception
from miy_api.core.realtime import RealtimeEvent
from miy_api.domains.auth.dependencies import resolve_auth_context_from_token
from miy_api.domains.dm.realtime_access import authorize_dm_realtime_event
from miy_api.domains.notifications.realtime_access import (
    authorize_notification_realtime_event,
)


def authorize_user_event(event: RealtimeEvent, *, token: str, user_id: str) -> RealtimeEvent | None:
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None
    if not event_type.startswith(("dm.", "notification.", "notifications.")):
        return event
    with get_session_factory()() as db:
        context = resolve_auth_context_from_token(db, token, update_last_seen=False)
        if context.user.id != user_id:
            raise localized_http_exception(status_code=401, code="auth.required")
        if event_type.startswith("dm."):
            return authorize_dm_realtime_event(db, user=context.user, event=event)
        return authorize_notification_realtime_event(db, user=context.user, event=event)
