import asyncio
import contextlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, unquote_to_bytes, urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import ClientDisconnect

from . import agents, attachments, auth, git, host, miy_sso, monitor, routing, store, templates
from .config import Settings
from .errors import ConsoleError
from .models import Agent, Event, Task, database
from .rpc import CodexRPC
from .runtime import Runtime
from .schemas import (
    DOCUMENT_CHAR_LIMIT,
    MESSAGE_CHAR_LIMIT,
    AccountOut,
    AgentOut,
    Answer,
    AttachmentOut,
    ChangeOut,
    DeviceLoginOut,
    DiffOut,
    DocumentInput,
    GitStatusOut,
    Implement,
    ImportThread,
    LoginInput,
    Message,
    MessageBody,
    MIYSessionInput,
    ModelOut,
    NewTask,
    Ok,
    Recover,
    ServiceOut,
    SessionOut,
    SkillOut,
    TaskDetail,
    TaskOut,
    TaskPreferences,
    ThreadPage,
)


def _authenticated_response(settings, request: Request, token: str, csrf: str) -> JSONResponse:
    response = JSONResponse({"authenticated": True})
    if settings.base_path:
        # Clear cookies left by a previous root-path installation. Browsers send both
        # paths, and duplicate cookie names otherwise make session selection ambiguous.
        response.delete_cookie(auth.COOKIE, path="/")
        response.delete_cookie(auth.CSRF_COOKIE, path="/")
    for name, value, httponly in ((auth.COOKIE, token, True), (auth.CSRF_COOKIE, csrf, False)):
        response.set_cookie(
            name,
            value,
            max_age=settings.session_hours * 3600,
            httponly=httponly,
            secure=urlsplit(request.headers["origin"]).scheme == "https",
            samesite="strict",
            path=settings.base_path or "/",
        )
    return response


