import copy

import pytest

from miy_api.miy_desktop_update_manifest import (
    MIYDesktopUpdateManifestError,
    miy_desktop_update_dir_values,
    validate_miy_desktop_update_manifest,
)


def test_miy_desktop_update_manifest_rejects_unsafe_paths_and_files() -> None:
    manifest = _manifest_fixture()
    manifest["feedPathPrefix"] = "/api/v1/miy-desktop/updates/"

    with pytest.raises(MIYDesktopUpdateManifestError, match="absolute path prefix"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["updateBaseUrlEnv"] = "MIY_UPDATE_BASE_URL"

    with pytest.raises(MIYDesktopUpdateManifestError, match="updateBaseUrlEnv is invalid"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["defaultDir"] = "../updates"

    with pytest.raises(MIYDesktopUpdateManifestError, match="relative POSIX path"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["stableCopies"][0]["to"] = "../installer.exe"

    with pytest.raises(MIYDesktopUpdateManifestError, match="safe file name"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["installerUrlEnv"] = "MIY_DESKTOP_INSTALLER_URL_WIN"

    with pytest.raises(MIYDesktopUpdateManifestError, match="installerUrlEnv is invalid"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["servedArtifactSuffixes"] = [".exe", "blockmap"]

    with pytest.raises(MIYDesktopUpdateManifestError, match="servedArtifactSuffixes"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["servedArtifactContentTypes"][".exe"] = "not-a-content-type"

    with pytest.raises(MIYDesktopUpdateManifestError, match="servedArtifactContentTypes"):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    del manifest["servedArtifactContentTypes"][".exe"]

    with pytest.raises(
        MIYDesktopUpdateManifestError, match="servedArtifactContentTypes is missing"
    ):
        validate_miy_desktop_update_manifest(manifest)

    manifest = _manifest_fixture()
    manifest["platforms"]["win"]["installerStableCopy"] = "missing.exe"

    with pytest.raises(
        MIYDesktopUpdateManifestError, match="installerStableCopy must reference"
    ):
        validate_miy_desktop_update_manifest(manifest)


def test_miy_desktop_update_dir_values_reject_unsafe_env_paths() -> None:
    with pytest.raises(MIYDesktopUpdateManifestError, match="must not be empty"):
        miy_desktop_update_dir_values({"MIY_DESKTOP_UPDATE_WIN_DIR": "   "})

    with pytest.raises(MIYDesktopUpdateManifestError, match="clean relative path"):
        miy_desktop_update_dir_values(
            {"MIY_DESKTOP_UPDATE_WIN_DIR": "../outside"}
        )


def _manifest_fixture() -> dict[str, object]:
    return copy.deepcopy(
        {
            "feedPathPrefix": "/api/v1/miy-desktop/updates",
            "updateBaseUrlEnv": "MIY_DESKTOP_UPDATE_BASE_URL",
            "trustedUpdateOriginsEnv": "MIY_DESKTOP_TRUSTED_UPDATE_ORIGINS",
            "servedArtifactContentTypes": {
                ".blockmap": "application/octet-stream",
                ".exe": "application/octet-stream",
            },
            "platformOrder": ["win"],
            "platforms": {
                "win": {
                    "packageName": "miy-desktop-win",
                    "installerUrlEnv": "VITE_MIY_DESKTOP_INSTALLER_URL_WIN",
                    "installerStableCopy": "MIY-Desktop-Setup-latest.exe",
                    "updateDirEnv": "MIY_DESKTOP_UPDATE_WIN_DIR",
                    "defaultDir": ".miy-desktop-updates/win",
                    "updateFile": "latest.yml",
                    "servedArtifactSuffixes": [".exe", ".blockmap"],
                    "packagedArtifacts": [
                        {"template": "miy Desktop Setup ${version}.exe"},
                    ],
                    "stableCopies": [
                        {
                            "template": "miy Desktop Setup ${version}.exe",
                            "to": "MIY-Desktop-Setup-latest.exe",
                        },
                    ],
                },
            },
        }
    )
