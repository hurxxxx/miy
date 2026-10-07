"""One bounded, explicit Source PUT; no retry, allocation or publication authority."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
import hashlib
import logging
import os
import ssl
import stat
from threading import BoundedSemaphore
from urllib.parse import quote, urlsplit
from uuid import UUID

import certifi
import httpx
from minio import Minio

from miy_api.domains.files.selected_storage import SelectedStorageConfig

MAX_BYTES = 250 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
ACK_BYTES = 64 * 1024
TOTAL_SECONDS = 120.0
IO_SECONDS = 5.0
CLEANUP_SECONDS = 5.0
MAX_CONCURRENT_PUTS = 2
_slots = BoundedSemaphore(MAX_CONCURRENT_PUTS)
_private_io: ContextVar[bool] = ContextVar("file_publication_private_io", default=False)


class _PrivateTransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_io.get()


for _logger_name in ("httpcore.connection", "httpcore.http11", "httpcore.http2", "httpx"):
    logging.getLogger(_logger_name).addFilter(_PrivateTransportFilter())


@dataclass(frozen=True)
class PublishedObjectReceipt:
    publication_id: UUID
    operation_id: UUID
    size_bytes: int
    sha256: str
    version_id: str = field(repr=False)


class PublicationStorageRefused(ValueError):
    """Known no-dispatch control. Arguments never establish Source permission."""

    def __init__(self, code: str, publication_id: UUID | None, operation_id: UUID | None):
        super().__init__(code)
        self.code = code
        self.publication_id = publication_id
        self.operation_id = operation_id


class PublicationStorageUnknown(RuntimeError):
    """Same retained operation; no automatic second PUT or version fallback."""

    def __init__(self, code: str, publication_id: UUID, operation_id: UUID):
        super().__init__(code)
        self.code = code
        self.publication_id = publication_id
        self.operation_id = operation_id


class PublicationStorageCancelled(asyncio.CancelledError):
    """Cancellation after dispatch preserves the caller's exact operation IDs."""

    def __init__(self, publication_id: UUID, operation_id: UUID):
        super().__init__("storage_put_cancelled")
        self.code = "storage_put_cancelled"
        self.publication_id = publication_id
        self.operation_id = operation_id


class _InvalidInput(ValueError):
    pass


def _metadata(fd: int) -> tuple[int, int, int, int, int]:
    value = os.fstat(fd)
    if not stat.S_ISREG(value.st_mode):
        raise _InvalidInput("storage_spool_invalid")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _preflight(fd: int, size: int, sha256: str) -> tuple[int, int, int, int, int]:
    if type(fd) is not int or fd < 0:
        raise _InvalidInput("storage_spool_invalid")
    before = _metadata(fd)
    if before[2] != size:
        raise _InvalidInput("storage_spool_size")
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(CHUNK_BYTES, size - offset), offset)
        if not chunk:
            raise _InvalidInput("storage_spool_size")
        digest.update(chunk)
        offset += len(chunk)
    if os.pread(fd, 1, size) or _metadata(fd) != before:
        raise _InvalidInput("storage_spool_changed")
    if digest.hexdigest() != sha256:
        raise _InvalidInput("storage_spool_sha256")
    return before


def _signed_put_url(config: SelectedStorageConfig, storage_key: str) -> str:
    if not isinstance(config, SelectedStorageConfig):
        raise _InvalidInput("storage_configuration")
    for value in (
        config.endpoint,
        config.access_key,
        config.secret_key,
        config.bucket,
        config.region,
    ):
        if type(value) is not str or not value or any(ord(char) < 32 for char in value):
            raise _InvalidInput("storage_configuration")
    if (
        type(storage_key) is not str
        or not storage_key
        or len(storage_key.encode("utf-8")) > 1024
        or any(ord(char) < 32 or ord(char) == 127 for char in storage_key)
    ):
        raise _InvalidInput("storage_configuration")
    endpoint = urlsplit(config.endpoint)
    # urlsplit defers port validation until this public property is read.
    endpoint.port
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
        or any(char.isspace() or ord(char) == 127 for char in config.endpoint)
    ):
        raise _InvalidInput("storage_configuration")
    # Explicit static credentials and region keep this public SDK call local.
    client = Minio(
        endpoint.netloc,
        access_key=config.access_key,
        secret_key=config.secret_key,
        secure=endpoint.scheme == "https",
        region=config.region,
    )
    client.disable_virtual_style_endpoint()
    signed = client.presigned_put_object(config.bucket, storage_key, expires=timedelta(seconds=180))
    actual = urlsplit(signed)
    if (
        (actual.scheme, actual.hostname, actual.port)
        != (endpoint.scheme, endpoint.hostname, endpoint.port)
        or actual.username is not None
        or actual.password is not None
        or actual.fragment
        or actual.path != f"/{quote(config.bucket, safe='')}/{quote(storage_key, safe='/')}"
    ):
        raise _InvalidInput("storage_configuration")
    return signed


