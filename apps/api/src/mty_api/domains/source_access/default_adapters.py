from __future__ import annotations

from mty_api.domains.source_access.registry import (
    has_source_access_adapter,
    register_source_access_adapter,
)


def ensure_builtin_source_access_adapters_registered() -> None:
    from mty_api.domains.docs.source_access import NativeDocSourceAccessAdapter
    from mty_api.domains.files.source_access import FileManagerSourceAccessAdapter
    from mty_api.domains.meeting.source_access import MeetingSourceAccessAdapter
    from mty_api.domains.planner.source_access import PlannerEventSourceAccessAdapter
    from mty_api.domains.pms.source_access import PmsTaskSourceAccessAdapter

    for adapter in (
        NativeDocSourceAccessAdapter(),
        FileManagerSourceAccessAdapter(),
        MeetingSourceAccessAdapter(),
        PmsTaskSourceAccessAdapter(),
        PlannerEventSourceAccessAdapter(),
    ):
        if all(
            has_source_access_adapter(resource_type) for resource_type in adapter.resource_types
        ):
            continue
        register_source_access_adapter(adapter)


__all__ = ["ensure_builtin_source_access_adapters_registered"]
