"""Bounded agent summaries; Git receipts are verified by the host, never by prose."""

import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from . import agents, git, store, task_environments, task_git, task_history
from .errors import ConsoleError
from .models import Event, Operation, TaskMilestone, now
from .schemas import ExecutionOptions, TaskDetail, TaskHistoryItem

TOOL_NAME = "miy_task_timeline"
Phase = Literal["start", "implementation", "validation", "integration", "finish"]
State = Literal["in_progress", "needs_attention", "completed"]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["list", "update", "verify_merge"]
    key: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,99}$")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    phase: Phase | None = None
    state: State | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    evidence_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def shape(self):
        if self.action != "list" and not self.key:
            raise ValueError("A segment key is required")
        if self.action == "update" and not all((self.title, self.phase, self.state, self.summary)):
            raise ValueError("An update requires title, phase, state and summary")
        if self.action != "update" and any(
            (self.title, self.phase, self.state, self.summary, self.evidence_ids)
        ):
            raise ValueError("Summary fields are only accepted for update")
        return self


def specs():
    return [
        {
            "type": "function",
            "name": TOOL_NAME,
            "description": "Maintain concise task work segments. List when resuming to reuse keys "
            "and obtain task-scoped evidence IDs. Update the same key and phase at meaningful "
            "transitions, with real validation outcomes and blockers; avoid per-command calls. "
            "Use a new key for follow-up work after completion. Summaries are agent reports, not "
            "proof. A merge request supplies its key; verify_merge checks live Git ancestry before "
            "closing that segment. Never claim a merge from prose or a successful turn. This tool "
            "does not execute Git, close the conversation, authorize work, or expose credentials.",
            "inputSchema": Arguments.model_json_schema(),
        }
    ]


class PhaseOut(BaseModel):
    state: State
    summary: str
    evidence_ids: list[int]
    updated_at: str


class MergeTarget(BaseModel):
    source_root: str
    source_branch: str | None
    source_head: str
    target_root: str
    target_branch: str
    target_head: str


class MergeOut(MergeTarget):
    verified: bool = False
    verified_at: str | None = None
    integrated_head: str | None = None
    source_commit: str | None = None
    error_code: str | None = None


class MilestoneOut(BaseModel):
    id: str
    key: str
    title: str
    state: State
    phases: dict[Phase, PhaseOut]
    merge: MergeOut | None
    created_at: str
    updated_at: str
    evidence: list[TaskHistoryItem]


class TimelinePage(BaseModel):
    items: list[MilestoneOut]
    next_before: str | None = None


class MergeInput(ExecutionOptions):
    operation_id: UUID
    link_id: str = Field(min_length=1, max_length=36)
    expected_head: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    expected_branch: str | None = Field(default=None, max_length=200)
    expected_target_head: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    expected_target_branch: str = Field(min_length=1, max_length=200)


def require_host(settings, task):
    if any((task.context or {}).get(k) for k in ("source_binding", "app_id", "project_id")):
        raise ConsoleError("path_denied", 403)
    settings.require_allowed_paths(task.root, settings.workspace)


def segment(db, task, key):
    return db.scalar(
        select(TaskMilestone).where(
            TaskMilestone.task_id == task.id,
            TaskMilestone.key == key,
        )
    )


def output(db, row):
    ids = {id for p in row.phases.values() for id in p["evidence_ids"]}
    evidence = list(
        db.scalars(select(Event).where(Event.task_id == row.task_id, Event.id.in_(ids)))
    )
    return dict(
        id=row.id,
        key=row.key,
        title=row.title,
        state=row.state,
        phases=row.phases,
        merge=MergeOut.model_validate(row.merge).model_dump() if row.merge else None,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        evidence=[
            dict(id=e.id, event=e.kind, created_at=e.created_at.isoformat(), details=e.details)
            for e in evidence
        ],
    )


