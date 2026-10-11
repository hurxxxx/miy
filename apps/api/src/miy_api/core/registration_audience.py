"""Exact Workbench base URLs; this validates configuration, never fetches URLs."""

from urllib.parse import urlsplit
import re

from miy_api.core.app_origins import exact_origin

CALLBACK_PATH = "/api/registration-authorizations/callback"


def registration_audience(value: str) -> str:
    parsed = urlsplit(value)
    origin = exact_origin(f"{parsed.scheme}://{parsed.netloc}")
    path = parsed.path
    if (
        len(value) > 500
        or value != origin + path
        or parsed.query
        or parsed.fragment
        or re.fullmatch(r"(?:/[A-Za-z0-9_-]+)*", path) is None
    ):
        raise ValueError("Use an exact canonical Workbench base URL without a trailing slash")
    return value
