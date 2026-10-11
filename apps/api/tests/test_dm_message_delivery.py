from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


NOW = datetime(2026, 5, 21, 12, 0, 0)


class _FakeDb:
    def __init__(self) -> None:
        self.added = []
        self.added_batches = []
        self.refreshed = []
        self.commit_count = 0

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)

    def add_all(self, rows) -> None:  # noqa: ANN001
        self.added_batches.append(list(rows))

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, row) -> None:  # noqa: ANN001
        self.refreshed.append(row)


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email=f"{user_id}@example.test")
