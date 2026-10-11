"""Checked ingress metadata; only the producer imports application routers.

The existing OpenAPI generator owns generation and drift checks. Runtime readers
consume its packaged resource without application settings or business imports.
"""

from __future__ import annotations

from importlib.resources import files
import json
import re
from typing import Literal, TypedDict, cast

from starlette.routing import compile_path

from miy_api.core.app_contracts_generated import APP_CONTRACT_REVISION

RESOURCE_NAME = "first_party_routes.generated.json"


class RouteBinding(TypedDict):
    path: str
    owner: Literal["platform", "official"]


class RouteContract(TypedDict):
    schema_version: int
    app_contract_revision: str
    routes: list[RouteBinding]


def route_pattern(path: str) -> str:
    # Nginx matches paths only; Python capture names carry no identity.
    return re.sub(r"\(\?P<[^>]+>", "(?:", compile_path(path)[0].pattern)


def validate_route_contract(value: object) -> RouteContract:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "app_contract_revision", "routes"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["app_contract_revision"] != APP_CONTRACT_REVISION
        or not isinstance(value["routes"], list)
        or not value["routes"]
    ):
        raise ValueError("first_party_route_contract_invalid")
    patterns: dict[str, str] = {}
    ordered: list[tuple[str, str]] = []
    for route in value["routes"]:
        if (
            not isinstance(route, dict)
            or set(route) != {"path", "owner"}
            or not isinstance(route["path"], str)
            or not route["path"].startswith("/")
            or route["owner"] not in ("platform", "official")
        ):
            raise ValueError("first_party_route_contract_invalid")
        pattern = route_pattern(route["path"])
        previous = patterns.setdefault(pattern, route["owner"])
        if previous != route["owner"]:
            raise ValueError("first_party_route_owner_conflict")
        ordered.append((route["path"], route["owner"]))
    if ordered != sorted(set(ordered)):
        raise ValueError("first_party_route_contract_invalid")
    return cast(RouteContract, value)


def generated_route_contract() -> RouteContract:
    resource = files("miy_api.core").joinpath(RESOURCE_NAME)
    return validate_route_contract(json.loads(resource.read_text(encoding="utf-8")))


def native_route_contract() -> RouteContract:
    """Produce metadata from both actual owners, including native lazy WS routes."""
    from fastapi.routing import iter_route_contexts

    from miy_api.api_registry import router_specs

    bindings: set[tuple[str, str]] = set()
    for spec in router_specs():
        for route in iter_route_contexts(spec.router.routes):
            path = getattr(route, "path", None)
            if not isinstance(path, str):
                raise ValueError("first_party_route_path_required")
            bindings.add((path, spec.owner))
    return validate_route_contract(
        {
            "schema_version": 1,
            "app_contract_revision": APP_CONTRACT_REVISION,
            "routes": [{"path": path, "owner": owner} for path, owner in sorted(bindings)],
        }
    )
