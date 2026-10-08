from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy.orm import Session

from miy_api.domains.meeting import search_hooks as meeting_search_hooks
from miy_api.domains.pms import search_hooks as pms_search_hooks
from miy_api.domains.pms.models import Label
from miy_api.domains.retrieval.projection_fencing import ProjectionEventRef
from miy_api.domains.search.schemas import SearchEntityType


def _projection_event(
    task_id: str,
    *,
    event_sequence: int = 1,
    deleted: bool = False,
) -> ProjectionEventRef:
    return ProjectionEventRef(
        event_sequence=event_sequence,
        resource_type="pms_task",
        resource_id=task_id,
        projection_version=event_sequence,
        retrieval_partition_id="722c2043-fc6f-4446-9811-dc35c263d445",
        change_kind="delete" if deleted else "content",
        desired_state="deleted" if deleted else "active",
        content_checksum=None,
        visibility_checksum=None,
    )


def _record_enqueues(
    monkeypatch: Any,
) -> list[tuple[str, SearchEntityType, str, str, ProjectionEventRef | None]]:
    calls: list[tuple[str, SearchEntityType, str, str, ProjectionEventRef | None]] = []

    def fake_enqueue_search_index_job(
        db: Session,
        *,
        entity_type: SearchEntityType,
        entity_id: str,
        operation: str,
        projection_event: ProjectionEventRef | None = None,
    ) -> None:
        calls.append((entity_type, entity_id, operation, projection_event))

    monkeypatch.setattr(
        pms_search_hooks,
        "enqueue_search_index_job",
        fake_enqueue_search_index_job,
    )
    return calls


def test_enqueue_task_search_index_by_id_skips_missing_task(monkeypatch: Any) -> None:
    calls = _record_enqueues(monkeypatch)
    db = cast(Session, SimpleNamespace(get=lambda *args: None))
    pms_search_hooks.enqueue_task_search_index_by_id(db, task_id="missing-task")
    assert calls == []


def test_enqueue_task_search_index_by_id_delegates_to_search_outbox(monkeypatch: Any) -> None:
    calls = _record_enqueues(monkeypatch)
    db = Session()
    monkeypatch.setattr(
        db,
        "get",
        lambda model, task_id: SimpleNamespace(
            id=task_id,
            retrieval_partition_id="722c2043-fc6f-4446-9811-dc35c263d445",
        ),
    )
    monkeypatch.setattr(
        pms_search_hooks,
        "_record_task_projection_event",
        lambda db, *, task, operation: _projection_event(
            task.id,
            deleted=operation == "delete",
        ),
    )

    pms_search_hooks.enqueue_task_search_index_by_id(
        db,
        task_id="task-1",
        operation="delete",
        projection_event=_projection_event("task-1", deleted=True),
    )
    db.close()

    assert calls == [
        (
            SearchEntityType.PMS_TASK,
            "task-1",
            "delete",
            _projection_event("task-1", deleted=True),
        )
    ]


def test_enqueue_label_task_search_recompute_filters_and_sorts_task_ids(monkeypatch: Any) -> None:
    calls = []
    db = cast(
        Session,
        SimpleNamespace(
            get=lambda model, task_id: SimpleNamespace(
                id=task_id,
                retrieval_partition_id="722c2043-fc6f-4446-9811-dc35c263d445",
            )
        ),
    )
    label = cast(Label, SimpleNamespace(id="label-1", list_id="list-1"))
    task_ids = cast(list[str], ["task-b", "", None, "task-a", "task-a"])
    monkeypatch.setattr(
        pms_search_hooks,
        "_record_task_projection_event",
        lambda db, *, task, operation: calls.append((task.id, operation)),
    )

    pms_search_hooks.enqueue_label_task_search_recompute(
        db,
        label=label,
        task_ids=task_ids,
    )

    assert calls == [("task-a", "upsert"), ("task-b", "upsert")]


def test_task_projection_event_assigns_missing_source_binding(monkeypatch: Any) -> None:
    partition_id = "722c2043-fc6f-4446-9811-dc35c263d445"
    task = SimpleNamespace(id="task-unbound", retrieval_partition_id=None)
    captured: dict[str, Any] = {}

    def fake_assign_company_partition(db: Session, *, target: Any, **kwargs: Any) -> str:
        del db
        assert target is task
        assert kwargs == {"source_namespace": "pms"}
        target.retrieval_partition_id = partition_id
        return partition_id

    def fake_deliver_projection_intent(db: Session, **kwargs: Any) -> None:
        del db
        captured.update(kwargs["intent"].model_dump(mode="json"))

    monkeypatch.setattr(
        pms_search_hooks,
        "assign_company_projection_partition",
        fake_assign_company_partition,
    )
    monkeypatch.setattr(
        pms_search_hooks,
        "deliver_projection_intent",
        fake_deliver_projection_intent,
    )

    with Session() as db:
        result = pms_search_hooks._record_task_projection_event(db, task=task, operation="upsert")

    assert result is None  # Source delivery does not return an accepted Core reference.
    assert task.retrieval_partition_id == partition_id
    assert captured["retrieval_partition_id"] == partition_id
    assert captured["resource_type"] == "pms_task"
    assert captured["resource_id"] == task.id
    assert captured["operation"] == "upsert"
    assert captured["desired_state"] == "active"


def test_meeting_projection_event_assigns_missing_source_binding(monkeypatch: Any) -> None:
    partition_id = "722c2043-fc6f-4446-9811-dc35c263d445"
    meeting = SimpleNamespace(
        id="meeting-unbound",
        retrieval_partition_id=None,
    )
    captured: dict[str, Any] = {}

    def fake_assign_company_partition(db: Session, *, target: Any, **kwargs: Any) -> str:
        del db
        assert target is meeting
        assert kwargs == {"source_namespace": "meeting"}
        target.retrieval_partition_id = partition_id
        return partition_id

    def fake_deliver_projection_intent(db: Session, **kwargs: Any) -> None:
        del db
        captured.update(kwargs["intent"].model_dump(mode="json"))

    monkeypatch.setattr(
        meeting_search_hooks,
        "assign_company_projection_partition",
        fake_assign_company_partition,
    )
    monkeypatch.setattr(
        meeting_search_hooks,
        "deliver_projection_intent",
        fake_deliver_projection_intent,
    )

    with Session() as db:
        result = meeting_search_hooks._record_meeting_projection_event(
            db, meeting=meeting, operation="upsert"
        )

    assert result is None  # Source delivery does not return an accepted Core reference.
    assert meeting.retrieval_partition_id == partition_id
    assert captured["retrieval_partition_id"] == partition_id
    assert captured["resource_type"] == "meeting"
    assert captured["resource_id"] == meeting.id
    assert captured["operation"] == "upsert"
    assert captured["desired_state"] == "active"
