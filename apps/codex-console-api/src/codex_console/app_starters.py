"""Fixed starter resources shipped inside the standalone Workbench artifact."""

import hashlib
import json
from importlib.resources import files
from pathlib import PurePosixPath

from jsonschema.exceptions import ValidationError

from .app_sources import repository_identity, validator
from .errors import ConsoleError

MAX_BYTES = 2 * 1024 * 1024


def bundle():
    try:
        raw = files("codex_console").joinpath("app_starters.generated.json").read_bytes()
        if len(raw) > MAX_BYTES * 3:
            raise ValueError("Oversized starter resources")
        value = json.loads(raw)
        checksum = value.pop("bundle_digest")
        actual = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
        )
        if checksum != actual or value["schema_version"] != 1:
            raise ValueError("Invalid starter resources")
        for template in value["templates"].values():
            entries = template["files"]
            if (
                len(entries) > 256
                or sum(len(text.encode()) for text in entries.values()) > MAX_BYTES
            ):
                raise ValueError("Oversized starter")
            for name in entries:
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or path.as_posix() != name
                    or not path.parts
                    or ".." in path.parts
                    or any(
                        part.startswith((".env", ".auth_info")) or part == ".git"
                        for part in path.parts
                    )
                ):
                    raise ValueError("Invalid starter filename")
        value["bundle_digest"] = checksum
        return value
    except (ValueError, KeyError, TypeError, OSError):
        raise ConsoleError("app_setup_bundle_invalid", 503) from None


def render(template_id, *, app_id, title, repository, expected_digest):
    value = bundle()
    if value["bundle_digest"] != expected_digest:
        raise ConsoleError("app_setup_bundle_changed", 409)
    if template_id not in value["templates"]:
        raise ConsoleError("app_setup_invalid", 422)
    try:
        repository_identity(repository)
        if not repository.startswith("https://"):
            raise ValueError("Only credential-free HTTPS repository identities are accepted")
        entries = value["templates"][template_id]["files"].copy()
        manifest = json.loads(entries["app.manifest.json"])
        manifest["app_id"] = app_id
        manifest["display"]["name"] = title
        manifest["source"] = {"repository": repository, "directory": "."}
        validator().validate(manifest)
        entries["app.manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        return {name: text.encode() for name, text in entries.items()}
    except (ValueError, ValidationError):
        raise ConsoleError("app_setup_invalid", 422) from None
