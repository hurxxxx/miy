from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace


NOW = datetime(2026, 5, 21, 12, 0, 0)


def _user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _participant(user_id: str, *, left_at=None) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id, left_at=left_at)