def page(db, task, before=None):
    query = select(TaskMilestone).where(TaskMilestone.task_id == task.id)
    if before:
        anchor = db.get(TaskMilestone, before)
        if not anchor or anchor.task_id != task.id:
            raise ConsoleError("invalid_input", 422)
        query = query.where(
            (TaskMilestone.created_at < anchor.created_at)
            | ((TaskMilestone.created_at == anchor.created_at) & (TaskMilestone.id < anchor.id))
        )
    rows = list(
        db.scalars(
            query.order_by(TaskMilestone.created_at.desc(), TaskMilestone.id.desc()).limit(31)
        )
    )
    return dict(
        items=[output(db, row) for row in rows[:30]],
        next_before=rows[29].id if len(rows) > 30 else None,
    )


def note(db, task, row):
    row.updated_at = now()
    store.changed(db, task, "task.timeline.updated", details={"segment_id": row.id})


def execute(db, settings, task, args):
    require_host(settings, task)
    if args.action == "list":
        return {
            **page(db, task),
            "recent_evidence": task_history.page(db, task.id, limit=30)["items"],
        }
    row = segment(db, task, args.key)
    if args.action == "verify_merge":
        if not row or not row.merge:
            raise ConsoleError("merge_request_required", 409)
        verify(db, settings, task, row)
        return output(db, row)
    if row and row.state == "completed":
        previous = row.phases.get(args.phase)
        if (
            previous
            and all(previous[k] == getattr(args, k) for k in ("state", "summary", "evidence_ids"))
            and row.title == args.title
        ):
            return output(db, row)
        raise ConsoleError("timeline_segment_completed", 409)
    if (
        row
        and row.merge
        and not row.merge.get("verified")
        and args.phase in ("integration", "finish")
        and args.state == "completed"
    ):
        raise ConsoleError("merge_verification_required", 409)
    for id in args.evidence_ids:
        evidence = db.get(Event, id)
        if (
            not evidence
            or evidence.task_id != task.id
            or evidence.kind in task_history.NOISE
            or not evidence.details
            or evidence.details.get("visible") is False
        ):
            raise ConsoleError("timeline_evidence_unavailable", 422)
    if not row:
        if args.key.startswith("merge:"):
            raise ConsoleError("merge_request_required", 409)
        row = TaskMilestone(task_id=task.id, key=args.key, title=args.title, phases={})
        db.add(row)
        db.flush()
    entry = dict(state=args.state, summary=args.summary, evidence_ids=args.evidence_ids)
    previous = row.phases.get(args.phase, {})
    if row.title == args.title and all(previous.get(k) == v for k, v in entry.items()):
        return output(db, row)
    row.title = args.title
    row.phases = {**row.phases, args.phase: {**entry, "updated_at": now().isoformat()}}
    blocked = any(p["state"] == "needs_attention" for p in row.phases.values())
    finished = (args.phase == "finish" and args.state == "completed") or (
        row.merge and row.merge.get("verified")
    )
    row.state = "needs_attention" if blocked else "completed" if finished else "in_progress"
    note(db, task, row)
    return output(db, row)


def target(db, settings, task, link_id):
    require_host(settings, task)
    source = task_git.resolve(db, settings, task, link_id)
    if not source:
        raise ConsoleError("git_unavailable", 409)
    common, metadata = task_git.validate(settings, task, source)
    dest = settings.workspace
    dest_common, dest_metadata = task_git.identity(dest)
    settings.require_allowed_paths(dest_common, dest_metadata)
    a, b = git.status(source), git.status(dest)
    if source == dest or common != dest_common or not b.get("branch") or not a.get("head"):
        raise ConsoleError("merge_target_unavailable", 409)
    return dict(
        source_root=str(source),
        source_branch=a.get("branch"),
        source_head=a["head"],
        source_changed=a["changed"],
        target_root=str(dest),
        target_branch=b["branch"],
        target_head=b["head"],
        common_dir=common,
        source_git_dir=metadata,
        target_git_dir=dest_metadata,
        link_id=link_id,
        verified=False,
    )


