from __future__ import annotations

from datetime import UTC, datetime


def _dt(day: int, hour: int) -> datetime:
    return datetime(2026, 5, day, hour, tzinfo=UTC).replace(tzinfo=None)
