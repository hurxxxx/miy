from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StatusDefinition:
    slug: str
    name: str
    category: str
    id: str = "status-1"


@dataclass
class TaskListStub:
    status_mode: str = "custom"
    team_id: str | None = "space-1"
    statuses: list[StatusDefinition] = field(default_factory=list)
    space_statuses: list[StatusDefinition] = field(default_factory=list)


@dataclass
class TaskStub:
    status: str
    archived: bool = False
