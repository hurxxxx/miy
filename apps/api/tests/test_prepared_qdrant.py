from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import socket
from threading import Thread
import time
import uuid

import httpx
import pytest

from miy_api.domains.rag.contracts import (
    RagChunk,
    RagDeleteRequest,
    RagProjection,
    RagUpsertRequest,
    RagVectorRecord,
    RagVectorSearchRequest,
)
from miy_api.domains.rag.providers.prepared_qdrant import (
    PreparedQdrantControlError,
    PreparedQdrantPolicy,
    prepared_qdrant_client,
)
from miy_api.domains.rag.service import RagService

COLLECTION = "prepared-files-vector"
PARTITION = str(uuid.UUID(int=11))


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Stream(httpx.SyncByteStream):
    def __init__(self, chunks, *, close_error=None):
        self.chunks = chunks
        self.close_error = close_error
        self.closed = 0

    def __iter__(self):
        yield from self.chunks

    def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error


class Remote(httpx.BaseTransport):
    def __init__(self, pages=(), *, exists=True, ack="completed", handler=None, close_error=None):
        self.pages = iter(pages)
        self.exists = exists
        self.ack = ack
        self.handler = handler
        self.calls = []
        self.closed = 0
        self.close_error = close_error

    def handle_request(self, request):
        body = json.loads(request.content) if request.content else None
        self.calls.append((request, body))
        if self.handler:
            return self.handler(request)
        path = request.url.path
        if path.endswith("/exists"):
            result = {"exists": self.exists}
        elif path.endswith("/scroll"):
            points, offset = next(self.pages)
            result = {"points": points, "next_page_offset": offset}
        elif path.endswith("/delete") or request.method == "PUT":
            result = {"operation_id": 1, "status": self.ack}
        else:
            result = collection_info()
        return httpx.Response(200, json={"result": result, "status": "ok", "time": 0.0})

    def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error


def point(identity, index=1):
    return {"id": identity, "payload": {"chunk_metadata": {"chunk_index": index}}}


def deletion():
    return RagDeleteRequest(
        collection=COLLECTION,
        retrieval_partition_id=PARTITION,
        resource_type="file_manager_file",
        resource_id="file-one",
    )


def projection():
    return RagProjection(
        retrieval_partition_id=PARTITION,
        projection_version=3,
        resource_type="file_manager_file",
        resource_id="file-one",
        source_kind="files",
        chunks=[RagChunk(chunk_id="one", text="synthetic")],
    )


def upsert():
    projected = projection()
    return (
        RagUpsertRequest(collection=COLLECTION, projection=projected, chunks=projected.chunks),
        [
            RagVectorRecord(
                chunk_id="one", text="synthetic", embedding=[1.0, 0.0], projection=projected
            )
        ],
    )


