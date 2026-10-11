from __future__ import annotations

from typing import Any


class _FakeRealtime:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    def publish_user(self, user_id: str, event: dict[str, Any]) -> None:
        self.published.append((user_id, event))