def create_app(settings=None, *, rpc_factory=CodexRPC, role="combined"):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings()
        app.root_path = app.state.settings.base_path
        engine, factory = database(app.state.settings.database_url)
        app.state.factory = factory
        app.state.upload_slots = asyncio.Semaphore(2)
        from .storage import SCHEMA, process_guard

        guard = contextlib.ExitStack()
        runtime = None
        template_runtime = None
        observer = None
        host_observer = None
        try:
            guard.enter_context(process_guard(app.state.settings.database_url, role))
            with engine.connect() as connection:
                revision = connection.scalar(
                    text("SELECT version_num FROM console_alembic_version")
                )
            if revision != SCHEMA:
                raise RuntimeError("Run codex-console migrate before starting the server")
            if role != "management":
                executor = "templates" if role == "templates" else "session"
                runtime_settings = app.state.settings
                if role == "templates":
                    if not runtime_settings.template_binary:
                        raise RuntimeError("Configure a pinned template runner binary")
                    runtime_settings = runtime_settings.model_copy(
                        update={"binary": str(runtime_settings.template_binary)}
                    )
                store.recover_startup(factory, executor)
                runtime = Runtime(runtime_settings, factory, rpc_factory, executor=executor)
                app.state.runtime = runtime
            if role in ("combined", "management"):
                observer = asyncio.create_task(monitor.observe(app.state.settings, factory))
                host_observer = asyncio.create_task(host.observe(app.state.settings, factory))
            if role == "combined":
                store.recover_startup(factory, "templates")
                template_settings = app.state.settings
                if template_settings.template_binary:
                    template_settings = template_settings.model_copy(
                        update={"binary": str(template_settings.template_binary)}
                    )
                template_runtime = Runtime(
                    template_settings, factory, rpc_factory, executor="templates"
                )
                app.state.template_runtime = template_runtime
            if role in ("combined", "management"):
                templates.seed(factory)
            if role in ("combined", "management") and app.state.settings.web_dist.is_dir():
                app.mount(
                    "/",
                    StaticFiles(directory=app.state.settings.web_dist, html=True),
                    name="console-web",
                )
            yield
        finally:
            if host_observer:
                host_observer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await host_observer
            if observer:
                observer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await observer
            if runtime:
                await runtime.close()
            if template_runtime:
                await template_runtime.close()
            guard.close()
            engine.dispose()

    app = FastAPI(
        title="Codex Console",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ConsoleError)
    async def console_error(request, exc):
        return JSONResponse({"code": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo a password or a submitted prompt in validation errors.
        return JSONResponse({"code": "invalid_input"}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def conflict_error(request, exc):
        return JSONResponse({"code": "conflict"}, status_code=409)

    @app.middleware("http")
    async def boundaries(request, call_next):
        cfg = request.app.state.settings
        try:
            host = urlsplit("//" + request.headers.get("host", "")).hostname
        except ValueError:
            host = None
        allowed_host = urlsplit(cfg.origin).hostname
        if not host or host not in (allowed_host, "127.0.0.1", "localhost", "::1"):
            return JSONResponse({"code": "host_denied"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin", "")
            if origin not in (cfg.origin, cfg.local_origin) or (
                request.headers.get("host", "").lower() != urlsplit(origin).netloc.lower()
            ):
                return JSONResponse({"code": "origin_denied"}, status_code=403)
            upload = request.method == "PUT" and re.fullmatch(
                r"/api/tasks/[0-9a-f-]{36}/attachments/[0-9a-f-]{36}",
                request.url.path.removeprefix(cfg.base_path),
            )
            if not upload:
                path = request.url.path.removeprefix(cfg.base_path)
                char_limit = (
                    DOCUMENT_CHAR_LIMIT
                    if request.method == "PUT"
                    and re.fullmatch(r"/api/tasks/[0-9a-f-]{36}/documents", path)
                    else MESSAGE_CHAR_LIMIT
                    if request.method == "POST"
                    and re.fullmatch(r"/api/tasks/[0-9a-f-]{36}/(messages|steer|implement)", path)
                    else None
                )
                # A Unicode code point can occupy 12 JSON bytes as an escaped
                # surrogate pair. Reserve bounded space for the remaining fields.
                byte_limit = char_limit * 12 + 4096 if char_limit else 128 * 1024
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > byte_limit:
                        return JSONResponse({"code": "input_too_large"}, status_code=413)
                request._body = bytes(body)
        try:
            path = request.url.path.removeprefix(cfg.base_path)
            if path.startswith(("/api/tasks", "/api/codex", "/api/templates")):
                owner(request)
            target = routing.execution_target(app.state.factory, path, request.query_params)
            if target and role == "management":
                owner(request)
                response = await routing.forward(request, target)
            elif target and role in ("session", "templates") and target != role:
                response = JSONResponse({"code": "executor_mismatch"}, status_code=409)
            else:
                response = await call_next(request)
        except ConsoleError as exc:
            response = JSONResponse({"code": exc.code}, status_code=exc.status)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'; worker-src 'self' blob:"
        )
        if request.url.path.removeprefix(cfg.base_path).startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def owner(request: Request):
        csrf = (
            None if request.method in ("GET", "HEAD") else request.headers.get("x-csrf-token", "")
        )
        if not auth.authenticate(request.app.state.factory, request.cookies.get(auth.COOKIE), csrf):
            raise ConsoleError("unauthenticated", 401)

    def runtime_for(task_id=None, *, executor=None):
        if task_id:
            with app.state.factory() as db:
                executor = store.require_task(db, str(task_id)).executor
        if executor == "templates" and role == "combined":
            return app.state.template_runtime
        runtime = app.state.runtime
        if executor and runtime.executor != executor:
            raise ConsoleError("executor_mismatch", 409)
        return runtime

    templates.register(app, owner, runtime_for)
    secured = [Depends(owner)]

    @app.get("/api/monitor/host", dependencies=secured, response_model=host.HostOut)
    def host_status():
        return host.snapshot(app.state.factory)

    @app.get("/api/monitor/services", dependencies=secured, response_model=list[ServiceOut])
    def service_status():
        return monitor.snapshot(app.state.settings, app.state.factory)

    @app.patch("/api/overview/{task_id}", dependencies=secured, response_model=Ok)
    def preferences(task_id: UUID, body: TaskPreferences):
        with app.state.factory.begin() as db:
            task = store.require_task(db, str(task_id), locked=True)
            task.pinned = body.pinned
            store.changed(db, task, "task.preferences")
        return {"ok": True}

    @app.get("/healthz", response_model=Ok)
    def health():
        return {"ok": True}

    @app.get("/api/session", response_model=SessionOut)
    def session(request: Request):
        return {
            "authenticated": auth.authenticate(app.state.factory, request.cookies.get(auth.COOKIE))
        }

    @app.post("/api/session", response_model=SessionOut)
    def login(body: LoginInput, request: Request):
        cfg = app.state.settings
        result = auth.login(app.state.factory, body.password, cfg.session_hours)
        if result is None:
            raise ConsoleError("login_failed", 401)
        token, csrf = result
        return _authenticated_response(cfg, request, token, csrf)

    @app.post("/api/session/miy", response_model=SessionOut)
    @app.post("/api/session/mty", response_model=SessionOut, include_in_schema=False)
    def login_from_miy(body: MIYSessionInput, request: Request):
        cfg = app.state.settings
        expected_subject = cfg.sso_subjects.get(body.issuer)
        if expected_subject is None:
            raise ConsoleError("login_failed", 401)
        subject = miy_sso.exchange_code(issuer=body.issuer, code=body.code)
        if subject != str(expected_subject):
            raise ConsoleError("login_failed", 401)
        token, csrf = auth.create_session(app.state.factory, cfg.session_hours)
        return _authenticated_response(cfg, request, token, csrf)

    @app.delete("/api/session", dependencies=secured, response_model=Ok)
    def logout(request: Request):
        with app.state.factory.begin() as db:
            db.execute(
                delete(auth.WebSession).where(
                    auth.WebSession.token_hash == auth.digest(request.cookies[auth.COOKIE])
                )
            )
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.COOKIE, path=app.state.settings.base_path or "/")
        response.delete_cookie(auth.CSRF_COOKIE, path=app.state.settings.base_path or "/")
        return response

    @app.get("/api/codex/account", dependencies=secured, response_model=AccountOut)
    async def account():
        return await app.state.runtime.account()

    @app.get("/api/codex/models", dependencies=secured, response_model=list[ModelOut])
    async def models(task_id: str | None = Query(default=None, max_length=36)):
        return await runtime_for(task_id).models(task_id=task_id)

    @app.post("/api/codex/login", dependencies=secured, response_model=DeviceLoginOut)
    async def codex_login():
        rpc = await app.state.runtime.connect()
        result = await rpc.call("account/login/start", {"type": "chatgptDeviceCode"})
        url = result.get("verificationUrl", "")
        if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "auth.openai.com":
            raise ConsoleError("login_url_invalid", 502)
        return {
            "login_id": result["loginId"],
            "verification_url": url,
            "user_code": result["userCode"],
        }

    @app.get("/api/codex/threads", dependencies=secured, response_model=ThreadPage)
    async def threads(
        search: str = Query(default="", max_length=200),
        cursor: str | None = Query(default=None, max_length=4096),
    ):
        rpc = await app.state.runtime.authenticated_rpc()
        root = str(app.state.settings.workspace)
        result = await rpc.call(
            "thread/list",
            {
                "cwd": root,
                "searchTerm": search or None,
                "cursor": cursor,
                "limit": 30,
                "sortKey": "updated_at",
                "archived": False,
            },
        )
        return {
            "items": [
                {
                    "id": row["id"],
                    "title": (row.get("name") or row.get("preview") or "Codex")[:200],
                    "preview": row.get("preview", "")[:500],
                    "updated_at": row["updatedAt"],
                }
                for row in result.get("data", [])
                if row.get("cwd") == root
            ],
            "cursor": result.get("nextCursor"),
        }

    @app.post("/api/tasks/import", dependencies=secured, response_model=TaskDetail)
    async def import_thread(body: ImportThread):
        runtime = app.state.runtime
        async with runtime.gate:
            rpc = await runtime.authenticated_rpc()
            result = await rpc.call(
                "thread/read", {"threadId": body.thread_id, "includeTurns": True}
            )
            thread = result["thread"]
            if Path(thread.get("cwd", "/")).resolve() != app.state.settings.workspace:
                raise ConsoleError("path_denied", 403)
            if (thread.get("status") or {}).get("type") == "active":
                raise ConsoleError("turn_not_finished")
            with app.state.factory.begin() as db:
                linked = agents.task_for_thread(db, body.thread_id)
                if linked and linked.thread_id != body.thread_id:
                    raise ConsoleError("thread_owned", 409)
                existing = db.scalar(select(Task).where(Task.thread_id == body.thread_id))
                if existing:
                    runtime.require_task(db, existing.id)
                    task_id = existing.id
                else:
                    task = Task(
                        title=(thread.get("name") or thread.get("preview") or "Codex")[:200],
                        thread_id=body.thread_id,
                        root=str(app.state.settings.workspace),
                    )
                    db.add(task)
                    db.flush()
                    store.reconcile_history(db, task, thread.get("turns", []))
                    store.changed(db, task, "thread.imported")
                    task_id = task.id
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.get("/api/overview", dependencies=secured, response_model=list[TaskOut])
    @app.get("/api/tasks", dependencies=secured, response_model=list[TaskOut])
    def tasks(search: str = Query(default="", max_length=200), template_id: UUID | None = None):
        with app.state.factory() as db:
            query = select(Task)
            if template_id is not None:
                query = query.where(
                    Task.executor == "templates",
                    Task.template_snapshot["template_id"].as_string() == str(template_id),
                )
            if search.strip():
                query = query.where(
                    func.lower(Task.title).contains(search.strip().lower(), autoescape=True)
                )
            recent = list(db.scalars(query.order_by(Task.updated_at.desc(), Task.id).limit(200)))
            tracked = db.scalars(
                query.where(
                    or_(
                        Task.pinned.is_(True),
                        Task.status.in_((*store.ACTIVE, "uncertain", "failed")),
                        Task.id.in_(
                            select(Agent.task_id).where(
                                Agent.parent_thread_id.is_not(None),
                                Agent.status.not_in(
                                    ("completed", "interrupted", "errored", "shutdown")
                                ),
                            )
                        ),
                    )
                )
            )
            return [
                store.task_out(task, db) for task in {t.id: t for t in [*recent, *tracked]}.values()
            ]

    @app.post("/api/tasks", dependencies=secured, response_model=TaskDetail)
    def new_task(body: NewTask):
        context = body.context.model_dump() if body.context else None
        if context and context.get("service_id"):
            service = next(
                (s for s in monitor.services(app.state.settings) if s.id == context["service_id"]),
                None,
            )
            if not service:
                raise ConsoleError("invalid_input", 422)
            context.update({"environment": service.environment, "service_name": service.name})
            context["observation"] = next(
                s
                for s in monitor.snapshot(app.state.settings, app.state.factory)
                if s["id"] == service.id
            )
        with app.state.factory.begin() as db:
            task = Task(title=body.title, root=str(app.state.settings.workspace), context=context)
            db.add(task)
            db.flush()
            if body.isolate:
                cfg = app.state.settings
                root, isolated = git.prepare_workspace(
                    cfg.workspace,
                    task.id,
                    None,
                    base_ref=cfg.worktree_base_ref,
                    worktree_root=cfg.worktree_root,
                    validate_target=cfg.require_allowed_paths,
                    force_isolated=True,
                )
                task.root, task.worktree_owned = str(root), isolated
            store.changed(db, task, "task.created")
            task_id = task.id
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.get("/api/tasks/{task_id}/agents", dependencies=secured, response_model=list[AgentOut])
    def task_agents(task_id: UUID):
        with app.state.factory() as db:
            store.require_task(db, str(task_id))
            return store.agent_list(db, str(task_id))

    @app.get("/api/tasks/{task_id}/skills", dependencies=secured, response_model=list[SkillOut])
    async def task_skills(task_id: UUID):
        with app.state.factory() as db:
            task = store.require_task(db, str(task_id))
            runtime_for(task_id).require_allowed_task(task)
            root = task.root
        rpc = await runtime_for(task_id).authenticated_rpc()
        result = await rpc.call("skills/list", {"cwds": [root], "forceReload": False})
        return [
            {"name": s["name"], "description": s.get("description", "")[:500]}
            for entry in result.get("data", [])
            if entry.get("cwd") == root
            for s in entry.get("skills", [])
            if s.get("enabled")
        ]

    @app.get("/api/tasks/{task_id}", dependencies=secured, response_model=TaskDetail)
    def task_detail(task_id: str):
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.put(
        "/api/tasks/{task_id}/attachments/{attachment_id}",
        dependencies=secured,
        response_model=AttachmentOut,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                },
            }
        },
    )
    async def upload_attachment(
        task_id: UUID,
        attachment_id: UUID,
        request: Request,
        x_file_name: str = Header(max_length=3072),
    ):
        # Stream binary after authentication; do not pre-parse or spool an unlimited form.
        if request.headers.get("content-type") != "application/octet-stream":
            raise ConsoleError("invalid_input", 415)
        try:
            name = attachments.validate_name(unquote_to_bytes(x_file_name).decode("utf-8"))
        except UnicodeError:
            raise ConsoleError("invalid_filename", 422) from None
        cfg = app.state.settings
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or len(length) > 12):
            raise ConsoleError("invalid_input", 422)
        if length and int(length) > cfg.attachment_max_bytes:
            raise ConsoleError("attachment_too_large", 413)
        with app.state.factory() as db:
            store.require_task(db, str(task_id))
        try:
            async with asyncio.timeout(120), app.state.upload_slots:
                content = bytearray()
                async for chunk in request.stream():
                    if len(content) + len(chunk) > cfg.attachment_max_bytes:
                        raise ConsoleError("attachment_too_large", 413)
                    content.extend(chunk)
                return await asyncio.to_thread(
                    attachments.save,
                    app.state.factory,
                    cfg,
                    str(task_id),
                    str(attachment_id),
                    name,
                    bytes(content),
                )
        except TimeoutError:
            raise ConsoleError("attachment_upload_timeout", 408) from None
        except ClientDisconnect:
            raise ConsoleError("attachment_upload_cancelled", 400) from None

    @app.get(
        "/api/tasks/{task_id}/attachments", dependencies=secured, response_model=list[AttachmentOut]
    )
    def attachment_list(task_id: UUID):
        return store.detail(app.state.factory, str(task_id), app.state.settings)["attachments"]

    @app.get("/api/tasks/{task_id}/attachments/{attachment_id}/download", dependencies=secured)
    def download_attachment(task_id: UUID, attachment_id: UUID):
        with app.state.factory() as db:
            row = attachments.require(db, str(task_id), str(attachment_id))
            return Response(
                row.content,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": "attachment; filename*=UTF-8''"
                    + quote(row.name, safe=""),
                },
            )

    @app.delete(
        "/api/tasks/{task_id}/attachments/{attachment_id}", dependencies=secured, response_model=Ok
    )
    async def delete_attachment(task_id: UUID, attachment_id: UUID):
        async with runtime_for(task_id).gate:
            await asyncio.to_thread(
                attachments.remove,
                app.state.factory,
                app.state.settings,
                str(task_id),
                str(attachment_id),
            )
        return {"ok": True}

    @app.put("/api/tasks/{task_id}/documents", dependencies=secured, response_model=TaskDetail)
    def document(task_id: str, body: DocumentInput):
        with app.state.factory.begin() as db:
            task = store.require_task(db, task_id, locked=True)
            if task.status in (*store.ACTIVE, "uncertain"):
                raise ConsoleError("task_busy")
            latest = store.latest_revision(db, task_id, "plan")
            if (latest.version if latest else 0) != body.base_version:
                raise ConsoleError("stale_document")
            store.save_revision(db, task, "plan", body.body)
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post("/api/tasks/{task_id}/messages", dependencies=secured, response_model=TaskDetail)
    async def message(task_id: str, body: Message):
        await runtime_for(task_id).submit(
            task_id,
            body.operation_id,
            body.text,
            body.stage,
            attachment_ids=body.attachment_ids,
            model=body.model,
            effort=body.effort,
            permissions=body.permissions,
            skill_names=body.skill_names,
        )
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post("/api/tasks/{task_id}/implement", dependencies=secured, response_model=TaskDetail)
    async def implement(task_id: str, body: Implement):
        await runtime_for(task_id).submit(
            task_id,
            body.operation_id,
            body.text,
            "implement",
            body.revision_id,
            body.attachment_ids,
            model=body.model,
            effort=body.effort,
            permissions=body.permissions,
            skill_names=body.skill_names,
        )
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post("/api/tasks/{task_id}/steer", dependencies=secured, response_model=TaskDetail)
    async def steer(task_id: str, body: MessageBody):
        await runtime_for(task_id).steer(
            task_id, body.operation_id, body.text, body.attachment_ids, skill_names=body.skill_names
        )
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post("/api/tasks/{task_id}/interrupt", dependencies=secured, response_model=Ok)
    async def interrupt(task_id: str):
        await runtime_for(task_id).interrupt(task_id)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/recover", dependencies=secured, response_model=TaskDetail)
    async def recover(task_id: str, body: Recover):
        await runtime_for(task_id).recover(task_id, confirm_workspace=body.confirm_workspace)
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.post(
        "/api/tasks/{task_id}/requests/{request_id}",
        dependencies=secured,
        response_model=TaskDetail,
    )
    async def answer(task_id: str, request_id: str, body: Answer):
        await runtime_for(task_id).answer(task_id, request_id, body)
        return store.detail(app.state.factory, task_id, app.state.settings)

    @app.get("/api/tasks/{task_id}/changes", dependencies=secured, response_model=list[ChangeOut])
    def changes(task_id: str):
        with app.state.factory() as db:
            task = store.require_task(db, task_id)
            runtime_for(task_id).require_allowed_task(task)
            root = Path(task.root)
        return git.changes(root)

    @app.get("/api/tasks/{task_id}/git", dependencies=secured, response_model=GitStatusOut)
    def git_status(task_id: str):
        with app.state.factory() as db:
            task = store.require_task(db, task_id)
            runtime_for(task_id).require_allowed_task(task)
            root = Path(task.root)
        return git.status(root)

    @app.get("/api/tasks/{task_id}/diff", dependencies=secured, response_model=DiffOut)
    def diff(task_id: str, path: str = Query(max_length=2048)):
        with app.state.factory() as db:
            task = store.require_task(db, task_id)
            runtime_for(task_id).require_allowed_task(task)
            root = Path(task.root)
        return git.diff(root, path)

    @app.get("/api/overview/events", dependencies=secured)
    @app.get("/api/tasks/{task_id}/events", dependencies=secured)
    async def events(
        request: Request, task_id: str | None = None, after: int = Query(default=0, ge=0)
    ):
        with app.state.factory() as db:
            if task_id:
                store.require_task(db, task_id)
        raw_cursor = request.headers.get("last-event-id", str(after))
        if not raw_cursor.isdecimal() or len(raw_cursor) > 18:
            raise ConsoleError("invalid_input", 422)
        cursor = int(raw_cursor)

        async def stream():
            nonlocal cursor
            token = request.cookies.get(auth.COOKIE)
            while not await request.is_disconnected():
                if not auth.authenticate(app.state.factory, token):
                    yield "event: expired\ndata: {}\n\n"
                    return
                with app.state.factory() as db:
                    latest = (
                        db.scalar(
                            select(func.max(Event.id)).where(
                                *([Event.task_id == task_id] if task_id else [])
                            )
                        )
                        or 0
                    )
                if latest > cursor:
                    cursor = latest
                    # Cursor is a notification to reload the durable projection, not raw prompts.
                    yield f'id: {cursor}\nevent: changed\ndata: {{"cursor":{cursor}}}\n\n'
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    if role == "management":
        app.router.routes = [
            r
            for r in app.router.routes
            if r.path == "/healthz"
            or r.path.startswith(
                ("/api/session", "/api/overview", "/api/monitor", "/api/templates")
            )
        ]
    return app
