from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from mty_api.core.settings import Settings
from mty_api.mty_desktop_update_serving_policy import (
    DesktopUpdateServingPolicy,
    mty_desktop_update_serving_policy,
)
from mty_api.static_serving import apply_static_response_headers


class DesktopUpdateStaticFiles(StaticFiles):
    def __init__(
        self,
        *args: Any,
        platform: str,
        policy: DesktopUpdateServingPolicy,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.platform = platform
        self.policy = policy

    async def get_response(self, path: str, scope: dict[str, Any]) -> Response:
        if not self.policy.is_allowed_file_path(self.platform, path):
            raise StarletteHTTPException(status_code=404)

        response = await super().get_response(path, scope)
        headers = self.policy.attachment_headers(self.platform, path)
        apply_static_response_headers(response, headers)
        return response


def mty_desktop_update_dirs(settings: Settings) -> dict[str, Path]:
    return mty_desktop_update_serving_policy().update_dirs(
        settings.mty_desktop_update_dirs
    )


def prepare_mty_desktop_update_dirs(settings: Settings) -> dict[str, Path]:
    update_dirs = mty_desktop_update_dirs(settings)
    for update_dir in update_dirs.values():
        update_dir.mkdir(parents=True, exist_ok=True)
    return update_dirs


def mount_mty_desktop_update_feeds(
    app: FastAPI,
    settings: Settings,
    update_dirs: dict[str, Path] | None = None,
) -> None:
    resolved_update_dirs = (
        update_dirs if update_dirs is not None else mty_desktop_update_dirs(settings)
    )
    policy = mty_desktop_update_serving_policy()
    for platform in policy.platforms:
        app.mount(
            f"{policy.feed_path_prefix}/{platform}",
            DesktopUpdateStaticFiles(
                directory=resolved_update_dirs[platform],
                platform=platform,
                policy=policy,
            ),
            name=f"mty-desktop-updates-{platform}",
        )
