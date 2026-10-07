"""Canonical origins shared by platform configuration and independent-app contracts."""

from urllib.parse import urlsplit


def exact_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid origin port") from exc
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
        or "\\" in value
    ):
        raise ValueError("Use an exact origin without credentials, path, query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("HTTP is restricted to loopback development")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    default_port = 443 if parsed.scheme == "https" else 80
    canonical = f"{parsed.scheme}://{host}" + (f":{port}" if port and port != default_port else "")
    if value != canonical:
        raise ValueError("Use the canonical origin")
    return canonical
