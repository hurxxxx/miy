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
)
from miy_api.domains.rag.providers.prepared_qdrant import (
    PreparedQdrantControlError,
    PreparedQdrantPolicy,
    prepared_qdrant_client,
)

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


def test_full_delete_also_scans_then_deletes_explicit_ids_without_count_or_filter_mutation():
    remote = Remote([([point(1), point(2)], None)])
    with adapter(remote) as client:
        assert client.delete_resource(request=deletion()) == 2
    assert not any(request.url.path.endswith("/count") for request, _ in remote.calls)
    assert remote.calls[-1][1] == {"points": [1, 2]}
    assert remote.calls[1][1]["with_payload"] is False


@pytest.mark.parametrize(
    "pages,policy,reason",
    [([([point(1), point(2)], None)], {"max_delete_ids": 1}, "delete_id_limit_exceeded")],
)
def test_scan_overflow_and_malformed_continuation_never_delete(pages, policy, reason):
    remote = Remote(pages)
    with adapter(remote, policy=PreparedQdrantPolicy(**policy)) as client:
        with pytest.raises(PreparedQdrantControlError) as error:
            client.delete_chunks_at_or_after(request=deletion(), chunk_index=1)
    assert error.value.reason == reason
    assert not any(request.url.path.endswith("/delete") for request, _ in remote.calls)


@pytest.mark.parametrize(
    "status,operation", [("acknowledged", "upsert"), ("wait_timeout", "delete")]
)
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


def test_aggregate_response_bytes_are_shared_across_methods():
    remote = Remote([([], None)])
    with adapter(remote, policy=PreparedQdrantPolicy(max_aggregate_response_bytes=100)) as client:
        with pytest.raises(PreparedQdrantControlError, match="aggregate_bytes_exceeded"):
            client.delete_resource(request=deletion())
    assert len(remote.calls) == 2


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


@pytest.mark.parametrize("mode", ["timeout", "redirect", "status"])
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