class _SpoolBody(httpx.AsyncByteStream):
    def __init__(self, fd: int, size: int, sha256: str, metadata: tuple[int, int, int, int, int]):
        self.fd = fd
        self.size = size
        self.sha256 = sha256
        self.metadata = metadata
        self.started = False
        # HTTPX may skip an empty iterator. Actual size/SHA/EOF already verified.
        self.complete = size == 0

    async def __aiter__(self):
        if self.started:
            raise _InvalidInput("storage_put_body_replayed")
        self.started = True
        digest = hashlib.sha256()
        offset = 0
        while offset < self.size:
            if _metadata(self.fd) != self.metadata:
                raise _InvalidInput("storage_put_body_changed")
            chunk = os.pread(self.fd, min(CHUNK_BYTES, self.size - offset), offset)
            if not chunk:
                raise _InvalidInput("storage_put_body_changed")
            digest.update(chunk)
            offset += len(chunk)
            yield chunk
        if (
            os.pread(self.fd, 1, self.size)
            or _metadata(self.fd) != self.metadata
            or digest.hexdigest() != self.sha256
        ):
            raise _InvalidInput("storage_put_body_changed")
        self.complete = True


def _version(response: httpx.Response) -> str:
    values = [value for name, value in response.headers.raw if name.lower() == b"x-amz-version-id"]
    if len(values) != 1 or not values[0] or len(values[0]) > 1024:
        raise _InvalidInput("storage_put_version")
    value = values[0].decode("utf-8")
    if value == "null" or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise _InvalidInput("storage_put_version")
    return value


async def _close_owned(value) -> None:
    if value is not None:
        try:
            async with asyncio.timeout(CLEANUP_SECONDS):
                await value.aclose()
        except BaseException:
            # Cleanup cannot replace known ACK or original unknown/cancellation.
            pass


async def publish_spooled_object(
    config: SelectedStorageConfig,
    *,
    publication_id: UUID,
    operation_id: UUID,
    storage_key: str,
    spool_fd: int,
    expected_size: int,
    expected_sha256: str,
) -> PublishedObjectReceipt:
    """Perform one PUT from a regular Source spool, retaining its caller-owned IDs.

    Current Source attempted permission/actor/app/tree admission belongs to the
    composing command. This transport creates no durable permission or IDs.
    No caller FD is closed. A post-dispatch error is never retry authorization.
    """
    valid_publication = publication_id if type(publication_id) is UUID else None
    valid_operation = operation_id if type(operation_id) is UUID else None
    if valid_publication is None or valid_operation is None:
        raise PublicationStorageRefused("storage_put_identity", valid_publication, valid_operation)
    if (
        type(expected_size) is not int
        or not 0 <= expected_size <= MAX_BYTES
        or type(expected_sha256) is not str
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
    ):
        raise PublicationStorageRefused("storage_put_input", publication_id, operation_id)
    if not _slots.acquire(blocking=False):
        raise PublicationStorageRefused("storage_put_busy", publication_id, operation_id)
    privacy_token = _private_io.set(True)
    dispatched = False
    transport = None
    response = None
    try:
        metadata = _preflight(spool_fd, expected_size, expected_sha256)
        signed = _signed_put_url(config, storage_key)
        body = _SpoolBody(spool_fd, expected_size, expected_sha256, metadata)
        request = httpx.Request(
            "PUT",
            signed,
            headers={
                "Content-Length": str(expected_size),
                "Content-Type": "application/octet-stream",
                "Accept-Encoding": "identity",
            },
            content=body,
            extensions={"timeout": dict.fromkeys(("connect", "read", "write", "pool"), IO_SECONDS)},
        )
        final = urlsplit(str(request.url))
        original = urlsplit(signed)
        if (final.scheme, final.hostname, final.port, final.path, final.query) != (
            original.scheme,
            original.hostname,
            original.port,
            original.path,
            original.query,
        ):
            raise _InvalidInput("storage_configuration")
        transport = httpx.AsyncHTTPTransport(
            verify=ssl.create_default_context(
                cafile=os.environ.get("SSL_CERT_FILE") or certifi.where()
            ),
            trust_env=False,
            retries=0,
            http2=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        async with asyncio.timeout(TOTAL_SECONDS):
            dispatched = True
            response = await transport.handle_async_request(request)
            if response.status_code != 200:
                raise _InvalidInput("storage_put_response")
            if response.headers.get_list("content-encoding") not in ([], ["identity"]):
                raise _InvalidInput("storage_put_response")
            version_id = _version(response)
            received = 0
            if not isinstance(response.stream, httpx.AsyncByteStream):
                raise _InvalidInput("storage_put_response")
            # Response.aiter_raw closes at EOF before returning. Consume the
            # public raw transport stream so cleanup cannot obscure an ACK.
            async for chunk in response.stream:
                if not isinstance(chunk, bytes):
                    raise _InvalidInput("storage_put_response")
                received += len(chunk)
                if received > ACK_BYTES:
                    raise _InvalidInput("storage_put_response_size")
            if not body.complete or _metadata(spool_fd) != metadata:
                raise _InvalidInput("storage_put_body_incomplete")
            return PublishedObjectReceipt(
                publication_id, operation_id, expected_size, expected_sha256, version_id
            )
    except asyncio.CancelledError:
        raise PublicationStorageCancelled(publication_id, operation_id) from None
    except BaseException as error:
        code = (
            str(error)
            if isinstance(error, _InvalidInput)
            else (
                "storage_put_interrupted"
                if not isinstance(error, Exception)
                else "storage_put_timeout"
                if isinstance(error, (TimeoutError, httpx.TimeoutException))
                else "storage_put_unknown"
                if dispatched
                else "storage_put_configuration"
            )
        )
        control = PublicationStorageUnknown if dispatched else PublicationStorageRefused
        raise control(code, publication_id, operation_id) from None
    finally:
        await _close_owned(response)
        await _close_owned(transport)
        _private_io.reset(privacy_token)
        _slots.release()
