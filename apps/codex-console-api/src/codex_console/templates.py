"""Saved user requests. Codex, not this module, decides and performs operations."""

import asyncio
import hashlib
import re
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import Depends, Query
from pydantic import Field, model_validator
from sqlalchemy import select

from . import git, store
from .errors import ConsoleError
from .models import Task, TaskTemplate, now
from .schemas import Input, ModelOut, SkillOut, TaskDetail


class TemplateVariable(Input):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=100)
    default: str = Field(default="", max_length=4000)
    required: bool = True


class TemplateDefinition(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    directory: str = Field(default=".", min_length=1, max_length=1000)
    context: str = Field(default="", max_length=16000)
    references: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=20)
    prompt: str = Field(min_length=1, max_length=16000)
    variables: list[TemplateVariable] = Field(default_factory=list, max_length=20)
    stage: Literal["plan", "implement"] = "implement"
    permissions: Literal["ask", "yolo"] = "ask"
    isolate: bool = False
    shared_resources: bool = True
    model: str | None = Field(default=None, max_length=200)
    effort: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def names(self):
        names = [v.name for v in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate input name")
        used = set(re.findall(r"\{\{([a-z][a-z0-9_]*)\}\}", self.prompt + self.context))
        if used - set(names):
            raise ValueError("Declare all prompt inputs")
        if any(not x or len(x) > 1000 for x in self.references + self.skills):
            raise ValueError("Invalid reference or skill")
        return self


class TemplateOut(Input):
    id: str
    version: int
    definition: TemplateDefinition
    archived: bool
    updated_at: str


class TemplateUpdate(Input):
    version: int = Field(ge=1)
    definition: TemplateDefinition
    archived: bool = False


class TemplateRun(Input):
    launch_id: UUID
    version: int = Field(ge=1)
    values: dict[str, str] = Field(default_factory=dict, max_length=20)


class TemplateCatalog(Input):
    skills: list[SkillOut]
    models: list[ModelOut]
    workspace: str


def output(row):
    return dict(
        id=row.id,
        version=row.version,
        definition=row.definition,
        archived=row.archived,
        updated_at=row.updated_at.isoformat(),
    )


def directory(settings, relative):
    root = settings.workspace if relative == "." else git.safe_path(settings.workspace, relative)
    settings.require_allowed_paths(root)
    if not root.is_dir():
        raise ConsoleError("workspace_unavailable", 422)
    return root


def seed(factory):
    common = "Read AGENTS.md and the applicable repository instructions. Preserve unrelated work. "
    choices = [
        (
            "MR 리뷰",
            "MR을 검토하고 우선순위별 개선점을 보고합니다.",
            "mr",
            "MR 번호 또는 URL",
            "Review {{mr}}. Report findings here; do not publish comments or merge.",
            ["mty-mr-review"],
        ),
        (
            "MR 개선·병합",
            "입력한 범위의 개선 또는 병합을 Codex에 요청합니다.",
            "request",
            "MR과 요청할 조치",
            "Perform the explicitly requested MR work: {{request}}. Recheck the current head, "
            "CI, reviews and branch policy before any authorized merge.",
            [],
        ),
        (
            "Upstream 변경 확인",
            "원본 변경점과 현재 프로젝트에 미치는 영향을 확인합니다.",
            None,
            None,
            "Inspect upstream updates not integrated into this repository and explain "
            "their impact. "
            "Do not merge or publish changes.",
            [],
        ),
        (
            "Upstream 반영",
            "선택한 원본 변경을 통합하고 검증합니다.",
            "request",
            "반영할 변경과 게시 범위",
            "Integrate the requested upstream changes: {{request}}. Preserve internal "
            "site changes, "
            "validate conflicts and compatibility, and follow the authorized publication scope.",
            [],
        ),
        (
            "서비스 점검·조치",
            "서비스와 요청할 조치를 입력하면 Codex가 조사·실행합니다.",
            "request",
            "서비스·환경·요청",
            "Inspect and handle this service request: {{request}}. Confirm the exact service and "
            "dependencies, follow owner documentation, and verify the actual resulting state.",
            [],
        ),
        (
            "Codex CLI 호환성 업데이트",
            "설치된 새 CLI에 맞게 콘솔을 수정·검증·반영합니다.",
            None,
            None,
            "Read docs/apps/codex-console/README.md. Identify the installed session Codex CLI and "
            "this independently pinned template runner. Update only the console adapter, generated "
            "contracts, tests and documentation needed to support the installed CLI. "
            "Consult official "
            "OpenAI app-server documentation. Never weaken compatibility, approval or "
            "permission checks. "
            "Run contract tests and real subscription smoke. This request authorizes "
            "committing and "
            "pushing the verified compatibility changes to GitLab origin following branch policy, "
            "and deploying the separate console release with backup and public browser "
            "verification. "
            "Keep this template runner and its pinned binary running throughout the update; do not "
            "restart or replace them during this task. Drain other affected work before restarting "
            "the session/UI services. If validation fails, keep the prior release. Do not upgrade "
            "the system CLI or perform unrelated improvements.",
            ["openai-docs"],
        ),
    ]
    with factory.begin() as db:
        for name, description, key, label, prompt, skills in choices:
            ident = str(uuid5(NAMESPACE_URL, "mty-codex-template:" + name))
            if db.get(TaskTemplate, ident):
                continue
            definition = TemplateDefinition(
                name=name,
                description=description,
                prompt=common + prompt,
                references=["AGENTS.md"],
                skills=skills,
                variables=[TemplateVariable(name=key, label=label)] if key else [],
            )
            db.add(TaskTemplate(id=ident, definition=definition.model_dump()))


def register(app, owner, runtime_for):
    secured = [Depends(owner)]

    @app.get("/api/templates", dependencies=secured, response_model=list[TemplateOut])
    def listing(archived: bool = False):
        with app.state.factory() as db:
            return [
                output(r)
                for r in db.scalars(
                    select(TaskTemplate)
                    .where(TaskTemplate.archived == archived)
                    .order_by(TaskTemplate.updated_at.desc())
                )
            ]

    @app.post("/api/templates", dependencies=secured, response_model=TemplateOut)
    def create(body: TemplateDefinition):
        directory(app.state.settings, body.directory)
        with app.state.factory.begin() as db:
            row = TaskTemplate(definition=body.model_dump())
            db.add(row)
            db.flush()
            return output(row)

    @app.put("/api/templates/{template_id}", dependencies=secured, response_model=TemplateOut)
    def edit(template_id: UUID, body: TemplateUpdate):
        directory(app.state.settings, body.definition.directory)
        with app.state.factory.begin() as db:
            row = db.scalar(
                select(TaskTemplate).where(TaskTemplate.id == str(template_id)).with_for_update()
            )
            if row is None:
                raise ConsoleError("template_not_found", 404)
            if row.version != body.version:
                raise ConsoleError("stale_template", 409)
            row.definition, row.archived = body.definition.model_dump(), body.archived
            row.version += 1
            row.updated_at = now()
            db.flush()
            return output(row)

    @app.get("/api/templates/catalog", dependencies=secured, response_model=TemplateCatalog)
    async def catalog(directory_name: str = Query(default=".", max_length=1000)):
        root = directory(app.state.settings, directory_name)
        runtime = runtime_for(executor="templates")
        rpc = await runtime.authenticated_rpc()
        result = await rpc.call("skills/list", {"cwds": [str(root)], "forceReload": True})
        return dict(
            workspace=str(app.state.settings.workspace),
            models=await runtime.models(rpc),
            skills=[
                {"name": s["name"], "description": s.get("description", "")[:500]}
                for entry in result.get("data", [])
                if entry.get("cwd") == str(root)
                for s in entry.get("skills", [])
                if s.get("enabled")
            ],
        )

    @app.get("/api/templates/{template_id}", dependencies=secured, response_model=TemplateOut)
    def read(template_id: UUID):
        with app.state.factory() as db:
            row = db.get(TaskTemplate, str(template_id))
            if row is None:
                raise ConsoleError("template_not_found", 404)
            return output(row)

    @app.post("/api/templates/{template_id}/run", dependencies=secured, response_model=TaskDetail)
    async def run(template_id: UUID, body: TemplateRun):
        cfg, factory = app.state.settings, app.state.factory
        runtime = runtime_for(executor="templates")
        # Native validation happens before accepting a new task. Existing launches never replay.
        with factory() as db:
            previous = db.scalar(select(Task).where(Task.launch_id == str(body.launch_id)))
            if previous:
                snapshot = previous.template_snapshot
                if (
                    snapshot["template_id"] != str(template_id)
                    or snapshot["version"] != body.version
                    or snapshot["values"] != body.values
                ):
                    raise ConsoleError("duplicate_request", 409)
                return store.detail(factory, previous.id, cfg)
            row = db.get(TaskTemplate, str(template_id))
            if row is None or row.archived:
                raise ConsoleError("template_not_found", 404)
            if row.version != body.version:
                raise ConsoleError("stale_template", 409)
            definition = TemplateDefinition.model_validate(row.definition)
        source = directory(cfg, definition.directory)
        variables = {v.name: body.values.get(v.name, v.default) for v in definition.variables}
        if (
            set(body.values) - set(variables)
            or any(len(v) > 4000 for v in body.values.values())
            or any(v.required and not variables[v.name].strip() for v in definition.variables)
        ):
            raise ConsoleError("invalid_input", 422)

        def render(value):
            return re.sub(r"\{\{([a-z][a-z0-9_]*)\}\}", lambda m: variables[m.group(1)], value)

        request_text = render(definition.prompt)
        reference_hashes = {}
        for path in definition.references:
            content = await asyncio.to_thread(git.read_worktree_file, source, path)
            reference_hashes[path] = hashlib.sha256(content).hexdigest()
        context = render(definition.context)
        if context:
            request_text += "\n\nUser-provided context:\n" + context
        if definition.references:
            request_text += "\n\nRead these reference files relative to the working directory:\n"
            request_text += "\n".join(definition.references)
        if len(request_text) > 32000:
            raise ConsoleError("input_too_large", 422)
        rpc = await runtime.authenticated_rpc()
        skill_inputs = await runtime.skill_inputs(rpc, str(source), definition.skills)
        with factory.begin() as db:
            # Serialize admission with the existing cross-executor resource gate.
            previous = db.scalar(select(Task).where(Task.launch_id == str(body.launch_id)))
            if previous:
                if (
                    previous.template_snapshot["template_id"] != str(template_id)
                    or previous.template_snapshot["version"] != body.version
                    or previous.template_snapshot["values"] != body.values
                ):
                    raise ConsoleError("duplicate_request", 409)
                task_id = previous.id
                created = False
            else:
                current = db.get(TaskTemplate, str(template_id))
                if current.archived or current.version != body.version:
                    raise ConsoleError("stale_template", 409)
                task = Task(
                    title=definition.name,
                    root=str(source),
                    status="starting",
                    executor="templates",
                    launch_id=str(body.launch_id),
                    context={
                        "purpose": "inspection" if definition.shared_resources else "development"
                    },
                    template_snapshot=dict(
                        template_id=str(template_id),
                        version=body.version,
                        definition=definition.model_dump(),
                        values=body.values,
                        resolved_values=variables,
                        text=request_text,
                        reference_hashes=reference_hashes,
                        skills=skill_inputs,
                    ),
                )
                db.add(task)
                db.flush()
                store.changed(db, task, "template.launched")
                task_id, created = task.id, True
        if created:
            try:
                await runtime.submit(
                    task_id,
                    body.launch_id,
                    request_text,
                    definition.stage,
                    model=definition.model,
                    effort=definition.effort,
                    permissions=definition.permissions,
                    skill_names=definition.skills,
                )
            except ConsoleError as exc:
                with factory.begin() as db:
                    task = store.require_task(db, task_id, locked=True)
                    if task.status in ("idle", "starting") and not task.current_operation_id:
                        task.status, task.error_code = "failed", exc.code
                        store.changed(db, task, "template.failed")
                # Persisted failures remain recoverable without replaying a launch.
        return store.detail(factory, task_id, cfg)
