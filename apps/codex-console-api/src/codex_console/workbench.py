"""Single-owner app lifecycle management on the existing task engine and SQLite store."""

import asyncio
import json
from uuid import UUID

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import select

from . import git, store
from . import workbench_sources as sources
from .build_identity import RELEASE_IDENTITY
from .errors import ConsoleError
from .models import (
    AppBudget,
    DevelopmentUsage,
    DevelopmentUsageMonth,
    Maintenance,
    Task,
    WorkbenchProject,
    now,
)
from .workbench_schemas import (
    AppDescriptor,
    BudgetInput,
    CatalogOut,
    MaintenanceInput,
    MaintenanceOut,
    PlatformOut,
    ProjectInput,
    ProjectOut,
    RuntimeOut,
    UsageOut,
    VerifyMaintenance,
)


def catalog(settings):
    settings.require_allowed_paths(settings.workspace)
    try:
        body = json.loads(
            git.read_worktree_file(
                settings.workspace, "packages/contracts/app-contracts.json", missing_ok=False
            )
        )
        rows = body["apps"]
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("Invalid app list")
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid app entry")
            metadata = row.get("management")
            if not metadata:
                continue
            item = AppDescriptor(
                app_id=row["app_id"], title=row["title"], route_base=row["route_base"], **metadata
            )
            if item.route_base != "/apps/" + item.app_id:
                raise ValueError("Invalid app route")
            for path in item.source_paths:
                git.safe_path(settings.workspace, path)
            if settings.preview_origin:
                item.preview_url = settings.preview_origin + item.route_base
            result.append(item)
        if len({a.app_id for a in result}) != len(result):
            raise ValueError("Duplicate app")
        return result
    except (ValueError, KeyError, TypeError, ValidationError, RecursionError):
        raise ConsoleError("catalog_unavailable", 503) from None


def require_app(settings, app_id):
    item = next((a for a in catalog(settings) if a.app_id == app_id), None)
    if not item:
        raise ConsoleError("app_not_found", 404)
    return item


def validate_context(settings, db, context):
    if not context:
        return context
    context = dict(context)
    project_id = context.get("project_id")
    if project_id:
        project = db.get(WorkbenchProject, project_id)
        if not project or context.get("app_id") not in (None, project.app_id):
            raise ConsoleError("invalid_input", 422)
        context.update(
            project_id=project.id,
            app_id=project.app_id,
            project_summary=project.summary,
            reuse_decision=project.reuse_decision,
            reuse_notes=project.reuse_notes,
        )
    if context.get("app_id"):
        item = next((a for a in catalog(settings) if a.app_id == context["app_id"]), None)
        if not item and not project_id:
            raise ConsoleError("app_not_found", 404)
        unit = item.release_unit if item else "miy-app"
        if context.get("release_unit") not in (None, unit):
            raise ConsoleError("invalid_input", 422)
        context.update(release_unit=unit)
        if item:
            context.update(
                app_title=item.title, source_paths=item.source_paths, summary=item.summary
            )
    if context.get("maintenance_id"):
        row = db.get(Maintenance, context["maintenance_id"])
        if not row or row.app_id != context.get("app_id") or row.state in ("cancelled", "verified"):
            raise ConsoleError("invalid_input", 422)
        context.update(
            maintenance_title=row.title,
            maintenance_notes=row.notes,
            target_revision=row.target_revision,
        )
    return context


def link_task(db, task):
    ref = (task.context or {}).get("maintenance_id")
    if ref:
        row = db.get(Maintenance, ref)
        row.task_id, row.version, row.updated_at = task.id, row.version + 1, now()


def observe_usage(db, task, thread_id, params):
    usage = params.get("tokenUsage")
    breakdown = usage.get("total") if isinstance(usage, dict) else None
    total = breakdown.get("totalTokens") if isinstance(breakdown, dict) else None
    if type(total) is not int or not 0 <= total <= 10**15:
        return
    before = db.get(DevelopmentUsage, thread_id)
    if before is None:
        # Imported and discovered threads may contain historical tokens. Establish a
        # baseline without assigning old usage to the current billing month.
        db.add(DevelopmentUsage(thread_id=thread_id, task_id=task.id, total_tokens=total))
        return
    if total <= before.total_tokens:
        return  # Duplicate/out-of-order events must not charge twice.
    delta = total - before.total_tokens
    before.total_tokens, before.observed_at = total, now()
    month = now().strftime("%Y-%m")
    bucket = db.get(DevelopmentUsageMonth, (thread_id, month))
    if bucket:
        bucket.total_tokens += delta
    else:
        db.add(
            DevelopmentUsageMonth(
                thread_id=thread_id, month=month, task_id=task.id, total_tokens=delta
            )
        )


def maintenance_out(row):
    return MaintenanceOut(**{key: getattr(row, key) for key in MaintenanceOut.model_fields})