def verify(db, settings, task, row):
    operation = db.get(Operation, row.key.removeprefix("merge:"))
    if not operation or operation.task_id != task.id or operation.state != "accepted":
        raise ConsoleError("merge_request_required", 409)
    if row.merge.get("verified"):
        return
    data = dict(row.merge)
    try:
        live = target(db, settings, task, data["link_id"])
        for key in (
            "source_root",
            "target_root",
            "target_branch",
            "common_dir",
            "source_git_dir",
            "target_git_dir",
        ):
            if live[key] != data[key]:
                raise ConsoleError("merge_workspace_changed", 409)
        if data["source_branch"] and live["source_branch"] != data["source_branch"]:
            raise ConsoleError("merge_workspace_changed", 409)
        if live["source_changed"] or (
            data["source_changed"] and live["source_head"] == data["source_head"]
        ):
            raise ConsoleError("merge_source_unfinished", 409)
        root = Path(live["target_root"])
        # Full object IDs only, with replacements and lazy fetch disabled by the Git adapter.
        for ancestor, descendant in (
            (data["source_head"], live["source_head"]),
            (data["target_head"], live["target_head"]),
            (live["source_head"], live["target_head"]),
        ):
            git.git(root, "merge-base", "--is-ancestor", ancestor, descendant)
        data.update(
            verified=True,
            verified_at=now().isoformat(),
            source_commit=live["source_head"],
            integrated_head=live["target_head"],
            error_code=None,
        )
        row.state = (
            "needs_attention"
            if any(p["state"] == "needs_attention" for p in row.phases.values())
            else "completed"
        )
    except ConsoleError as exc:
        data["error_code"] = "merge_not_verified" if exc.code == "git_unavailable" else exc.code
        row.state = "needs_attention"
    row.merge = data
    note(db, task, row)


def prompt(row):
    d = row.merge
    snapshot = {k: d[k] for k in MergeTarget.model_fields}
    return (
        "선택한 작업 변경을 아래 개발 체크아웃의 브랜치로 병합해 주세요. "
        "먼저 AGENTS.md와 저장소 지침, 현재 Git 상태를 확인하고 "
        "필수 검사와 리뷰/PR 절차를 지켜 주세요. "
        "다른 작업의 변경은 보존하세요. "
        "이 요청은 개발 병합에 필요한 브랜치 준비, 작업 커밋과 병합을 "
        "요청합니다. 별도의 푸시/배포/삭제 권한을 추가하지 않습니다. "
        "요청 시점과 경로나 브랜치가 달라졌으면 임의로 대상을 바꾸지 말고 확인해 주세요. "
        "분리된 HEAD 또는 미커밋 변경은 이 작업 범위만 확인해 준비하세요. "
        "충돌이나 검사 실패가 해결되지 않으면 완료로 보고하지 마세요. "
        "miy_task_timeline 도구가 있으면 아래 key로 단계별 요약과 검사 근거를 남기고 "
        "병합 후 verify_merge를 호출하세요. "
        "도구가 없으면 최종 응답에 결과와 커밋, 검사 결과를 남기세요. "
        "작업 대화는 후속 작업을 위해 유지합니다.\n"
        + json.dumps({"key": row.key, "checkout_snapshot": snapshot}, ensure_ascii=False)
    )


