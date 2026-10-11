from __future__ import annotations

from typing import Any


class _Dumpable:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.payload


class _FakeDb:
    def __init__(self, users_by_id: dict[str, Any]) -> None:
        self._users_by_id = users_by_id

    def get(self, model, user_id: str):
        return self._users_by_id.get(user_id)


class _FakeRealtime:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    def publish_user(self, user_id: str, event: dict[str, Any]) -> None:
        self.published.append((user_id, event))
