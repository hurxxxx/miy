from __future__ import annotations

from mty_api.domains.retrieval.partition_adapter_registry import (
    has_retrieval_partition_adapter,
    register_retrieval_partition_adapter,
)


def ensure_retrieval_partition_adapters_registered() -> None:
    from mty_api.domains.docs.source_access import NativeDocSourceAccessAdapter
    from mty_api.domains.files.source_access import FileManagerSourceAccessAdapter
    from mty_api.domains.meeting.source_access import MeetingSourceAccessAdapter
    from mty_api.domains.planner.source_access import PlannerEventSourceAccessAdapter
    from mty_api.domains.pms.source_access import PmsTaskSourceAccessAdapter

    for adapter in (
        NativeDocSourceAccessAdapter(),
        FileManagerSourceAccessAdapter(),
        MeetingSourceAccessAdapter(),
        PlannerEventSourceAccessAdapter(),
        PmsTaskSourceAccessAdapter(),
    ):
        if has_retrieval_partition_adapter(adapter.adapter_id):
            continue
        register_retrieval_partition_adapter(adapter)


__all__ = ["ensure_retrieval_partition_adapters_registered"]