def collection_info():
    return {
        "status": "green",
        "optimizer_status": "ok",
        "segments_count": 1,
        "config": {
            "params": {
                "vectors": {"dense": {"size": 2, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {}},
            },
            "hnsw_config": {"m": 16, "ef_construct": 100, "full_scan_threshold": 10000},
            "optimizer_config": {
                "deleted_threshold": 0.2,
                "vacuum_min_vector_number": 1000,
                "default_segment_number": 0,
                "max_segment_size": None,
                "memmap_threshold": None,
                "indexing_threshold": 20000,
                "flush_interval_sec": 5,
                "max_optimization_threads": None,
            },
            "wal_config": {"wal_capacity_mb": 32, "wal_segments_ahead": 0},
        },
        "payload_schema": {
            "retrieval_partition_id": {"data_type": "keyword", "points": 0},
            "projection_version": {"data_type": "integer", "points": 0},
            **{
                key: {"data_type": "keyword", "points": 0}
                for key in (
                    "scope_kind",
                    "resource_type",
                    "resource_id",
                    "source_kind",
                    "visibility_refs",
                )
            },
        },
    }


def adapter(remote, **kwargs):
    return prepared_qdrant_client(
        collection=COLLECTION, url="https://qdrant.invalid", _transport=remote, **kwargs
    )


@pytest.mark.parametrize(
    "name",
    [
        "page_size",
        "max_scroll_pages",
        "max_scanned_points",
        "max_delete_ids",
        "max_response_bytes",
        "max_requests",
        "max_aggregate_response_bytes",
    ],
)
@pytest.mark.parametrize("value", [True, 1.0, "1", 0, -1, 2**80])
def test_integer_policy_requires_exact_positive_lower_only(name, value):
    with pytest.raises(PreparedQdrantControlError, match="policy_invalid"):
        PreparedQdrantPolicy(**{name: value})


@pytest.mark.parametrize("name", ["elapsed_budget_seconds", "phase_timeout_seconds"])
@pytest.mark.parametrize("value", [True, "1", 0, -1, float("nan"), float("inf"), 121])
def test_time_policy_requires_finite_positive_lower_only(name, value):
    with pytest.raises(PreparedQdrantControlError, match="policy_invalid"):
        PreparedQdrantPolicy(**{name: value})


def test_constructor_does_zero_network_and_preserves_bound_collection(monkeypatch):
    def background(*args, **kwargs):
        pytest.fail("compatibility background thread forbidden")

    monkeypatch.setattr("qdrant_client.qdrant_remote.Thread", background)
    remote = Remote()
    with adapter(remote) as client:
        assert remote.calls == []
        assert client.for_partitioned_generation(collection=COLLECTION) is client
        with pytest.raises(PreparedQdrantControlError, match="collection_mismatch"):
            client.for_partitioned_generation(collection="another")
    assert remote.closed == 1


def test_existing_target_schema_is_validated_without_creation_or_indexes():
    remote = Remote()
    with adapter(remote) as client:
        client.ensure_collection(collection=COLLECTION, dense_dimensions=2)
    assert len(remote.calls) == 3
    assert all(request.method == "GET" for request, _ in remote.calls)


@pytest.mark.parametrize("problem", ["missing", "dimensions", "indexes"])
def test_bad_target_refuses_without_setup(problem):
    remote = Remote(exists=problem != "missing")
    if problem != "missing":
        info = collection_info()
        if problem == "dimensions":
            info["config"]["params"]["vectors"]["dense"]["size"] = 3
        else:
            info["payload_schema"].pop("projection_version")

        def handler(request):
            if request.url.path.endswith("/exists"):
                return httpx.Response(200, json={"result": {"exists": True}, "status": "ok"})
            return httpx.Response(200, json={"result": info, "status": "ok"})

        remote.handler = handler
    with adapter(remote) as client, pytest.raises(PreparedQdrantControlError) as error:
        client.ensure_collection(collection=COLLECTION, dense_dimensions=2)
    assert error.value.reason in {"target_missing", "target_schema_invalid"}
    assert all(request.method == "GET" for request, _ in remote.calls)


@pytest.mark.parametrize("method", ["healthcheck", "query", "delete_collection"])
def test_nonmaterialization_calls_are_refused_without_requests(method):
    remote = Remote()
    with adapter(remote) as client, pytest.raises(PreparedQdrantControlError):
        if method == "query":
            client.query(request=RagVectorSearchRequest(collection=COLLECTION, query="x"))
        elif method == "delete_collection":
            client.delete_collection(collection=COLLECTION)
        else:
            client.healthcheck()
    assert remote.calls == []


def test_stale_delete_uses_exact_partition_resource_and_legacy_index_semantics():
    remote = Remote([([point(1, 0), point(2, "2"), point(3, 3)], 7), ([point(4, False)], None)])
    with adapter(remote) as client:
        assert client.delete_chunks_at_or_after(request=deletion(), chunk_index=2) == 2
    scrolls = [body for request, body in remote.calls if request.url.path.endswith("/scroll")]
    assert scrolls[0]["limit"] == 128
    assert scrolls[0]["with_vector"] is False
    assert scrolls[0]["with_payload"] == ["chunk_metadata.chunk_index"]
    assert scrolls[0]["filter"]["must"] == [
        {"key": "retrieval_partition_id", "match": {"value": PARTITION}},
        {"key": "resource_type", "match": {"value": "file_manager_file"}},
        {"key": "resource_id", "match": {"value": "file-one"}},
    ]
    deletes = [body for request, body in remote.calls if request.url.path.endswith("/delete")]
    assert deletes == [{"points": [2, 3]}]
    assert "wait=true" in str(remote.calls[-1][0].url)


def test_full_delete_also_scans_then_deletes_explicit_ids_without_count_or_filter_mutation():
    remote = Remote([([point(1), point(2)], None)])
    with adapter(remote) as client:
        assert client.delete_resource(request=deletion()) == 2
    assert not any(request.url.path.endswith("/count") for request, _ in remote.calls)
    assert remote.calls[-1][1] == {"points": [1, 2]}
    assert remote.calls[1][1]["with_payload"] is False


@pytest.mark.parametrize("full", [True, False])
def test_empty_scan_does_zero_deletes(full):
    remote = Remote([([], None)])
    with adapter(remote) as client:
        result = (
            client.delete_resource(request=deletion())
            if full
            else client.delete_chunks_at_or_after(request=deletion(), chunk_index=1)
        )
        assert result == 0
    assert len(remote.calls) == 2


@pytest.mark.parametrize(
    "pages,policy,reason",
    [
        ([([point(1), point(2)], None)], {"page_size": 1}, "page_size_exceeded"),
        ([([point(1), point(2)], None)], {"max_scanned_points": 1}, "point_limit_exceeded"),
        ([([point(1), point(2)], None)], {"max_delete_ids": 1}, "delete_id_limit_exceeded"),
        ([([point(1)], 7)], {"max_scroll_pages": 1}, "scroll_page_limit_exceeded"),
        ([([point(1)], 7), ([point(2)], 7)], {}, "offset_cycle"),
        ([([point(1)], 7), ([point(2)], 8), ([point(3)], 7)], {}, "offset_cycle"),
        ([([point(1)], 7), ([point(1)], None)], {}, "duplicate_point"),
        ([([point(1)], "invalid")], {}, "point_id_invalid"),
    ],
)
def test_scan_overflow_and_malformed_continuation_never_delete(pages, policy, reason):
    remote = Remote(pages)
    with adapter(remote, policy=PreparedQdrantPolicy(**policy)) as client:
        with pytest.raises(PreparedQdrantControlError) as error:
            client.delete_chunks_at_or_after(request=deletion(), chunk_index=1)
    assert error.value.reason == reason
    assert not any(request.url.path.endswith("/delete") for request, _ in remote.calls)


def test_exact_page_boundary_completes():
    remote = Remote([([point(1)], 7), ([point(2)], None)])
    with adapter(remote, policy=PreparedQdrantPolicy(page_size=1, max_scroll_pages=2)) as client:
        assert client.delete_resource(request=deletion()) == 2


@pytest.mark.parametrize("status", ["acknowledged", "wait_timeout", "invalid", None])
@pytest.mark.parametrize("operation", ["upsert", "delete"])
def test_mutation_requires_completed_ack(operation, status):
    remote = Remote([([point(1)], None)], ack=status)
    with adapter(remote) as client, pytest.raises(PreparedQdrantControlError):
        if operation == "upsert":
            request, records = upsert()
            client.upsert_chunks(request=request, records=records)
        else:
            client.delete_resource(request=deletion())
    assert (
        len(
            [
                request
                for request, _ in remote.calls
                if request.method == "PUT" or request.url.path.endswith("/delete")
            ]
        )
        == 1
    )


def test_upsert_reuses_existing_canonical_point_identity():
    remote = Remote()
    with adapter(remote) as client:
        request, records = upsert()
        assert client.upsert_chunks(request=request, records=records) == 1
    payload = remote.calls[0][1]["points"][0]
    assert payload["payload"]["retrieval_partition_id"] == PARTITION
    assert payload["payload"]["projection_version"] == 3
    assert uuid.UUID(payload["id"])


def test_cross_resource_upsert_refuses_without_requests():
    remote = Remote()
    request, records = upsert()
    records[0].projection = records[0].projection.model_copy(update={"resource_id": "another"})
    with (
        adapter(remote) as client,
        pytest.raises(PreparedQdrantControlError, match="projection_mismatch"),
    ):
        client.upsert_chunks(request=request, records=records)
    assert remote.calls == []


def test_existing_rag_fenced_public_api_calls_prewrite_once():
    class Embedding:
        provider_name = "synthetic-embedding"

        def __init__(self):
            self.calls = 0

        def embed_texts(self, texts, timeout_seconds=None):
            self.calls += 1
            return [[1.0, 0.0] for _ in texts]

    remote = Remote([([], None)])
    embedding = Embedding()
    fences = []
    with adapter(remote) as client:
        service = RagService(vector_index=client, embedding_client=embedding)
        result = service.sync_projection_with_fence(
            projection(),
            collection=COLLECTION,
            before_vector_write=lambda: fences.append("current-core-fence"),
        )
    assert result.chunk_count == 1
    assert embedding.calls == 1
    assert fences == ["current-core-fence"]
    assert len([request for request, _ in remote.calls if request.method == "PUT"]) == 1


def test_strict_timeout_is_clamped_after_sdk_request_override():
    clock = Clock()
    remote = Remote([([], None)])
    with adapter(
        remote,
        policy=PreparedQdrantPolicy(elapsed_budget_seconds=3, phase_timeout_seconds=2),
        _clock=clock,
    ) as client:
        client._call(client._client.scroll, collection_name=COLLECTION, timeout=99)
    assert remote.calls[0][0].extensions["timeout"] == {
        key: 2 for key in ("connect", "read", "write", "pool")
    }
    assert remote.calls[0][0].headers["Accept-Encoding"] == "identity"


def test_elapsed_budget_is_not_reset_between_requests_or_pages():
    clock = Clock()
    remote = Remote([([], 7), ([], None)])
    original = remote.handle_request

    def handle(request):
        response = original(request)
        clock.now += 0.6
        return response

    remote.handle_request = handle
    with adapter(
        remote, policy=PreparedQdrantPolicy(elapsed_budget_seconds=1), _clock=clock
    ) as client:
        with pytest.raises(PreparedQdrantControlError, match="elapsed_budget_exhausted"):
            client.delete_resource(request=deletion())
    assert len(remote.calls) == 2
    assert remote.calls[1][0].extensions["timeout"]["read"] == pytest.approx(0.4)


def test_request_limit_includes_exists_before_scan():
    remote = Remote([([], None)])
    with adapter(remote, policy=PreparedQdrantPolicy(max_requests=1)) as client:
        with pytest.raises(PreparedQdrantControlError, match="request_limit_exceeded"):
            client.delete_resource(request=deletion())
    assert len(remote.calls) == 1


@pytest.mark.parametrize("kind", ["response", "aggregate", "compressed", "redirect"])
def test_transport_refuses_before_sdk_json_parse_and_closes_original_stream(kind):
    stream = Stream([b"{", b"synthetic-provider-body-secret" * 3])
    headers = {"content-encoding": "gzip"} if kind == "compressed" else {}
    status = 302 if kind == "redirect" else 200
    remote = Remote(handler=lambda request: httpx.Response(status, headers=headers, stream=stream))
    policy = (
        PreparedQdrantPolicy(max_response_bytes=8)
        if kind == "response"
        else PreparedQdrantPolicy(max_aggregate_response_bytes=8)
        if kind == "aggregate"
        else PreparedQdrantPolicy()
    )
    with adapter(remote, policy=policy) as client:
        with pytest.raises(PreparedQdrantControlError) as error:
            client.delete_resource(request=deletion())
    assert (
        error.value.reason
        == {
            "response": "response_bytes_exceeded",
            "aggregate": "aggregate_bytes_exceeded",
            "compressed": "response_encoding_forbidden",
            "redirect": "redirect_forbidden",
        }[kind]
    )
    assert "secret" not in str(error.value)
    assert stream.closed == 1
    assert len(remote.calls) == 1


def test_aggregate_response_bytes_are_shared_across_methods():
    remote = Remote([([], None)])
    with adapter(remote, policy=PreparedQdrantPolicy(max_aggregate_response_bytes=100)) as client:
        with pytest.raises(PreparedQdrantControlError, match="aggregate_bytes_exceeded"):
            client.delete_resource(request=deletion())
    assert len(remote.calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("synthetic-url-secret"),
        TypeError("unexpected timeout"),
        RuntimeError("synthetic-provider-body-secret"),
    ],
)
def test_sdk_wrapped_failure_has_fixed_control_and_no_retry(error):
    def fail(request):
        raise error

    remote = Remote(handler=fail)
    with adapter(remote) as client, pytest.raises(PreparedQdrantControlError) as controlled:
        client.delete_resource(request=deletion())
    assert len(remote.calls) == 1
    assert "secret" not in str(controlled.value)
    assert (
        controlled.value.reason == "phase_timeout"
        if isinstance(error, httpx.TimeoutException)
        else controlled.value.reason == "remote_failed"
    )


