"""Prepared-only finite Qdrant REST work; not a hard cancellation deadline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from functools import wraps
import logging
import math
import time
from typing import Any, TypeVar
import uuid
from urllib.parse import urlsplit

import httpx
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException

from miy_api.domains.rag.contracts import (
    RagDeleteRequest,
    RagProviderHealth,
    RagUpsertRequest,
    RagVectorRecord,
    RagVectorSearchHit,
    RagVectorSearchRequest,
)
from miy_api.domains.rag.providers.base import RagProviderConfigurationError
from miy_api.domains.rag.providers.qdrant import (
    QdrantVectorIndexClient,
    _chunk_index_from_payload,
    _require_projection_fence,
)

_T = TypeVar("_T")
_private_io: ContextVar[bool] = ContextVar("prepared_qdrant_private_io", default=False)


class _PrivateTransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _private_io.get()


for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_logger_name).addFilter(_PrivateTransportFilter())


def _private_transport_logs(function):
    @wraps(function)
    def scoped(*args, **kwargs):
        token = _private_io.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _private_io.reset(token)

    return scoped


class PreparedQdrantControlError(RuntimeError):
    """Fixed internal identifiers; never retain request/provider exception text."""

    code = "prepared_qdrant_refused"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"{self.code}:{reason}")


def _validate_endpoint(url: str) -> None:
    if (
        type(url) is not str
        or not url
        or len(url) > 2048
        or any(ord(character) <= 32 or ord(character) == 127 for character in url)
        or "?" in url
        or "#" in url
    ):
        raise PreparedQdrantControlError("endpoint_invalid")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and (parsed.port is None or parsed.port > 0)
            and bool(httpx.URL(url).host)
        )
    except (ValueError, httpx.InvalidURL):
        valid = False
    if not valid:
        raise PreparedQdrantControlError("endpoint_invalid")


@dataclass(frozen=True, slots=True)
class PreparedQdrantPolicy:
    elapsed_budget_seconds: float = 120.0
    phase_timeout_seconds: float = 5.0
    page_size: int = 128
    max_scroll_pages: int = 64
    max_scanned_points: int = 8192
    max_delete_ids: int = 8192
    max_response_bytes: int = 4 * 1024 * 1024
    max_requests: int = 96
    max_aggregate_response_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        ceilings = {
            "elapsed_budget_seconds": 120.0,
            "phase_timeout_seconds": 5.0,
            "page_size": 128,
            "max_scroll_pages": 64,
            "max_scanned_points": 8192,
            "max_delete_ids": 8192,
            "max_response_bytes": 4 * 1024 * 1024,
            "max_requests": 96,
            "max_aggregate_response_bytes": 64 * 1024 * 1024,
        }
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("_seconds"):
                if type(value) not in (int, float) or not 0 < value <= ceilings[field.name]:
                    raise PreparedQdrantControlError("policy_invalid")
                if not math.isfinite(value):
                    raise PreparedQdrantControlError("policy_invalid")
            elif type(value) is not int or not 0 < value <= ceilings[field.name]:
                raise PreparedQdrantControlError("policy_invalid")


class _Budget:
    def __init__(self, policy: PreparedQdrantPolicy, clock: Callable[[], float]):
        policy.validate()
        self.policy = policy
        self.clock = clock
        self.deadline = clock() + policy.elapsed_budget_seconds
        self.requests = 0
        self.response_bytes = 0

    def remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if not math.isfinite(remaining) or remaining <= 0:
            raise PreparedQdrantControlError("elapsed_budget_exhausted")
        return remaining

    def begin_request(self) -> float:
        remaining = self.remaining()
        if self.response_bytes >= self.policy.max_aggregate_response_bytes:
            raise PreparedQdrantControlError("aggregate_bytes_exceeded")
        if self.requests >= self.policy.max_requests:
            raise PreparedQdrantControlError("request_limit_exceeded")
        self.requests += 1
        return min(remaining, self.policy.phase_timeout_seconds)

    def read_bytes(self, count: int, response_bytes: int) -> None:
        # Charge bytes already received, including the crossing/late chunk.
        self.response_bytes += count
        self.remaining()
        if response_bytes + count > self.policy.max_response_bytes:
            raise PreparedQdrantControlError("response_bytes_exceeded")
        if self.response_bytes > self.policy.max_aggregate_response_bytes:
            raise PreparedQdrantControlError("aggregate_bytes_exceeded")


class _BoundedResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpx.Response, budget: _Budget):
        self.response = response
        self.budget = budget
        self.bytes_read = 0

    def __iter__(self) -> Iterator[bytes]:
        iterator = iter(self.response.stream)
        while True:
            self.budget.remaining()
            try:
                chunk = next(iterator)
            except StopIteration:
                self.budget.remaining()
                return
            self.budget.read_bytes(len(chunk), self.bytes_read)
            self.bytes_read += len(chunk)
            yield chunk

    def close(self) -> None:
        # Cleanup may not replace the retained effect control or a known ACK.
        try:
            self.response.close()
        except BaseException:
            pass


class _BudgetTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport, budget: _Budget):
        self.inner = inner
        self.budget = budget
        self.closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        timeout = self.budget.begin_request()
        request.extensions["timeout"] = {
            name: timeout for name in ("connect", "read", "write", "pool")
        }
        request.headers["Accept-Encoding"] = "identity"
        response = self.inner.handle_request(request)
        try:
            self.budget.remaining()
            if 300 <= response.status_code < 400:
                raise PreparedQdrantControlError("redirect_forbidden")
            encoding = response.headers.get("content-encoding", "identity").strip().lower()
            if encoding != "identity":
                raise PreparedQdrantControlError("response_encoding_forbidden")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=_BoundedResponseStream(response, self.budget),
                extensions=response.extensions,
            )
        except BaseException:
            try:
                response.close()
            except BaseException:
                pass
            raise

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.inner.close()


class PreparedQdrantVectorIndexClient(QdrantVectorIndexClient):
    """One owned finite REST budget bound to an already prepared collection."""

    @_private_transport_logs
    def __init__(
        self,
        *,
        collection: str,
        url: str,
        api_key: str | None = None,
        policy: PreparedQdrantPolicy | None = None,
        _transport: httpx.BaseTransport | None = None,
        _clock: Callable[[], float] = time.monotonic,
    ) -> None:
        resolved = policy if policy is not None else PreparedQdrantPolicy()
        if type(resolved) is not PreparedQdrantPolicy:
            raise PreparedQdrantControlError("policy_invalid")
        resolved.validate()
        _validate_endpoint(url)
        if type(collection) is not str or not collection or len(collection) > 255:
            raise PreparedQdrantControlError("collection_invalid")
        self._budget = _Budget(resolved, _clock)
        self._closed = False
        inner = _transport
        if inner is None:
            inner = httpx.HTTPTransport(
                retries=0,
                trust_env=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            )
        self._owned_transport = _BudgetTransport(inner, self._budget)
        try:
            client = QdrantClient(
                url=url,
                api_key=api_key,
                prefer_grpc=False,
                check_compatibility=False,
                timeout=math.ceil(resolved.phase_timeout_seconds),
                transport=self._owned_transport,
                trust_env=False,
                follow_redirects=False,
            )
            super().__init__(
                client=client,
                partitioned_generation=True,
                generation_collection=collection,
            )
            self._budget.remaining()
        except PreparedQdrantControlError:
            self.close()
            raise
        except Exception:
            self.close()
            raise PreparedQdrantControlError("construction_failed") from None
        except BaseException:
            self.close()
            raise

    @_private_transport_logs
    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for close in (
            getattr(getattr(self, "_client", None), "close", None),
            self._owned_transport.close,
        ):
            if close is not None:
                try:
                    close()
                except BaseException:
                    pass

    @_private_transport_logs
    def _call(self, function: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        if self._closed:
            raise PreparedQdrantControlError("client_closed")
        self._budget.remaining()
        try:
            result = function(*args, **kwargs)
        except PreparedQdrantControlError:
            raise
        except Exception as error:
            source = error
            for _ in range(4):
                if not isinstance(source, ResponseHandlingException):
                    break
                source = source.source
            if isinstance(source, PreparedQdrantControlError):
                raise source from None
            if isinstance(source, httpx.TimeoutException):
                raise PreparedQdrantControlError("phase_timeout") from None
            if isinstance(source, RagProviderConfigurationError):
                raise PreparedQdrantControlError("target_schema_invalid") from None
            raise PreparedQdrantControlError("remote_failed") from None
        self._budget.remaining()
        return result

    def _require_bound_collection(self, collection: str) -> None:
        if collection != self._generation_collection:
            raise PreparedQdrantControlError("collection_mismatch")

    def for_partitioned_generation(self, *, collection: str) -> PreparedQdrantVectorIndexClient:
        self._require_bound_collection(collection)
        return self

    def healthcheck(self) -> RagProviderHealth:
        raise PreparedQdrantControlError("healthcheck_unsupported")

    def query(
        self, *, request: RagVectorSearchRequest, timeout_seconds: float | None = None
    ) -> list[RagVectorSearchHit]:
        raise PreparedQdrantControlError("query_unsupported")

    def delete_collection(self, *, collection: str) -> bool:
        raise PreparedQdrantControlError("collection_delete_unsupported")

    def ensure_collection(
        self, *, collection: str, dense_dimensions: int, sparse_enabled: bool = True
    ) -> None:
        self._require_bound_collection(collection)
        if type(dense_dimensions) is not int or dense_dimensions <= 0:
            raise PreparedQdrantControlError("dimensions_invalid")
        if type(sparse_enabled) is not bool:
            raise PreparedQdrantControlError("schema_input_invalid")
        if not self._call(self._client.collection_exists, collection_name=collection):
            raise PreparedQdrantControlError("target_missing")
        self._call(
            self._validate_collection_schema,
            collection=collection,
            dense_dimensions=dense_dimensions,
            sparse_enabled=sparse_enabled,
        )
        self._call(self._validate_partitioned_payload_indexes, collection=collection)

    def _filter(self, request: RagDeleteRequest) -> models.Filter:
        self._require_bound_collection(request.collection)
        try:
            return self._resource_filter(
                retrieval_partition_id=request.retrieval_partition_id,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                scope_kind=request.scope_kind,
            )
        except Exception:
            raise PreparedQdrantControlError("projection_invalid") from None

    def _completed(self, result: models.UpdateResult) -> None:
        if (
            not isinstance(result, models.UpdateResult)
            or result.status is not models.UpdateStatus.COMPLETED
        ):
            raise PreparedQdrantControlError("update_not_completed")

    def upsert_chunks(self, *, request: RagUpsertRequest, records: list[RagVectorRecord]) -> int:
        self._require_bound_collection(request.collection)
        if len(records) > self._budget.policy.max_scanned_points:
            raise PreparedQdrantControlError("point_limit_exceeded")
        try:
            _require_projection_fence(request.projection)
            for record in records:
                _require_projection_fence(record.projection)
                if (
                    record.projection.retrieval_partition_id,
                    record.projection.projection_version,
                    record.projection.resource_type,
                    record.projection.resource_id,
                ) != (
                    request.projection.retrieval_partition_id,
                    request.projection.projection_version,
                    request.projection.resource_type,
                    request.projection.resource_id,
                ):
                    raise PreparedQdrantControlError("projection_mismatch")
            points = [self._to_point(request.collection, record) for record in records]
        except PreparedQdrantControlError:
            raise
        except Exception:
            raise PreparedQdrantControlError("projection_invalid") from None
        if not records:
            return 0
        result = self._call(
            self._client.upsert, collection_name=request.collection, points=points, wait=True
        )
        self._completed(result)
        return len(records)

    def delete_resource(self, *, request: RagDeleteRequest) -> int:
        return self._delete_scanned(request=request, chunk_index=None)

    def delete_chunks_at_or_after(self, *, request: RagDeleteRequest, chunk_index: int) -> int:
        if type(chunk_index) is not int or not -(2**63) <= chunk_index < 2**63:
            raise PreparedQdrantControlError("chunk_index_invalid")
        return self._delete_scanned(
            request=request, chunk_index=None if chunk_index <= 0 else chunk_index
        )

    def _delete_scanned(self, *, request: RagDeleteRequest, chunk_index: int | None) -> int:
        resource_filter = self._filter(request)
        if not self._call(self._client.collection_exists, collection_name=request.collection):
            raise PreparedQdrantControlError("target_missing")
        offset = None
        offsets: set[tuple[str, Any]] = set()
        seen_ids: set[tuple[str, Any]] = set()
        point_ids: list[models.ExtendedPointId] = []
        scanned = 0
        policy = self._budget.policy
        for _ in range(policy.max_scroll_pages):
            records, next_offset = self._call(
                self._client.scroll,
                collection_name=request.collection,
                scroll_filter=resource_filter,
                limit=policy.page_size,
                offset=offset,
                with_payload=["chunk_metadata.chunk_index"] if chunk_index is not None else False,
                with_vectors=False,
            )
            if len(records) > policy.page_size:
                raise PreparedQdrantControlError("page_size_exceeded")
            scanned += len(records)
            if scanned > policy.max_scanned_points:
                raise PreparedQdrantControlError("point_limit_exceeded")
            for record in records:
                identity = _point_identity(record.id)
                if identity in seen_ids:
                    raise PreparedQdrantControlError("duplicate_point")
                seen_ids.add(identity)
                if chunk_index is None or _checked_chunk_index(record.payload or {}) >= chunk_index:
                    if len(point_ids) >= policy.max_delete_ids:
                        raise PreparedQdrantControlError("delete_id_limit_exceeded")
                    point_ids.append(record.id)
            if next_offset is None:
                break
            identity = _point_identity(next_offset)
            if identity in offsets:
                raise PreparedQdrantControlError("offset_cycle")
            offsets.add(identity)
            offset = next_offset
        else:
            raise PreparedQdrantControlError("scroll_page_limit_exceeded")
        if not point_ids:
            return 0
        result = self._call(
            self._client.delete,
            collection_name=request.collection,
            points_selector=point_ids,
            wait=True,
        )
        self._completed(result)
        return len(point_ids)


def _checked_chunk_index(payload: dict[str, Any]) -> int:
    try:
        return _chunk_index_from_payload(payload)
    except (AttributeError, TypeError, ValueError):
        raise PreparedQdrantControlError("chunk_payload_invalid") from None


def _point_identity(value: Any) -> tuple[str, Any]:
    if type(value) is int and 0 <= value <= 2**64 - 1:
        return ("integer", value)
    if isinstance(value, uuid.UUID):
        return ("uuid", str(value))
    if type(value) is str and len(value) == 36:
        try:
            return ("uuid", str(uuid.UUID(value)))
        except ValueError:
            pass
    raise PreparedQdrantControlError("point_id_invalid")


@contextmanager
def prepared_qdrant_client(
    *,
    collection: str,
    url: str,
    api_key: str | None = None,
    policy: PreparedQdrantPolicy | None = None,
    _transport: httpx.BaseTransport | None = None,
    _clock: Callable[[], float] = time.monotonic,
) -> Iterator[PreparedQdrantVectorIndexClient]:
    adapter = PreparedQdrantVectorIndexClient(
        collection=collection,
        url=url,
        api_key=api_key,
        policy=policy,
        _transport=_transport,
        _clock=_clock,
    )
    try:
        yield adapter
    finally:
        adapter.close()
