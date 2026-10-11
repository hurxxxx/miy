import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import Response as FastAPIResponse
from opentelemetry.trace import SpanKind
from starlette.exceptions import HTTPException as StarletteHTTPException

from miy_api.api_registry import register_api_routers, register_first_party_api_routers
from miy_api.api_composition import (
    ApiComposition,
    InactiveCompositionMiddleware,
    require_composition,
)
from miy_api.client_build import (
    ClientBuildGuardMiddleware,
    is_valid_client_build_id,
    read_frontend_build_id,
)
from miy_api.core.db import get_session_factory, init_db
from miy_api.core.model_registry import import_all_models
from miy_api.core.i18n import (
    ERROR_CODE_HEADER,
    LocalizedApiMessage,
    select_locale,
    translate_message,
)
from miy_api.core.logging_security import install_sensitive_http_logging_guard
from miy_api.core.request_validation_errors import build_request_validation_error_body
from miy_api.core.runtime_diagnostics import (
    install_stack_dump_signal,
    start_event_loop_lag_watchdog,
)
from miy_api.core.settings import get_settings
from miy_api.core.storage import ensure_bucket
from miy_api.core.telemetry import (
    bootstrap_telemetry,
    current_trace_id,
    extract_trace_context,
    get_tracer,
)
from miy_api.domains.ai.privacy_filter import (
    check_privacy_filter_health,
    prepare_privacy_filter,
)
from miy_api.domains.ai.runtime.registry_validation import RuntimeRegistryValidationError
from miy_api.domains.ai.runtime_status import inspect_registered_llm_runtime
from miy_api.domains.hermes_terminal.mcp_socket_server import (
    HermesTerminalMcpSocketServer,
)
from miy_api.domains.rag.runtime import (
    attach_rag_queue_health,
    close_rag_runtime_resources,
    get_rag_runtime_health,
    preload_rag_runtime,
)
from miy_api.external_runtime import (
    ApiExternalRuntime,
    FirstPartyApiExternalRuntime,
    ProductionApiExternalRuntime,
)
from miy_api.frontend import mount_frontend
from miy_api.miy_desktop_updates import (
    mount_miy_desktop_update_feeds,
    prepare_miy_desktop_update_dirs,
)
from miy_api.openapi_contract import stable_operation_id
from miy_api.platform_extensions import initialize_platform_extensions
from miy_api.version import RUNTIME_REVISION
from miy_api.version import VERSION as APP_VERSION

logger = logging.getLogger(__name__)


def _skip_object_storage_prepare() -> None:
    return None


def _request_locale(request: Request) -> str:
    return select_locale(
        explicit_locale=request.headers.get("x-miy-locale"),
        accept_language=request.headers.get("accept-language"),
    )


async def runtime_registry_validation_exception_handler(
    request: Request,
    exc: RuntimeRegistryValidationError,
) -> JSONResponse:
    del request
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def localized_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    if not isinstance(exc.detail, LocalizedApiMessage):
        return await http_exception_handler(request, exc)

    locale = _request_locale(request)
    body: dict[str, object] = {
        "detail": translate_message(exc.detail, locale),
        "code": exc.detail.code,
    }
    if exc.detail.params:
        body["params"] = exc.detail.params
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers,
    )


async def localized_request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    locale = _request_locale(request)
    body, error_code = build_request_validation_error_body(exc.errors(), locale)
    return JSONResponse(
        status_code=422,
        content=body,
        headers={ERROR_CODE_HEADER: error_code},
    )


def create_app(
    *,
    initialize_runtime: bool = True,
    external_runtime: ApiExternalRuntime | None = None,
    composition: ApiComposition = "legacy",
) -> FastAPI:
    selected_composition = require_composition(composition)
    if selected_composition != "legacy" and initialize_runtime:
        raise RuntimeError("Split API runtime activation requires the writer cutover contract")
    return _create_app(
        initialize_runtime=initialize_runtime,
        external_runtime=external_runtime,
        composition=selected_composition,
    )


