"""Project the server-owned router inventory into an ingress owner map."""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import TypedDict

from fastapi.routing import iter_route_contexts
from starlette.routing import compile_path

from miy_api.api_registry import router_specs
from miy_api.core.app_contracts_generated import APP_CONTRACTS, OFFICIAL_APP_IDS


class ApiOwnerInventory(TypedDict):
    api_prefix: str
    official_patterns: list[str]


def api_owner_inventory(*, api_prefix: str = "/api/v1") -> ApiOwnerInventory:
    if not re.fullmatch(r"/[A-Za-z0-9/_-]+", api_prefix) or api_prefix.endswith("/"):
        raise ValueError("first_party_api_prefix_invalid")
    patterns: dict[str, str] = {}
    for spec in router_specs():
        # FastAPI 0.141 keeps included routers lazy. Its native iterator preserves
        # their effective prefixes for both HTTP and WebSocket routes.
        for route in iter_route_contexts(spec.router.routes):
            path = getattr(route, "path", None)
            if not isinstance(path, str):
                raise ValueError("first_party_route_path_required")
            pattern = compile_path(api_prefix + path)[0].pattern
            # Nginx only needs matching; named Python captures grant no identity.
            pattern = re.sub(r"\(\?P<[^>]+>", "(?:", pattern)
            previous = patterns.setdefault(pattern, spec.owner)
            if previous != spec.owner:
                raise ValueError("first_party_route_owner_conflict")
    official = sorted(pattern for pattern, owner in patterns.items() if owner == "official")
    return {"api_prefix": api_prefix, "official_patterns": official}


def nginx_owner_map(*, api_prefix: str = "/api/v1") -> str:
    official = api_owner_inventory(api_prefix=api_prefix)["official_patterns"]
    entries = "\n".join(f"    {json.dumps('~' + pattern)} official;" for pattern in official)
    return "map $uri $miy_api_owner {\n    default platform;\n" + entries + "\n}\n"


def official_client_bases() -> tuple[str, ...]:
    return tuple(
        sorted(str(app["route_base"]) for app in APP_CONTRACTS if app["app_id"] in OFFICIAL_APP_IDS)
    )


def nginx_client_owner_map() -> str:
    prefixes = (*official_client_bases(), "/official-suite")
    patterns = [f"^{re.escape(prefix)}(?:/|$)" for prefix in prefixes]
    patterns += [r"^/recording-sync-sw\.js$", r"^/help/pms/user-guide\.html$"]
    entries = "\n".join(
        f"    {json.dumps('~' + pattern)} official;" for pattern in sorted(patterns)
    )
    return "map $uri $miy_ui_owner {\n    default platform;\n" + entries + "\n}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--nginx-map", action="store_true")
    output.add_argument("--client-map", action="store_true")
    output.add_argument("--json", action="store_true")
    parser.add_argument("--api-prefix", default=os.environ.get("MIY_API_PREFIX", "/api/v1"))
    args = parser.parse_args()
    if args.json:
        print(json.dumps(api_owner_inventory(api_prefix=args.api_prefix)))
    elif args.client_map:
        print(nginx_client_owner_map(), end="")
    else:
        print(nginx_owner_map(api_prefix=args.api_prefix), end="")


if __name__ == "__main__":
    main()