def install(app, secured, runtime_for):
    @app.get("/api/tasks/{task_id}/timeline", dependencies=secured, response_model=TimelinePage)
    def timeline(task_id: str, before: UUID | None = None):
        with app.state.factory() as db:
            task = store.require_task(db, task_id)
            return page(db, task, str(before) if before else None)

    @app.get("/api/tasks/{task_id}/merge-target", dependencies=secured, response_model=MergeTarget)
    def merge_target(task_id: str, link_id: str = Query(max_length=36)):
        with app.state.factory() as db:
            return target(db, app.state.settings, store.require_task(db, task_id), link_id)

    @app.post("/api/tasks/{task_id}/merge", dependencies=secured, response_model=TaskDetail)
    async def request_merge(task_id: str, body: MergeInput):
        runtime = runtime_for(task_id)
        # Admission is through Runtime.start (never steering into an unrelated active turn).
        async with runtime.task_gate(task_id):

            def prepare():
                with app.state.factory.begin() as db:
                    task = runtime.require_task(db, task_id)
                    runtime.require_allowed_task(task)
                    require_host(app.state.settings, task)
                    allowed = task_environments.implementation_permissions(app.state.settings, task)
                    if allowed is not None and body.permissions not in allowed:
                        raise ConsoleError("permission_denied", 403)
                    key = "merge:" + str(body.operation_id)
                    row = segment(db, task, key)
                    request_data = body.model_dump(mode="json")
                    if row:
                        if row.merge["request"] != request_data:
                            raise ConsoleError("duplicate_request", 409)
                        return prompt(row)
                    if task.status in (*store.ACTIVE, "uncertain") or agents.busy_descendants(
                        db, task.id
                    ):
                        raise ConsoleError("task_busy", 409)
                    data = target(db, app.state.settings, task, body.link_id)
                    if (
                        data["source_head"],
                        data["source_branch"],
                        data["target_head"],
                        data["target_branch"],
                    ) != (
                        body.expected_head,
                        body.expected_branch,
                        body.expected_target_head,
                        body.expected_target_branch,
                    ):
                        raise ConsoleError("merge_workspace_changed", 409)
                    data["request"] = request_data
                    row = TaskMilestone(
                        task_id=task.id,
                        key=key,
                        title=(
                            f"{data['source_branch'] or data['source_head'][:8]}"
                            f" → {data['target_branch']}"
                        ),
                        phases={},
                        merge=data,
                        state="in_progress",
                    )
                    db.add(row)
                    db.flush()
                    note(db, task, row)
                    return prompt(row)

            text = await asyncio.to_thread(prepare)
        try:
            await runtime.start(
                task_id,
                body.operation_id,
                text,
                "implement",
                model=body.model,
                effort=body.effort,
                permissions=body.permissions,
            )
        except ConsoleError as exc:
            with app.state.factory.begin() as db:
                task = store.require_task(db, task_id)
                row = segment(db, task, "merge:" + str(body.operation_id))
                if row and not row.merge.get("verified"):
                    row.state = "needs_attention"
                    row.merge = {**row.merge, "error_code": exc.code}
                    note(db, task, row)
            raise
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post(
        "/api/tasks/{task_id}/timeline/{segment_id}/verify",
        dependencies=secured,
        response_model=MilestoneOut,
    )
    async def verify_from_ui(task_id: str, segment_id: UUID):
        runtime = runtime_for(task_id)
        async with runtime.task_gate(task_id):

            def check():
                with app.state.factory.begin() as db:
                    task = runtime.require_task(db, task_id)
                    runtime.require_allowed_task(task)
                    require_host(app.state.settings, task)
                    if task.status in (*store.ACTIVE, "uncertain") or agents.busy_descendants(
                        db, task.id
                    ):
                        raise ConsoleError("task_busy", 409)
                    row = db.get(TaskMilestone, str(segment_id))
                    if not row or row.task_id != task.id or not row.merge:
                        raise ConsoleError("merge_request_required", 404)
                    operation = db.get(Operation, row.key.removeprefix("merge:"))
                    if not operation or operation.state != "accepted":
                        raise ConsoleError("merge_request_required", 409)
                    verify(db, app.state.settings, task, row)
                    return output(db, row)

            return await asyncio.to_thread(check)


def settle(factory, settings, task_id):
    """Best-effort completion receipt for old threads without the dynamic tool."""
    with factory.begin() as db:
        task = store.require_task(db, task_id)
        if task.status in (*store.ACTIVE, "uncertain") or agents.busy_descendants(db, task.id):
            return
        row = segment(db, task, "merge:" + str(task.current_operation_id))
        if row and row.merge and not row.merge.get("verified"):
            if task.status == "idle":
                verify(db, settings, task, row)
            else:
                row.state = "needs_attention"
                row.merge = {**row.merge, "error_code": task.error_code or "execution_interrupted"}
                note(db, task, row)
