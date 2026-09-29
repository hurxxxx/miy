from __future__ import annotations

from mty_api.domains.auth.models import User
from mty_api.domains.dm import participants, thread_projection
from mty_api.domains.dm.models import DmConversation


def dm_conversation_display_name(conversation: DmConversation, current_user_id: str) -> str:
    return thread_projection.conversation_display_name(
        conversation,
        current_user_id=current_user_id,
        active_participants=participants.active_participants(conversation),
    )


def dm_user_name(user: User) -> str:
    return thread_projection.user_display_name(user)
