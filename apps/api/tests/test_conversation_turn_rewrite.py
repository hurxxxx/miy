from __future__ import annotations

from dataclasses import dataclass

import pytest

from miy_api.domains.conversations.turn_rewrite import (
    ConversationTailRewriteError,
    plan_conversation_tail_rewrite,
)


@dataclass(frozen=True)
class Turn:
    id: str
    seq: int
    role: str
    content: str


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        (
            {
                "target_turn_id": "user-0",
                "from_seq": 0,
                "expected_tail_turn_id": "stale-tail",
                "expected_tail_seq": 1,
                "persist_user_turn": True,
                "replacement_user_content": "new",
                "expected_retry_user_content": "new",
            },
            "ai.conversation_rewrite_tail_mismatch",
        )
    ],
)
def test_plan_rejects_stale_or_invalid_rewrites(kwargs: dict[str, object], code: str) -> None:
    with pytest.raises(ConversationTailRewriteError) as exc_info:
        plan_conversation_tail_rewrite(
            turns=[
                Turn(id="user-0", seq=0, role="user", content="old"),
                Turn(id="assistant-1", seq=1, role="assistant", content="answer"),
            ],
            current_title="old",
            **kwargs,
        )

    assert exc_info.value.code == code
