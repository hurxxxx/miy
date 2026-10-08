#!/usr/bin/env python3
"""Create an app-only development checkout from a bounded, pinned source snapshot.

Run with the platform API Python environment. This core operator command does not
copy source Git metadata, credentials, environment files, links, or host config.
The destination becomes the app's development repository; there is no reverse sync.
"""

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

def prepare(source: Path, revision: str, destination: Path):
    from miy_api.domains.independent_apps.builds import BuildFailure, _required, _snapshot
    from miy_api.domains.independent_apps.contracts import AppDefinition
    if (
        not source.is_absolute()
        or source.resolve() != source
        or not destination.is_absolute()
        or destination.resolve() != destination
        or destination.exists()
        or not destination.parent.is_dir()
        or destination.is_relative_to(source)
        or source.is_relative_to(destination)
    ):
        raise BuildFailure("workspace_target_denied")
    descriptor = os.open(source / "app.manifest.json", os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise BuildFailure("workspace_manifest_invalid")
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise BuildFailure("workspace_manifest_invalid")
    definition = AppDefinition.model_validate_json(raw)
    environment = {
        "PATH": os.defpath,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_TERMINAL_PROMPT": "0",
    }
    with tempfile.TemporaryDirectory(
        prefix=".miy-app-source-", dir=destination.parent
    ) as temporary:
        checkout = Path(temporary) / "checkout"
        checkout.mkdir(mode=0o700)
        archive = _snapshot(source, revision, definition, checkout)
        prefix = [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=MIY app workspace",
            "-c",
            "user.email=app-workspace@localhost.invalid",
            "-C",
            str(checkout),
        ]
        for arguments in (
            ("init", "-b", "main"),
            ("remote", "add", "origin", definition.source.repository),
            ("add", "--all"),
            ("commit", "-m", "Initialize isolated application workspace"),
        ):
            _required([*prefix, *arguments], env=environment)
        new_revision = _required([*prefix, "rev-parse", "HEAD"], env=environment).decode().strip()
        # The explicit target did not exist; publish only after all checks pass.
        if destination.exists():
            raise BuildFailure("workspace_target_exists")
        checkout.rename(destination)
    return {
        "app_id": definition.app_id,
        "source_revision": revision,
        "source_archive_sha256": archive,
        "development_revision": new_revision,
        "development_repository": str(destination),
        "reverse_sync": False,
    }


def main():
    from miy_api.domains.independent_apps.builds import BuildFailure

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.revision, args.destination)
    except (BuildFailure, ValueError, OSError):
        parser.exit(
            1, "Isolated app workspace preparation failed; no source commands were executed.\n"
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