def create_first_party_app(
    *,
    composition: ApiComposition,
    initialize_runtime: bool = True,
    external_runtime: ApiExternalRuntime | None = None,
    client_build_id: str | None = None,
) -> FastAPI:
    """Explicit split process using the existing trusted first-party DB boundary.

    No Source-only role, delegated credential or new writer owner is selected.
    The previous process must be drained by the deployment owner before routing
    is changed. Schema migration and identity seeding remain a single core job.
    """
    selected = require_composition(composition)
    if selected == "legacy":
        raise ValueError("First-party split runtime requires one router owner")
    if client_build_id is not None:
        if selected != "official":
            raise ValueError("Platform client build identity belongs to its own frontend artifact")
        if not is_valid_client_build_id(client_build_id):
            raise ValueError("Official client build identity is invalid")
    return _create_app(
        initialize_runtime=initialize_runtime,
        external_runtime=external_runtime,
        composition=selected,
        first_party_shared_authority=True,
        client_build_id=client_build_id,
    )


def _create_app(
    *,
    initialize_runtime: bool,
    external_runtime: ApiExternalRuntime | None,
    composition: ApiComposition,
    first_party_shared_authority: bool = False,
    client_build_id: str | None = None,
) -> FastAPI:
    selected_composition = require_composition(composition)
    platform_services = selected_composition in {"legacy", "platform"}
    serve_frontend = selected_composition == "legacy" or (
        first_party_shared_authority and selected_composition == "platform"
    )
    install_sensitive_http_logging_guard()
    settings = get_settings()
    frontend_build_id = (
        read_frontend_build_id(settings.frontend_dist_dir) if serve_frontend else client_build_id
    )
    miy_desktop_update_dirs = prepare_miy_desktop_update_dirs(settings) if serve_frontend else {}
    telemetry_enabled = (
        selected_composition == "legacy" or first_party_shared_authority
    ) and bootstrap_telemetry(
        service_name=(
            "miy-api" if selected_composition == "legacy" else f"miy-{selected_composition}-api"
        ),
        service_version=APP_VERSION,
        enabled=settings.otel_enabled,
        enable_console_exporter=settings.otel_console_exporter,
        enable_otlp_exporter=settings.otel_otlp_exporter_enabled,
        metrics_export_interval_ms=settings.otel_metrics_export_interval_ms,
    )
    telemetry_tracer = get_tracer("miy_api.http")
    selected_external_runtime = external_runtime
    if initialize_runtime:
        if selected_external_runtime is None:
            if first_party_shared_authority:
                selected_external_runtime = FirstPartyApiExternalRuntime(
                    composition=selected_composition, settings=settings
                )
            else:
                selected_external_runtime = ProductionApiExternalRuntime(
                    settings,
                    storage_prepare=(
                        ensure_bucket
                        if settings.object_storage_required
                        else _skip_object_storage_prepare
                    ),
                )
        install_stack_dump_signal()
        initialize_platform_extensions(settings)
        if first_party_shared_authority:
            from miy_api.core.worker_task_publisher import configure_first_party_worker_routing
            from miy_api.domains.official_apps.first_party_runtime import (
                require_first_party_database,
            )

            import_all_models()
            require_first_party_database(composition=selected_composition)
            configure_first_party_worker_routing()
        else:
            init_db()
        selected_external_runtime.prepare()
        if selected_composition in {"legacy", "official"}:
            Path(settings.recording_spool_dir).expanduser().mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not initialize_runtime:
            yield
            return
        assert selected_external_runtime is not None
        terminal_mcp_socket = HermesTerminalMcpSocketServer(settings) if platform_services else None
        try:
            async with selected_external_runtime.activate(app):
                if terminal_mcp_socket is not None:
                    await terminal_mcp_socket.startup()
                if platform_services and settings.llm_healthcheck_on_startup:
                    with get_session_factory()() as session:
                        llm_status = inspect_registered_llm_runtime(
                            session,
                            settings=settings,
                            probe="live",
                        )
                    app.state.llm_health = llm_status.pools.public_dict()
                    app.state.llm_effective = llm_status.workloads.public_dict()
                    if settings.llm_required and not llm_status.workloads.ready:
                        logger.warning(
                            "LLM effective readiness check failed: %s",
                            llm_status.workloads.public_dict(),
                        )
                if platform_services and settings.opf_healthcheck_on_startup:
                    privacy_filter = prepare_privacy_filter(
                        settings=settings,
                        download=settings.opf_download_on_startup,
                    )
                    app.state.privacy_filter_health = privacy_filter
                    if settings.opf_required and not privacy_filter.ready:
                        logger.warning("Privacy Filter readiness check failed: %s", privacy_filter)
                if platform_services and settings.rag_enabled and settings.rag_preload_on_startup:
                    app.state.rag_preload = preload_rag_runtime(settings)
                loop_lag_watchdog = start_event_loop_lag_watchdog(settings)
                app.state.loop_lag_watchdog = loop_lag_watchdog
                try:
                    yield
                finally:
                    loop_lag_watchdog.cancel()
                    await asyncio.gather(loop_lag_watchdog, return_exceptions=True)
                    app.state.loop_lag_watchdog = None
        finally:
            if terminal_mcp_socket is not None:
                await terminal_mcp_socket.shutdown()
            if platform_services:
                close_rag_runtime_resources()

    app = FastAPI(
        title=(
            settings.app_name
            if selected_composition == "legacy"
            else f"{settings.app_name} {selected_composition} API"
        ),
        version=APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        generate_unique_id_function=stable_operation_id,
    )
    app.add_middleware(
        ClientBuildGuardMiddleware,
        expected_build_id=frontend_build_id,
    )
    app.state.frontend_build_id = frontend_build_id
    app.state.api_composition = selected_composition
    app.state.first_party_shared_authority = first_party_shared_authority
    app.state.telemetry_enabled = telemetry_enabled
    app.add_exception_handler(
        RuntimeRegistryValidationError,
        runtime_registry_validation_exception_handler,
    )
    app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)
    app.add_exception_handler(
        RequestValidationError,
        localized_request_validation_exception_handler,
    )

    @app.middleware("http")
    async def add_instance_headers(request, call_next) -> FastAPIResponse:
        response = await call_next(request)
        response.headers["X-MIY-Instance-Id"] = settings.instance_id
        trace_id = current_trace_id()
        if trace_id is not None:
            response.headers["X-MIY-Trace-Id"] = trace_id
        return response

    @app.middleware("http")
    async def telemetry_middleware(request, call_next) -> FastAPIResponse:
        if not app.state.telemetry_enabled:
            return await call_next(request)

        span_name = f"HTTP {request.method}"
        with telemetry_tracer.start_as_current_span(
            span_name,
            context=extract_trace_context(request.headers),
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "url.scheme": request.url.scheme,
            },
        ) as span:
            response = await call_next(request)
            route = request.scope.get("route")
            route_path = getattr(route, "path", None)
            if isinstance(route_path, str) and route_path:
                span.set_attribute("http.route", route_path)
            span.set_attribute("http.response.status_code", response.status_code)
            return response

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, str]:
        if selected_composition != "legacy" and not first_party_shared_authority:
            return {
                "status": "ok",
                "composition": selected_composition,
                "activation": "inactive",
                "version": APP_VERSION,
                "runtime_revision": RUNTIME_REVISION,
            }
        return {
            "status": "ok",
            "version": APP_VERSION,
            "environment": settings.environment,
            "instance_id": settings.instance_id,
            "runtime_revision": RUNTIME_REVISION,
            **(
                {"composition": selected_composition, "authority": "first_party_shared_database"}
                if first_party_shared_authority
                else {}
            ),
        }

    @app.get("/readyz", tags=["system"])
    def readyz(request: Request, response: Response) -> dict[str, object]:
        if selected_composition != "legacy" and not first_party_shared_authority:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "not_ready",
                "composition": selected_composition,
                "code": "service_not_activated",
                "version": APP_VERSION,
                "runtime_revision": RUNTIME_REVISION,
            }
        if first_party_shared_authority and selected_composition == "official":
            from miy_api.domains.official_apps.first_party_runtime import (
                require_first_party_database,
            )

            try:
                require_first_party_database(composition="official")
            except RuntimeError:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
                return {"status": "not_ready", "code": "first_party_database_unavailable"}
            services = (
                getattr(request.app.state, "app_realtime", None),
                getattr(request.app.state, "docs_collab", None),
                getattr(request.app.state, "whiteboard_collab", None),
            )
            ready = all(service is not None for service in services) and all(
                bool(
                    getattr(service, "redis_available", getattr(service, "relay_available", False))
                )
                for service in services
                if service is not None
            )
            if not ready:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "ok" if ready else "not_ready",
                "composition": "official",
                "authority": "first_party_shared_database",
                "environment": settings.environment,
                "instance_id": settings.instance_id,
                "version": APP_VERSION,
                "runtime_revision": RUNTIME_REVISION,
            }
        with get_session_factory()() as session:
            llm_status = inspect_registered_llm_runtime(
                session,
                settings=settings,
                probe="configured",
            )
        dual = llm_status.pools
        effective = llm_status.workloads
        rag = get_rag_runtime_health()
        if rag.get("enabled"):
            with get_session_factory()() as session:
                rag = attach_rag_queue_health(rag, db=session)
        locale = _request_locale(request)
        ready = effective.ready or not settings.llm_required
        if rag.get("enabled") and not rag.get("ready", False):
            ready = False
        privacy_filter = check_privacy_filter_health(settings=settings)
        if settings.opf_required and not privacy_filter.ready:
            ready = False
        app_realtime = getattr(request.app.state, "app_realtime", None)
        realtime = {
            "redis_available": bool(
                app_realtime is None or getattr(app_realtime, "redis_available", False)
            )
        }
        if not realtime["redis_available"]:
            ready = False
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {
            "status": "ok" if ready else "degraded",
            "version": APP_VERSION,
            "environment": settings.environment,
            "instance_id": settings.instance_id,
            "runtime_revision": RUNTIME_REVISION,
            "llm": dual.public_dict(locale=locale, include_base_url=False),
            "llm_effective": effective.public_dict(locale=locale),
            "privacy_filter": {
                "enabled": privacy_filter.enabled,
                "ready": privacy_filter.ready,
                "status": privacy_filter.status,
                "checkpoint": privacy_filter.checkpoint,
                "device": privacy_filter.device,
                "detail": privacy_filter.detail,
            },
            "rag": rag,
            "realtime": realtime,
        }

    if first_party_shared_authority:
        register_first_party_api_routers(app, settings, composition=selected_composition)
    else:
        register_api_routers(app, settings, composition=selected_composition)
    if serve_frontend:
        mount_miy_desktop_update_feeds(app, settings, miy_desktop_update_dirs)
        if selected_composition == "legacy" and settings.serve_frontend:
            official_frontend_dir = (
                Path(settings.frontend_dist_dir).expanduser().resolve().parent / "official-suite"
            )
            if (official_frontend_dir / "index.html").is_file():
                from miy_official_api.frontend import (
                    mount_official_frontend,
                    read_platform_build_id,
                )

                official_build_id = read_platform_build_id(official_frontend_dir)
                if official_build_id != frontend_build_id:
                    raise RuntimeError("legacy_official_frontend_compatibility_mismatch")
                mount_official_frontend(
                    app, official_frontend_dir, platform_build_id=official_build_id
                )
        mount_frontend(app, settings)
    elif not first_party_shared_authority:
        app.add_middleware(InactiveCompositionMiddleware)
    return app