def test_cleanup_cancellation_keeps_known_ack_and_original_body_control():
    remote = Remote(close_error=KeyboardInterrupt())
    with adapter(remote) as client:
        request, records = upsert()
        assert client.upsert_chunks(request=request, records=records) == 1
    assert remote.closed == 1
    original = PreparedQdrantControlError("synthetic-original")
    with pytest.raises(PreparedQdrantControlError) as controlled:
        with adapter(Remote(close_error=KeyboardInterrupt())):
            raise original
    assert controlled.value is original


@contextmanager
def tcp_server(response):
    listener = socket.socket()
    listener.settimeout(1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    calls = []

    def serve():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(1)
                data = conn.recv(65536)
                calls.append(data)
                response(conn)
        except (TimeoutError, BrokenPipeError, ConnectionResetError, OSError):
            pass

    thread = Thread(target=serve)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", calls
    finally:
        listener.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("mode", ["timeout", "bytes", "redirect", "status"])
def test_loopback_actual_public_sdk_phase_cap_byte_cap_no_redirect_or_retry(mode):
    def response(conn):
        if mode == "timeout":
            time.sleep(0.2)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        elif mode == "bytes":
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 128\r\n\r\n" + b"x" * 128)
        elif mode == "redirect":
            conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: /another\r\nContent-Length: 0\r\n\r\n")
        else:
            conn.sendall(b"HTTP/1.1 503 Unavailable\r\nContent-Length: 2\r\n\r\n{}")

    policy = PreparedQdrantPolicy(phase_timeout_seconds=0.05, max_response_bytes=64)
    with tcp_server(response) as (url, calls):
        with prepared_qdrant_client(collection=COLLECTION, url=url, policy=policy) as client:
            with pytest.raises(PreparedQdrantControlError) as error:
                client.delete_resource(request=deletion())
        assert len(calls) == 1
    assert (
        error.value.reason
        == {
            "timeout": "phase_timeout",
            "bytes": "response_bytes_exceeded",
            "redirect": "redirect_forbidden",
            "status": "remote_failed",
        }[mode]
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://synthetic-user:synthetic-secret@qdrant.invalid",
        "https://qdrant.invalid?synthetic-secret=1",
        "https://qdrant.invalid#synthetic-secret",
        "https://qdrant.invalid/collections/private",
        "https://qdrant.invalid/\n",
        "https://qdrant.invalid/\t",
        "file:///synthetic-private",
        "https:///missing-host",
    ],
)
def test_invalid_endpoint_refuses_before_sdk_or_transport(monkeypatch, url):
    constructor_calls = []

    def constructor(*args, **kwargs):
        constructor_calls.append(kwargs)
        pytest.fail("invalid endpoint reached SDK")

    monkeypatch.setattr("miy_api.domains.rag.providers.prepared_qdrant.QdrantClient", constructor)
    with pytest.raises(PreparedQdrantControlError) as error:
        with prepared_qdrant_client(collection=COLLECTION, url=url, _transport=Remote()):
            pass
    assert error.value.reason == "endpoint_invalid"
    assert constructor_calls == []
    assert "synthetic-secret" not in str(error.value)


