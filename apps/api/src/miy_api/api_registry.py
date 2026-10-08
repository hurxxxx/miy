from __future__ import annotations

from collections.abc import Callable, Sequence
from fastapi import Depends, FastAPI
from fastapi.params import Depends as DependsParam
from sqlalchemy.orm import Session

from miy_api.api_composition import ApiComposition, RouterSpec, require_composition
from miy_api.core.settings import Settings
from miy_api.domains.auth.dependencies import require_auth_context, require_current_user
from miy_api.openapi_contract import PROTECTED_ERROR_RESPONSES


def router_specs(composition: ApiComposition = "legacy") -> tuple[RouterSpec, ...]:
    selected = require_composition(composition)
    specs: list[RouterSpec] = []
    if selected in ("legacy", "platform"):
        from miy_api.platform_api_registry import platform_router_specs

        specs.extend(platform_router_specs())
    if selected in ("legacy", "official"):
        from miy_api.official_api_registry import official_router_specs

        specs.extend(official_router_specs())
    if len({spec.position for spec in specs}) != len(specs):
        raise ValueError("API composition contains duplicate router positions")
    if len({id(spec.router) for spec in specs}) != len(specs):
        raise ValueError("API composition contains duplicate routers")
    return tuple(sorted(specs, key=lambda spec: spec.position))


def _include_router_spec(
    app: FastAPI,
    spec: RouterSpec,
    *,
    api_prefix: str,
    protected_dependencies: Sequence[DependsParam],
) -> None:
    if spec.protection == "public":
        app.include_router(spec.router, prefix=api_prefix)
    else:
        app.include_router(
            spec.router,
            prefix=api_prefix,
            dependencies=protected_dependencies,
            responses=PROTECTED_ERROR_RESPONSES,
        )


def register_api_routers(
    app: FastAPI,
    settings: Settings,
    *,
    composition: ApiComposition = "legacy",
    official_auth_session_factory: Callable[[], Session] | None = None,
    official_auth_max_concurrent_reads: int | None = None,
) -> None:
    composition = require_composition(composition)
    prepared = (
        official_auth_session_factory is not None or official_auth_max_concurrent_reads is not None
    )
    if prepared and (
        composition != "official"
        or official_auth_session_factory is None
        or official_auth_max_concurrent_reads is None
    ):
        raise ValueError("Prepared auth requires official composition, factory and read budget")
    if composition == "official":
        from miy_api.official_auth import owned_app_scope, require_official_auth_context

        if prepared:
            from miy_api.official_auth import build_prepared_official_auth_dependency

            dependency = build_prepared_official_auth_dependency(
                session_factory=official_auth_session_factory,
                max_concurrent_reads=official_auth_max_concurrent_reads,
            )
            # HTTP and owned collaboration callbacks share one read budget.
            app.state.prepared_official_auth_dependency = dependency
        else:
            dependency = require_official_auth_context
        app.dependency_overrides[require_auth_context] = dependency
    for spec in router_specs(composition):
        protected_dependencies = [Depends(require_current_user)]
        if composition == "official":
            protected_dependencies.insert(0, Depends(owned_app_scope(spec.logical_app_id)))
        _include_router_spec(
            app,
            spec,
            api_prefix=settings.api_prefix,
            protected_dependencies=protected_dependencies,
        )