def install(app, secured):
    @app.get("/api/workbench/catalog", dependencies=secured, response_model=CatalogOut)
    def read_catalog(request: Request):
        cfg, factory = request.app.state.settings, request.app.state.factory
        items = catalog(cfg)
        status = git.status(cfg.workspace)
        with factory() as db:
            projects = [
                ProjectOut(**{k: getattr(r, k) for k in ProjectOut.model_fields})
                for r in db.scalars(
                    select(WorkbenchProject).order_by(WorkbenchProject.created_at.desc())
                )
            ]
        return CatalogOut(
            items=items,
            projects=projects,
            source_revision=status["head"],
            source_dirty=bool(status["changed"]),
            checked_at=now(),
        )

    @app.post("/api/workbench/projects", dependencies=secured, response_model=ProjectOut)
    def create_project(body: ProjectInput, request: Request):
        exists = any(a.app_id == body.app_id for a in catalog(request.app.state.settings))
        if (body.reuse_decision == "new" and exists) or (
            body.reuse_decision == "extend" and not exists
        ):
            raise ConsoleError("invalid_input", 422)
        with request.app.state.factory.begin() as db:
            row = WorkbenchProject(**body.model_dump())
            db.add(row)
            db.flush()
            return ProjectOut(**{k: getattr(row, k) for k in ProjectOut.model_fields})

    @app.get("/api/workbench/runtime", dependencies=secured, response_model=RuntimeOut)
    async def read_runtime(request: Request):
        return await sources.runtime_catalog(request.app.state.settings, request.app.state.factory)

    @app.get(
        "/api/workbench/apps/{app_id}/maintenance",
        dependencies=secured,
        response_model=list[MaintenanceOut],
    )
    def maintenance_list(app_id: str, request: Request):
        require_app(request.app.state.settings, app_id)
        with request.app.state.factory() as db:
            return [
                maintenance_out(r)
                for r in db.scalars(
                    select(Maintenance)
                    .where(Maintenance.app_id == app_id)
                    .order_by(Maintenance.updated_at.desc())
                )
            ]

    def write_maintenance(app_id, body, request, record_id=None):
        require_app(request.app.state.settings, app_id)
        with request.app.state.factory.begin() as db:
            row = db.get(Maintenance, str(record_id)) if record_id else None
            if record_id and (not row or row.app_id != app_id):
                raise ConsoleError("app_not_found", 404)
            if (row.version if row else 0) != body.version:
                raise ConsoleError("conflict", 409)
            if body.task_id:
                task = store.require_task(db, str(body.task_id))
                if (task.context or {}).get("app_id") != app_id:
                    raise ConsoleError("invalid_input", 422)
            values = body.model_dump(mode="json", exclude={"version"})
            if row:
                for k, value in values.items():
                    setattr(row, k, value)
                row.version += 1
                row.updated_at = now()
                row.verification = None
            else:
                row = Maintenance(app_id=app_id, **values)
                db.add(row)
            db.flush()
            return maintenance_out(row)

    @app.post(
        "/api/workbench/apps/{app_id}/maintenance",
        dependencies=secured,
        response_model=MaintenanceOut,
    )
    def create_maintenance(app_id: str, body: MaintenanceInput, request: Request):
        return write_maintenance(app_id, body, request)

    @app.put(
        "/api/workbench/apps/{app_id}/maintenance/{record_id}",
        dependencies=secured,
        response_model=MaintenanceOut,
    )
    def update_maintenance(app_id: str, record_id: UUID, body: MaintenanceInput, request: Request):
        return write_maintenance(app_id, body, request, record_id)

    @app.post(
        "/api/workbench/apps/{app_id}/maintenance/{record_id}/verify",
        dependencies=secured,
        response_model=MaintenanceOut,
    )
    async def verify_maintenance(
        app_id: str, record_id: UUID, body: VerifyMaintenance, request: Request
    ):
        cfg, factory = request.app.state.settings, request.app.state.factory
        item = require_app(cfg, app_id)
        with factory() as db:
            row = db.get(Maintenance, str(record_id))
            if not row or row.app_id != app_id:
                raise ConsoleError("app_not_found", 404)
            if row.version != body.version:
                raise ConsoleError("conflict", 409)
            target = row.target_revision
            if not target or row.state == "cancelled":
                raise ConsoleError("verification_unavailable", 409)
        runtime, pipeline = await asyncio.gather(
            sources.runtime_catalog(cfg, factory, fresh=True),
            sources.verified_pipeline(cfg, target),
        )
        installed = next((a for a in runtime.items if a.app_id == app_id), None)
        current_installation = (
            bool(
                RELEASE_IDENTITY
                and not RELEASE_IDENTITY["source_dirty"]
                and RELEASE_IDENTITY["source_revision"] == target
            )
            if item.release_unit == "miy-workbench"
            else not runtime.stale
            and installed is not None
            and installed.installed_revision == target
        )
        if not current_installation or not pipeline:
            raise ConsoleError("verification_unavailable", 409)
        with factory.begin() as db:
            row = db.get(Maintenance, str(record_id))
            if row.version != body.version or row.target_revision != target:
                raise ConsoleError("conflict", 409)
            row.state, row.version, row.updated_at = "verified", row.version + 1, now()
            row.verification = {
                **pipeline,
                "installed_revision": target,
                "installation_checked_at": (
                    now().isoformat()
                    if item.release_unit == "miy-workbench"
                    else runtime.checked_at.isoformat()
                ),
            }
            return maintenance_out(row)

    @app.put(
        "/api/workbench/apps/{app_id}/budget", dependencies=secured, response_model=BudgetInput
    )
    def budget(app_id: str, body: BudgetInput, request: Request):
        require_app(request.app.state.settings, app_id)
        with request.app.state.factory.begin() as db:
            row = db.get(AppBudget, app_id)
            if (row.version if row else 0) != body.version:
                raise ConsoleError("conflict", 409)
            if not row:
                row = AppBudget(app_id=app_id)
                db.add(row)
            for key, value in body.model_dump().items():
                setattr(row, key, value)
            row.version = body.version + 1
            db.flush()
            return BudgetInput(**{k: getattr(row, k) for k in BudgetInput.model_fields})

    @app.get("/api/workbench/apps/{app_id}/usage", dependencies=secured, response_model=UsageOut)
    async def usage(app_id: str, request: Request):
        cfg, factory = request.app.state.settings, request.app.state.factory
        require_app(cfg, app_id)
        remote = await sources.runtime_usage(cfg, factory, app_id)
        month = now().strftime("%Y-%m")
        with factory() as db:
            tasks = list(
                db.scalars(select(Task).where(Task.context["app_id"].as_string() == app_id))
            )
            ids = [t.id for t in tasks]
            samples = list(
                db.scalars(
                    select(DevelopmentUsageMonth).where(
                        DevelopmentUsageMonth.task_id.in_(ids), DevelopmentUsageMonth.month == month
                    )
                )
            )
            reported = {s.task_id for s in samples}
            development = sum(s.total_tokens for s in samples) if samples else None
            row = db.get(AppBudget, app_id)
            budget = (
                BudgetInput(**{k: getattr(row, k) for k in BudgetInput.model_fields})
                if row
                else BudgetInput()
            )
            overdue = db.scalar(
                select(Maintenance.id)
                .where(
                    Maintenance.app_id == app_id,
                    Maintenance.state.in_(("open", "planned")),
                    Maintenance.due_on < now().date().isoformat(),
                )
                .limit(1)
            )
        alerts = []
        if any(t.status in ("failed", "uncertain") for t in tasks):
            alerts.append("task_failed")
        if overdue:
            alerts.append("patch_overdue")
        if (
            budget.development_tokens
            and development is not None
            and development > budget.development_tokens
        ):
            alerts.append("development_budget_exceeded")
        data = remote.get("data")
        if remote["state"] == "ready" and data:
            if (
                budget.runtime_tokens
                and data.get("total_tokens") is not None
                and data["total_tokens"] > budget.runtime_tokens
            ):
                alerts.append("runtime_budget_exceeded")
            if data.get("llm_errors"):
                alerts.append("runtime_errors")
            if (
                budget.amount_minor
                and data.get("amount_minor") is not None
                and data.get("currency") == budget.currency
                and data["amount_minor"] > budget.amount_minor
            ):
                alerts.append("cost_budget_exceeded")
        return UsageOut(
            month=month,
            development_tokens=development,
            development_tasks=len(tasks),
            unreported_tasks=len(set(ids) - reported),
            runtime=data,
            runtime_state=remote["state"],
            runtime_checked_at=remote.get("checked_at"),
            stale=remote["state"] != "ready",
            budget=budget,
            alerts=alerts,
        )

    @app.get("/api/workbench/platform", dependencies=secured, response_model=PlatformOut)
    async def platform(request: Request):
        cfg, factory = request.app.state.settings, request.app.state.factory
        cfg.require_allowed_paths(cfg.workspace)

        def local():
            try:
                status = git.status(cfg.workspace)
                lines = (
                    git.git(cfg.workspace, "log", "-20", "--format=%H%x00%s")
                    .decode("utf-8", "replace")
                    .splitlines()
                )
                commits = [
                    {"revision": a, "subject": b[:200]}
                    for line in lines
                    if "\0" in line
                    for a, b in [line.split("\0", 1)]
                ]
                trees = (
                    git.git(cfg.workspace, "worktree", "list", "--porcelain")
                    .decode("utf-8", "replace")
                    .splitlines()
                )
                return (
                    status,
                    commits,
                    [s.removeprefix("worktree ") for s in trees if s.startswith("worktree ")],
                )
            except ConsoleError:
                return None, [], []

        (status, commits, trees), remote = await asyncio.gather(
            asyncio.to_thread(local), sources.gitlab(cfg, factory)
        )
        return PlatformOut(
            git=status,
            commits=commits,
            worktrees=trees,
            gitlab=remote,
            workbench_release=RELEASE_IDENTITY,
        )