@pytest.fixture
def transport_log_capture(caplog, monkeypatch):
    # Alembic may disable existing loggers, and the app suppresses their parents.
    # Capture only these emitters, retaining their real ContextVar filters.
    for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
        logger = logging.getLogger(name)
        caplog.set_level(logging.DEBUG, logger=name)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        assert logger.isEnabledFor(logging.DEBUG)
    return caplog


def test_loopback_private_transport_logs_are_suppressed_only_in_prepared_context(
    transport_log_capture,
):
    caplog = transport_log_capture

    def response(conn):
        content = b'{"result":{"exists":false},"status":"ok"}'
        conn.sendall(
            b"HTTP/1.1 200 OK\r\nX-Synthetic-Private: synthetic-private-header\r\nContent-Length: "
            + str(len(content)).encode()
            + b"\r\n\r\n"
            + content
        )

    with tcp_server(response) as (url, calls):
        with prepared_qdrant_client(
            collection=COLLECTION, url=url, api_key="synthetic-private-key"
        ) as client:
            with pytest.raises(PreparedQdrantControlError, match="target_missing"):
                client.delete_resource(request=deletion())
        assert len(calls) == 1
    assert not any(record.name.startswith(("httpx", "httpcore")) for record in caplog.records)
    assert "synthetic-private" not in caplog.text
    logging.getLogger("httpx").info("unrelated-client-still-logged")
    logging.getLogger("httpcore.http11").debug("unrelated-core-still-logged")
    assert "unrelated-client-still-logged" in caplog.text
    assert "unrelated-core-still-logged" in caplog.text


