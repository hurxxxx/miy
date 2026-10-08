"""Bounded selected-file reads; the normal Files storage client is unchanged.

MinIO's public presigner is local only because region and static credentials are
explicit. The signed URL stays inside this adapter. AsyncHTTPTransport avoids
AsyncClient's URL logging and permits cancellation of the actual socket I/O.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
import ssl
from urllib.parse import parse_qs, quote, urlsplit

import certifi
import httpx
from minio import Minio

MAX_BYTES = 10 * 1024 * 1024
READ_SECONDS = 10.0
MAX_CONCURRENT_READS = 4
_active_reads = 0
_private_io: ContextVar[bool] = ContextVar("selected_file_private_io", default=False)


class _PrivateTransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpcore DEBUG includes response headers (including an upstream
        # redirect's signed Location). Suppress only this task's private I/O;
        # unrelated clients and application events retain their normal logging.
        return not _private_io.get()


for _logger_name in ("httpcore.connection", "httpcore.http11"):
    logging.getLogger(_logger_name).addFilter(_PrivateTransportFilter())


class SelectedStorageUnavailable(ValueError):
    """Only a stable, non-sensitive error leaves this boundary."""


class SelectedFileTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class SelectedStorageConfig:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str


def _tls_context() -> ssl.SSLContext:
    # Preserve the existing MinIO client's CA policy without inheriting proxy
    # URLs or disabling hostname/certificate verification on the new transport.
    return ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or certifi.where())


def _require_object_version(version_id: str) -> None:
    # S3's literal null version is mutable. Keep real version IDs opaque; this
    # is a bounded transport contract, not a MinIO-specific UUID restriction.
    if (
        type(version_id) is not str
        or not version_id
        or version_id == "null"
        or len(version_id) > 1024
        or any(ord(char) < 32 or ord(char) == 127 for char in version_id)
    ):
        raise SelectedStorageUnavailable("storage_object_version")
    try:
        encoded = version_id.encode("utf-8")
    except UnicodeError:
        raise SelectedStorageUnavailable("storage_object_version") from None
    if len(encoded) > 1024:
        raise SelectedStorageUnavailable("storage_object_version")


def _signed_url(
    config: SelectedStorageConfig, storage_key: str, *, version_id: str | None = None
) -> str:
    if version_id is not None:
        _require_object_version(version_id)
    endpoint = urlsplit(config.endpoint)
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
        or not config.region
        or not config.access_key
        or not config.secret_key
        or not storage_key
        or len(storage_key) > 1024
    ):
        raise SelectedStorageUnavailable("storage_configuration")
    client = Minio(
        endpoint.netloc,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=endpoint.scheme == "https",
        region=config.region,
    )
    # MinIO-style path addressing only. A presigner must not redirect this
    # bounded reader to an inferred AWS bucket hostname or another authority.
    client.disable_virtual_style_endpoint()
    version_options = {"version_id": version_id} if version_id is not None else {}
    signed = client.presigned_get_object(
        config.bucket, storage_key, expires=timedelta(seconds=30), **version_options
    )
    actual = urlsplit(signed)
    if (
        (actual.scheme, actual.hostname, actual.port)
        != (endpoint.scheme, endpoint.hostname, endpoint.port)
        or actual.username
        or actual.password
        or actual.fragment
        or actual.path != f"/{quote(config.bucket, safe='')}/{quote(storage_key, safe='/')}"
        or (
            version_id is not None
            and parse_qs(actual.query, keep_blank_values=True).get("versionId") != [version_id]
        )
    ):
        raise SelectedStorageUnavailable("storage_configuration")
    return signed


async def read_selected_object(
    config: SelectedStorageConfig,
    *,
    storage_key: str,
    expected_size: int,
    version_id: str | None = None,
) -> bytes:
    """Return the complete selected object or no bytes; never persist a copy."""
    global _active_reads
    if expected_size < 0 or expected_size > MAX_BYTES:
        raise SelectedFileTooLarge("file_size_exceeded")
    # The API awaits this only on its event loop: check/increment have no await.
    # No pending queue or abandoned executor thread accumulates under overload.
    if _active_reads >= MAX_CONCURRENT_READS:
        raise SelectedStorageUnavailable("storage_busy")
    _active_reads += 1
    privacy_token = _private_io.set(True)
    try:
        signed = (
            _signed_url(config, storage_key)
            if version_id is None
            else _signed_url(config, storage_key, version_id=version_id)
        )
        request = httpx.Request(
            "GET",
            signed,
            headers={"Accept-Encoding": "identity"},
            extensions={"timeout": {"connect": 2.0, "read": 2.0, "write": 2.0, "pool": 2.0}},
        )
        async with asyncio.timeout(READ_SECONDS):
            async with httpx.AsyncHTTPTransport(
                verify=_tls_context(),
                trust_env=False,
                retries=0,
                http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            ) as transport:
                response = await transport.handle_async_request(request)
                try:
                    lengths = response.headers.get_list("content-length")
                    if (
                        response.status_code != 200
                        or response.headers.get("content-encoding", "identity") != "identity"
                        or len(lengths) != 1
                        or not lengths[0].isascii()
                        or not lengths[0].isdecimal()
                        or int(lengths[0]) != expected_size
                    ):
                        raise SelectedStorageUnavailable("storage_response")
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise SelectedFileTooLarge("file_size_exceeded")
                        if len(body) + len(chunk) > expected_size:
                            raise SelectedStorageUnavailable("storage_response")
                        body.extend(chunk)
                    if len(body) != expected_size:
                        raise SelectedStorageUnavailable("storage_response")
                    return bytes(body)
                finally:
                    await response.aclose()
    except asyncio.CancelledError:
        raise
    except SelectedFileTooLarge:
        raise
    except Exception:
        # httpx / presigner errors may embed signed URLs or object keys. Do not
        # expose their message or traceback context to API handlers or logs.
        raise SelectedStorageUnavailable("storage_unavailable") from None
    finally:
        _private_io.reset(privacy_token)
        _active_reads -= 1


async def read_pinned_object(
    config: SelectedStorageConfig, *, storage_key: str, version_id: str, expected_size: int
) -> bytes:
    """Read one exact published version, with no latest-version fallback.

    Source publication owns the trusted key/version binding. Passing a version
    here grants neither Source admission nor resource access.
    """
    _require_object_version(version_id)
    return await read_selected_object(
        config, storage_key=storage_key, expected_size=expected_size, version_id=version_id
    )
