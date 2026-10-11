"""The reviewed official artifact serves only its client paths and static namespace."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from miy_api.client_build import is_valid_client_build_id
from miy_api.first_party_routes import official_client_bases
from miy_api.frontend import FrontendStaticFiles


class OfficialClientFiles(FrontendStaticFiles):
    async def get_response(self, path: str, scope: dict):
        # Deep-link identifiers may contain a dot; they are routes, never static file names.
        # The surrounding mounts are restricted to contract-owned client bases.
        return await super().get_response("index.html", scope)


class OfficialNamespaceFiles(FrontendStaticFiles):
    async def get_response(self, path: str, scope: dict):
        if path.strip("/") == "widgets":
            return await super().get_response("index.html", scope)
        return await super().get_response(path, scope)


def read_platform_build_id(directory: str | Path) -> str | None:
    """Read the fixed reviewed compatibility identity, never the running core's identity."""
    compatibility = Path(directory).resolve() / ".miy-platform-build-id"
    if not compatibility.is_file():
        raise RuntimeError("official_frontend_compatibility_missing")
    build_id = compatibility.read_text(encoding="utf-8").strip()
    if build_id and not is_valid_client_build_id(build_id):
        raise RuntimeError("official_frontend_compatibility_invalid")
    return build_id or None


def mount_official_frontend(
    app: FastAPI,
    directory: str | Path,
    *,
    platform_build_id: str | None,
    required: bool = True,
) -> None:
    root = Path(directory).resolve()
    index = root / "index.html"
    if not index.is_file():
        if required:
            raise RuntimeError("official_frontend_artifact_missing")
        return
    if platform_build_id is not None and not is_valid_client_build_id(
        platform_build_id
    ):
        raise RuntimeError("official_frontend_compatibility_invalid")

    @app.get("/official-suite/platform-build.json", include_in_schema=False)
    def platform_build_metadata() -> JSONResponse:
        return JSONResponse(
            {"platform_build_id": platform_build_id},
            headers={"Cache-Control": "no-store"},
        )

    # Preserve existing fixed asset URLs, including the Recording worker's existing scope.
    def fixed_asset_handler(file: Path):
        def fixed_asset() -> FileResponse:
            return FileResponse(
                file, headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"}
            )

        return fixed_asset

    for public_path, relative in (
        ("/recording-sync-sw.js", "recording-sync-sw.js"),
        ("/help/pms/user-guide.html", "help/pms/user-guide.html"),
    ):
        app.add_api_route(
            public_path,
            fixed_asset_handler(root / relative),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
    app.mount(
        "/official-suite",
        OfficialNamespaceFiles(directory=root, index_path=index),
        name="official-assets",
    )
    for base in official_client_bases():
        # Exact routes avoid the portal catchall handling a mount's slash redirect.
        app.add_api_route(
            base,
            fixed_asset_handler(index),
            methods=["GET", "HEAD"],
            include_in_schema=False,
        )
        app.mount(
            base,
            OfficialClientFiles(directory=root, index_path=index),
            name="official-client-" + base.replace("/", "-"),
        )