def test_concurrent_unrelated_client_logging_remains_visible_during_private_request(
    transport_log_capture,
):
    caplog = transport_log_capture

    def handle(request):
        def unrelated_logs():
            logging.getLogger("httpx").info("concurrent-client-visible")
            logging.getLogger("httpcore.http11").debug("concurrent-core-visible")

        other = Thread(target=unrelated_logs)
        other.start()
        other.join(timeout=1)
        assert not other.is_alive()
        logging.getLogger("httpcore.http11").debug("private-current-request-hidden")
        return httpx.Response(200, json={"result": {"exists": False}, "status": "ok"})

    with adapter(Remote(handler=handle)) as client:
        with pytest.raises(PreparedQdrantControlError, match="target_missing"):
            client.delete_resource(request=deletion())
    assert "concurrent-client-visible" in caplog.text
    assert "concurrent-core-visible" in caplog.text
    assert "private-current-request-hidden" not in caplog.text
    assert "HTTP Request:" not in caplog.text


def test_rejected_chunk_is_charged_and_exhausted_aggregate_blocks_another_request():
    remote = Remote(handler=lambda request: httpx.Response(200, stream=Stream([b"{", b"x" * 32])))
    policy = PreparedQdrantPolicy(max_response_bytes=8, max_aggregate_response_bytes=16)
    with adapter(remote, policy=policy) as client:
        with pytest.raises(PreparedQdrantControlError, match="response_bytes_exceeded"):
            client.delete_resource(request=deletion())
        assert client._budget.response_bytes == 33
        with pytest.raises(PreparedQdrantControlError, match="aggregate_bytes_exceeded"):
            client.delete_resource(request=deletion())
    assert len(remote.calls) == 1


@pytest.mark.parametrize(
    "metadata", [["synthetic-invalid"], {"chunk_index": "9" * 5000}, {"chunk_index": "²"}]
)
def test_malformed_legacy_chunk_selector_has_fixed_control_and_zero_delete(metadata):
    remote = Remote([([{"id": 1, "payload": {"chunk_metadata": metadata}}], None)])
    with adapter(remote) as client:
        with pytest.raises(PreparedQdrantControlError) as error:
            client.delete_chunks_at_or_after(request=deletion(), chunk_index=1)
    assert error.value.reason == "chunk_payload_invalid"
    assert len(remote.calls) == 2
    assert not any(request.url.path.endswith("/delete") for request, _ in remote.calls)
