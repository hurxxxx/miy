"""Advisory project executor metadata observation; never native task authority."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import app_sources, executor_probe, workbench
from .config import AppExecutionEnvironment
from .errors import ConsoleError
from .models import AppSourceBinding, WorkbenchProject
from .workbench_schemas import ProjectExecutionReadinessOut


@dataclass(frozen=True)
class Selection:
    app_id: str
    binding: dict = field(repr=False)
    manifest_digest: str
    environment: AppExecutionEnvironment = field(repr=False)


def _select(settings, factory, project_id):
    with factory() as db:
        project = db.get(WorkbenchProject, project_id)
        if project is None:
            raise ConsoleError("app_not_found", 404)
        selected = db.get(AppSourceBinding, project.app_id)
        if selected is None:
            return project.app_id, None
        _, digest = app_sources.read_manifest(settings, selected.repository_root, project.app_id)
        # Reuse the same current source/catalog policy as actual Task creation.
        context = workbench.validate_context(
            settings, db, {"project_id": project_id, "purpose": "development"}
        )
        binding = context.get("source_binding")
        if not binding:
            raise ConsoleError("app_source_unavailable", 422)
        workbench.context_root(settings, context)
        environment = next(
            (
                item
                for item in settings.app_execution_environments
                if item.key == binding["remote_environment_key"]
            ),
            None,
        )
        if environment is None:
            raise ConsoleError("app_executor_unavailable", 503)
        return project.app_id, Selection(
            project.app_id, binding, digest, environment.model_copy(deep=True)
        )


_SOURCE_ERRORS = {
    "app_source_unavailable": "unconfigured",
    "app_source_invalid": "unavailable",
    "app_source_changed": "changed",
    "app_source_denied": "denied",
    "app_source_git_policy": "denied",
    "app_executor_unavailable": "unconfigured",
    "catalog_unavailable": "unavailable",
}
_PROBE_ERRORS = {
    "executor_version_mismatch": ("unsupported", "app_executor_version_mismatch"),
    "executor_root_mismatch": ("changed", "app_executor_changed"),
}


async def read(settings, factory, project_id):
    """Read only initialize metadata, then discard results for changed bindings."""
    app_id = None
    selected = None

    def result(state, code=None):
        return ProjectExecutionReadinessOut(
            project_id=project_id,
            app_id=app_id,
            source_version=selected.binding["version"] if selected else None,
            state=state,
            failure_code=code,
            checked_at=datetime.now(UTC),
        )

    try:
        app_id, selected = await asyncio.to_thread(_select, settings, factory, project_id)
    except ConsoleError as error:
        if error.status == 404:
            raise
        return result(_SOURCE_ERRORS.get(error.code, "unavailable"), _safe_source_code(error.code))
    if selected is None:
        return result("unconfigured", "app_source_unavailable")

    try:
        # This existing pinned public protocol client has a 10s/64KiB bound and
        # sends initialize/initialized only: no process/fs/thread or policy probes.
        await executor_probe.preflight(selected.environment)
    except executor_probe.ProbeFailure as error:
        state, code = _PROBE_ERRORS.get(str(error), ("unavailable", "app_executor_unavailable"))
        return result(state, code)
    except Exception:
        # Never expose transport messages, endpoint configuration or peer data.
        return result("unavailable", "app_executor_unavailable")

    try:
        _, current = await asyncio.to_thread(_select, settings, factory, project_id)
    except ConsoleError:
        return result("changed", "app_executor_changed")
    if current != selected:
        return result("changed", "app_executor_changed")
    return result("reachable")


def _safe_source_code(code):
    return code if code in _SOURCE_ERRORS else "app_source_unavailable"
