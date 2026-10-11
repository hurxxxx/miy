import copy


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
