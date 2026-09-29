import copy

import pytest

from mty_api.mty_desktop_update_manifest import (
    MTYDesktopUpdateManifestError,
    mty_desktop_update_dir_values,
    validate_mty_desktop_update_manifest,
)


def test_mty_desktop_update_manifest_rejects_unsafe_paths_and_files() -> None:
    manifest = _manifest_fixture()
    manifest["feedPathPrefix"] = "/api/v1/mty-desktop/updates/"

    with pytest.raises(MTYDesktopUpdateManifestError, match="absolute path prefix"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["updateBaseUrlEnv"] = "MTY_UPDATE_BASE_URL"

    with pytest.raises(MTYDesktopUpdateManifestError, match="updateBaseUrlEnv is invalid"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["defaultDir"] = "../updates"

    with pytest.raises(MTYDesktopUpdateManifestError, match="relative POSIX path"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["stableCopies"][0]["to"] = "../installer.exe"

    with pytest.raises(MTYDesktopUpdateManifestError, match="safe file name"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["installerUrlEnv"] = "MTY_DESKTOP_INSTALLER_URL_WIN"

    with pytest.raises(MTYDesktopUpdateManifestError, match="installerUrlEnv is invalid"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["servedArtifactSuffixes"] = [".exe", "blockmap"]

    with pytest.raises(MTYDesktopUpdateManifestError, match="servedArtifactSuffixes"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["servedArtifactContentTypes"][".exe"] = "not-a-content-type"

    with pytest.raises(MTYDesktopUpdateManifestError, match="servedArtifactContentTypes"):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    del manifest["servedArtifactContentTypes"][".exe"]

    with pytest.raises(
        MTYDesktopUpdateManifestError, match="servedArtifactContentTypes is missing"
    ):
        validate_mty_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["installerStableCopy"] = "missing.exe"

    with pytest.raises(
        MTYDesktopUpdateManifestError, match="installerStableCopy must reference"
    ):
        validate_mty_desktop_update_manifest(manifest)


def test_mty_desktop_update_dir_values_reject_unsafe_env_paths() -> None:
    with pytest.raises(MTYDesktopUpdateManifestError, match="must not be empty"):
        mty_desktop_update_dir_values({"MTY_DESKTOP_UPDATE_WIN_DIR": "   "})

    with pytest.raises(MTYDesktopUpdateManifestError, match="clean relative path"):
        mty_desktop_update_dir_values(
            {"MTY_DESKTOP_UPDATE_WIN_DIR": "../outside"}
        )


def _manifest_fixture() -> dict[str, object]:
    return copy.deepcopy(
        {
            "feedPathPrefix": "/api/v1/mty-desktop/updates",
            "updateBaseUrlEnv": "MTY_DESKTOP_UPDATE_BASE_URL",
            "trustedUpdateOriginsEnv": "MTY_DESKTOP_TRUSTED_UPDATE_ORIGINS",
            "servedArtifactContentTypes": {
                ".blockmap": "application/octet-stream",
                ".exe": "application/octet-stream",
            },
            "platformOrder": ["win"],
            "platforms": {
                "win": {
                    "packageName": "mty-desktop-win",
                    "installerUrlEnv": "VITE_MTY_DESKTOP_INSTALLER_URL_WIN",
                    "installerStableCopy": "MTY-Desktop-Setup-latest.exe",
                    "updateDirEnv": "MTY_DESKTOP_UPDATE_WIN_DIR",
                    "defaultDir": ".mty-desktop-updates/win",
                    "updateFile": "latest.yml",
                    "servedArtifactSuffixes": [".exe", ".blockmap"],
                    "packagedArtifacts": [
                        {"template": "MTY Desktop Setup ${version}.exe"},
                    ],
                    "stableCopies": [
                        {
                            "template": "MTY Desktop Setup ${version}.exe",
                            "to": "MTY-Desktop-Setup-latest.exe",
                        },
                    ],
                },
            },
        }
    )
