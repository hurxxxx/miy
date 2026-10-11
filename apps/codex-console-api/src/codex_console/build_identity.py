"""Immutable release identity captured when this process starts, not checkout HEAD."""

import json
import re
from pathlib import Path


def read_identity(path):
    try:
        if path.is_symlink() or path.stat().st_size > 4096:
            return None
        data = json.loads(path.read_text())
        if (
            not isinstance(data, dict)
            or not re.fullmatch(r"[0-9a-f]{40}", data.get("source_revision", ""))
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", data.get("digest", ""))
            or type(data.get("source_dirty")) is not bool
        ):
            return None
        return {k: data[k] for k in ("source_revision", "source_dirty", "digest")}
    except (OSError, ValueError, TypeError, RecursionError):
        return None


RELEASE_IDENTITY = read_identity(Path(__file__).with_name("_build.json"))
