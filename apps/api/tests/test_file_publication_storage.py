"""Actual public SDK signing and bounded owned TCP; no live/shared storage."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import logging
import os
import ssl
from threading import Barrier, Event
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest

from miy_api.domains.files import publication_storage as storage

PUB = UUID("11111111-1111-4111-8111-111111111111")
OP = UUID("22222222-2222-4222-8222-222222222222")
KEY = "files/synthetic/objects/11111111-1111-4111-8111-111111111111"


def config(port=9000):
    return storage.SelectedStorageConfig(
        endpoint=f"http://127.0.0.1:{port}",
        access_key="synthetic-access",
        secret_key="synthetic-secret",
        bucket="synthetic-bucket",
        region="us-east-1",
    )


@pytest.fixture
def spool(tmp_path):
    value = tmp_path / "source-spool"
    value.write_bytes(b"synthetic body")
    fd = os.open(value, os.O_RDONLY)
    try:
        yield value, fd
    finally:
        os.close(fd)


def arguments(fd, content=b"synthetic body"):
    return dict(
        publication_id=PUB,
        operation_id=OP,
        storage_key=KEY,
        spool_fd=fd,
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )


class AckBody(httpx.AsyncByteStream):
    def __init__(self, chunks=(b"",), close_error=None):
        self.chunks = chunks
        self.close_error = close_error
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def mock_transport(
    monkeypatch,
    *,
    consume=True,
    status=200,
    headers=None,
    chunks=(b"",),
    error=None,
    transport_close=None,
    response_close=None,
    before_read=None,
):
    observed = {"calls": 0, "chunks": [], "closed": False, "requests": []}
    ack = AckBody(chunks, response_close)

    class Transport:
        def __init__(self, **options):
            assert options["retries"] == 0 and options["trust_env"] is False
            assert options["http2"] is False
            assert isinstance(options["verify"], ssl.SSLContext)
            assert options["verify"].verify_mode == ssl.CERT_REQUIRED
            assert options["verify"].check_hostname

        async def handle_async_request(self, request):
            observed["calls"] += 1
            observed["requests"].append(request)
            assert request.method == "PUT"
            assert request.headers["Host"] == request.url.netloc.decode("ascii")
            assert request.extensions["timeout"] == dict.fromkeys(
                ("connect", "read", "write", "pool"), storage.IO_SECONDS
            )
            if before_read:
                before_read()
            if consume:
                async for chunk in request.stream:
                    observed["chunks"].append(chunk)
            if error:
                raise error
            return httpx.Response(
                status,
                headers=headers
                if headers is not None
                else [(b"x-amz-version-id", b"opaque+/=version")],
                stream=ack,
            )

        async def aclose(self):
            observed["closed"] = True
            if transport_close:
                raise transport_close

    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
    return observed, ack


def test_real_sdk_signing_is_local_and_exact(monkeypatch, spool):
    monkeypatch.setattr(storage.Minio, "_url_open", lambda *a, **k: pytest.fail("discovery I/O"))
    observed, ack = mock_transport(monkeypatch)
    result = asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert result == storage.PublishedObjectReceipt(
        PUB, OP, 14, hashlib.sha256(b"synthetic body").hexdigest(), "opaque+/=version"
    )
    parsed = urlsplit(str(observed["requests"][0].url))
    assert parsed.hostname == "127.0.0.1" and parsed.path == "/synthetic-bucket/" + KEY
    assert parse_qs(parsed.query)["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert b"".join(observed["chunks"]) == b"synthetic body"
    assert observed["calls"] == 1 and observed["closed"] and ack.closed
    assert "opaque" not in repr(result) and KEY not in repr(result)
    assert os.lseek(spool[1], 0, os.SEEK_CUR) == 0 and os.fstat(spool[1]).st_size == 14


@pytest.mark.parametrize("content", [b"", b"a" * (storage.CHUNK_BYTES * 2 + 9)])
def test_actual_empty_and_chunked_body_size_sha_eof(monkeypatch, tmp_path, content):
    path = tmp_path / "input"
    path.write_bytes(content)
    fd = os.open(path, os.O_RDONLY)
    observed, _ = mock_transport(monkeypatch, consume=bool(content))
    reads = []
    actual_pread = os.pread
    monkeypatch.setattr(
        storage.os,
        "pread",
        lambda fd, size, offset: (reads.append(size), actual_pread(fd, size, offset))[1],
    )
    try:
        result = asyncio.run(storage.publish_spooled_object(config(), **arguments(fd, content)))
        assert (
            result.size_bytes == len(content)
            and result.sha256 == hashlib.sha256(content).hexdigest()
        )
        assert b"".join(observed["chunks"]) == content
        assert max(reads) <= storage.CHUNK_BYTES and observed["calls"] == 1
        assert os.fstat(fd).st_size == len(content)
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    "field,value",
    [
        ("publication_id", str(PUB)),
        ("operation_id", None),
        ("spool_fd", True),
        ("expected_size", True),
        ("expected_size", -1),
        ("expected_size", storage.MAX_BYTES + 1),
        ("expected_sha256", "A" * 64),
        ("expected_sha256", "sensitive.invalid"),
        ("expected_sha256", "0" * 64),
        ("expected_size", 15),
    ],
)
def test_invalid_input_refuses_before_sdk_or_transport(monkeypatch, spool, field, value):
    monkeypatch.setattr(storage, "Minio", lambda *a, **k: pytest.fail("SDK construction"))
    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", lambda **k: pytest.fail("transport"))
    args = arguments(spool[1]) | {field: value}
    with pytest.raises(storage.PublicationStorageRefused) as result:
        asyncio.run(storage.publish_spooled_object(config(), **args))
    assert "sensitive" not in str(result.value) and KEY not in str(result.value)
    assert not storage._private_io.get()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://name:secret@127.0.0.1",
        "http://127.0.0.1?secret=value",
        "http://127.0.0.1#secret",
        "http://127.0.0.1/prefix",
        "http://127.0.0.1\n",
        "ftp://127.0.0.1",
        "http:///",
        "http://127.0.0.1:bad",
    ],
)
def test_bad_endpoint_refuses_before_sdk(monkeypatch, spool, endpoint):
    monkeypatch.setattr(storage, "Minio", lambda *a, **k: pytest.fail("SDK construction"))
    with pytest.raises(storage.PublicationStorageRefused) as result:
        asyncio.run(
            storage.publish_spooled_object(
                replace(config(), endpoint=endpoint), **arguments(spool[1])
            )
        )
    assert "secret" not in str(result.value)


def test_nonregular_or_closed_fd_cannot_dispatch(monkeypatch):
    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", lambda **k: pytest.fail("transport"))
    first, second = os.pipe()
    try:
        with pytest.raises(storage.PublicationStorageRefused):
            asyncio.run(storage.publish_spooled_object(config(), **arguments(first, b"")))
    finally:
        os.close(first)
        os.close(second)
    with pytest.raises(storage.PublicationStorageRefused):
        asyncio.run(storage.publish_spooled_object(config(), **arguments(first, b"")))


def test_request_url_normalization_cannot_change_logical_key(monkeypatch, spool):
    monkeypatch.setattr(
        storage.httpx, "AsyncHTTPTransport", lambda **k: pytest.fail("no changed-key dispatch")
    )
    with pytest.raises(storage.PublicationStorageRefused):
        asyncio.run(
            storage.publish_spooled_object(
                config(), **(arguments(spool[1]) | {"storage_key": "a/../private"})
            )
        )


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("x-amz-version-id", "null")],
        [("x-amz-version-id", "")],
        [("x-amz-version-id", "a"), ("x-amz-version-id", "b")],
        [("x-amz-version-id", "a" * 1025)],
        [(b"x-amz-version-id", b"\xff")],
        [("x-amz-version-id", "line\nbreak")],
    ],
)
def test_bad_version_is_same_identity_unknown(monkeypatch, spool, headers):
    observed, ack = mock_transport(monkeypatch, headers=headers)
    with pytest.raises(storage.PublicationStorageUnknown) as result:
        asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert result.value.publication_id == PUB and result.value.operation_id == OP
    assert observed["calls"] == 1 and observed["closed"] and ack.closed
    assert result.value.__suppress_context__ and KEY not in str(result.value)


@pytest.mark.parametrize("status", [201, 202, 204, 301, 307, 400, 500])
def test_non200_is_never_ack_or_retry(monkeypatch, spool, status):
    observed, _ = mock_transport(
        monkeypatch, status=status, headers={"Location": "https://secret.invalid/private"}
    )
    with pytest.raises(storage.PublicationStorageUnknown, match="storage_put_response"):
        asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert observed["calls"] == 1


@pytest.mark.parametrize("case", ["early", "mutated", "length", "compressed"])
def test_incomplete_or_changed_body_ack_is_unknown(monkeypatch, spool, case):
    options = {}
    if case == "early":
        options["consume"] = False
    elif case == "mutated":
        options["before_read"] = lambda: spool[0].write_bytes(b"different body")
    elif case == "length":
        options["chunks"] = [b"a" * storage.ACK_BYTES, b"b"]
    else:
        options["headers"] = {"x-amz-version-id": "v1", "Content-Encoding": "gzip"}
    observed, ack = mock_transport(monkeypatch, **options)
    with pytest.raises(storage.PublicationStorageUnknown):
        asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert observed["calls"] == 1 and observed["closed"]
    assert ack.closed == (case != "mutated")


@pytest.mark.parametrize("kind", ["ack", "failure", "cancel"])
def test_cleanup_cancellation_preserves_known_result_or_original_control(monkeypatch, spool, kind):
    options = dict(
        transport_close=KeyboardInterrupt("private close"),
        response_close=KeyboardInterrupt("private header"),
    )
    if kind == "failure":
        options["error"] = RuntimeError("secret URL/body")
    elif kind == "cancel":
        options["error"] = asyncio.CancelledError("secret cancellation")
    observed, _ = mock_transport(monkeypatch, **options)
    if kind == "ack":
        assert (
            asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1]))).version_id
            == "opaque+/=version"
        )
    else:
        expected = (
            storage.PublicationStorageCancelled
            if kind == "cancel"
            else storage.PublicationStorageUnknown
        )
        with pytest.raises(expected) as result:
            asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
        assert result.value.publication_id == PUB and result.value.operation_id == OP
        assert "private" not in str(result.value) and "secret" not in str(result.value)
    assert observed["calls"] == 1 and observed["closed"] and not storage._private_io.get()


def test_iterator_never_replays_bytes(monkeypatch, spool):
    calls = []

    class Transport:
        def __init__(self, **kwargs):
            pass

        async def handle_async_request(self, request):
            calls.append([chunk async for chunk in request.stream])
            calls.append([chunk async for chunk in request.stream])
            return httpx.Response(200)

        async def aclose(self):
            pass

    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
    with pytest.raises(storage.PublicationStorageUnknown, match="storage_put_body_replayed"):
        asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert calls == [[b"synthetic body"]]


def test_immediate_two_slot_bound_and_release_after_cancel(monkeypatch, spool):
    async def exercise():
        entered = asyncio.Event()
        release = asyncio.Event()
        count = 0

        class Transport:
            def __init__(self, **kwargs):
                pass

            async def handle_async_request(self, request):
                nonlocal count
                count += 1
                if count == 2:
                    entered.set()
                await release.wait()
                async for _chunk in request.stream:
                    pass
                return httpx.Response(200, headers={"x-amz-version-id": "v1"}, stream=AckBody())

            async def aclose(self):
                pass

        monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
        pending = [
            asyncio.create_task(storage.publish_spooled_object(config(), **arguments(spool[1])))
            for _ in range(2)
        ]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(storage.PublicationStorageRefused, match="storage_put_busy"):
                await storage.publish_spooled_object(config(), **arguments(spool[1]))
            assert count == 2
            pending[0].cancel()
            with pytest.raises(storage.PublicationStorageCancelled):
                await pending[0]
            release.set()
            assert (await pending[1]).version_id == "v1"
            assert (
                await storage.publish_spooled_object(config(), **arguments(spool[1]))
            ).version_id == "v1"
        finally:
            release.set()
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("case", ["ack", "early", "timeout", "cancel", "oversize", "redirect"])
def test_real_tcp_body_and_ack_boundaries(monkeypatch, spool, case, caplog):
    async def exercise():
        requests = []
        peers = set()
        body_seen = asyncio.Event()
        peer_done = asyncio.Event()
        if case == "timeout":
            monkeypatch.setattr(storage, "IO_SECONDS", 0.05)
            monkeypatch.setattr(storage, "TOTAL_SECONDS", 0.15)
        caplog.set_level(logging.DEBUG, logger="httpcore.http11")
        caplog.set_level(logging.DEBUG, logger="httpcore.connection")

        async def handle(reader, writer):
            peers.add(asyncio.current_task())
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                requests.append(header)
                if case != "early":
                    body = await reader.readexactly(14)
                    assert body == b"synthetic body"
                body_seen.set()
                if case in {"timeout", "cancel"}:
                    await reader.read()
                else:
                    status = b"307 Temporary Redirect" if case == "redirect" else b"200 OK"
                    data = b"a" * (storage.ACK_BYTES + 1) if case == "oversize" else b""
                    writer.write(
                        b"HTTP/1.1 "
                        + status
                        + b"\r\nContent-Length: "
                        + str(len(data)).encode()
                        + b"\r\nx-amz-version-id: actual-test-version\r\nX-Private-Header: secret-header\r\n"
                        + b"Location: http://secret.invalid/path\r\n\r\n"
                        + data
                    )
                    await writer.drain()
                    await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                peer_done.set()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        pending = asyncio.create_task(
            storage.publish_spooled_object(config(port), **arguments(spool[1]))
        )
        try:
            if case == "cancel":
                await asyncio.wait_for(body_seen.wait(), 1)
                pending.cancel()
                with pytest.raises(storage.PublicationStorageCancelled) as result:
                    await pending
                assert result.value.publication_id == PUB and result.value.operation_id == OP
            elif case in {"ack", "early"}:
                # HTTPX writes this small body before it reads response headers.
                assert (await pending).version_id == "actual-test-version"
            else:
                with pytest.raises(storage.PublicationStorageUnknown):
                    await pending
            await asyncio.wait_for(peer_done.wait(), 1)
            assert len(requests) == 1
            assert not any(
                "secret-header" in record.getMessage() or KEY in record.getMessage()
                for record in caplog.records
            )
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            server.close()
            await server.wait_closed()
            await asyncio.gather(*peers, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["transport", "body", "preflight"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_base_interruption_has_fixed_phase_control_and_original_ids(
    monkeypatch, spool, phase, error_type
):
    actual_pread = os.pread
    dispatched = False
    calls = 0

    class Transport:
        def __init__(self, **options):
            pass

        async def handle_async_request(self, request):
            nonlocal dispatched, calls
            dispatched = True
            calls += 1
            if phase == "transport":
                raise error_type("synthetic-private-body")
            async for _chunk in request.stream:
                pass
            raise AssertionError("expected interruption")

        async def aclose(self):
            pass

    def pread(fd, size, offset):
        if phase == "preflight" or (phase == "body" and dispatched):
            raise error_type("synthetic-private-body")
        return actual_pread(fd, size, offset)

    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
    monkeypatch.setattr(storage.os, "pread", pread)

    async def exercise():
        try:
            await storage.publish_spooled_object(config(), **arguments(spool[1]))
        except BaseException as result:
            expected = (
                storage.PublicationStorageRefused
                if phase == "preflight"
                else storage.PublicationStorageUnknown
            )
            assert isinstance(result, expected)
            assert result.code == "storage_put_interrupted"
            assert result.publication_id == PUB and result.operation_id == OP
            assert "private" not in str(result) and result.__suppress_context__
        else:
            pytest.fail("interruption returned ACK")
        assert calls == (0 if phase == "preflight" else 1)

    asyncio.run(exercise())


@pytest.mark.parametrize("case", ["ack", "timeout", "cancel"])
def test_never_returning_cleanup_has_its_own_finite_budget(monkeypatch, spool, case):
    async def exercise():
        entered = asyncio.Event()
        closed = []

        class NeverClosedBody(AckBody):
            async def aclose(self):
                closed.append("response")
                await asyncio.Event().wait()

        class Transport:
            def __init__(self, **options):
                pass

            async def handle_async_request(self, request):
                async for _chunk in request.stream:
                    pass
                entered.set()
                if case != "ack":
                    await asyncio.Event().wait()
                return httpx.Response(
                    200, headers={"x-amz-version-id": "v1"}, stream=NeverClosedBody()
                )

            async def aclose(self):
                closed.append("transport")
                await asyncio.Event().wait()

        monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
        monkeypatch.setattr(storage, "TOTAL_SECONDS", 0.02)
        monkeypatch.setattr(storage, "CLEANUP_SECONDS", 0.01, raising=False)
        start = asyncio.get_running_loop().time()
        pending = asyncio.create_task(
            storage.publish_spooled_object(config(), **arguments(spool[1]))
        )
        try:
            if case == "cancel":
                await asyncio.wait_for(entered.wait(), 0.1)
                pending.cancel()
            if case == "ack":
                assert (await asyncio.wait_for(pending, 0.15)).version_id == "v1"
            else:
                error = (
                    storage.PublicationStorageCancelled
                    if case == "cancel"
                    else storage.PublicationStorageUnknown
                )
                with pytest.raises(error) as result:
                    await asyncio.wait_for(pending, 0.15)
                assert result.value.publication_id == PUB and result.value.operation_id == OP
            assert asyncio.get_running_loop().time() - start < 0.12
            assert closed == (["response", "transport"] if case == "ack" else ["transport"])
            assert storage._slots.acquire(blocking=False)
            storage._slots.release()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("version", [b"opaque version+/=", "opaque-雪".encode(), b"opaque" * 170])
def test_version_is_bounded_opaque_utf8_not_uuid(monkeypatch, spool, version):
    mock_transport(monkeypatch, headers=[(b"x-amz-version-id", version)])
    result = asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    assert result.version_id == version.decode("utf-8")


def test_explicit_private_ca_policy_keeps_verification(monkeypatch, spool):
    # Only an artificial config value; no real environment file/value is read.
    monkeypatch.setenv("SSL_CERT_FILE", "synthetic-private-ca.pem")
    observed = []
    actual_create = ssl.create_default_context

    def create_context(*args, **kwargs):
        observed.append(kwargs["cafile"])
        return actual_create(cafile=storage.certifi.where())

    monkeypatch.setattr(storage.ssl, "create_default_context", create_context)
    mock_transport(monkeypatch)
    assert asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1]))).version_id
    assert observed == ["synthetic-private-ca.pem"]


def test_slots_are_process_wide_across_event_loops_threads(monkeypatch, spool):
    entered = Barrier(3)
    release = Event()

    class Transport:
        def __init__(self, **options):
            pass

        async def handle_async_request(self, request):
            entered.wait(timeout=2)
            while not release.is_set():
                await asyncio.sleep(0.001)
            async for _chunk in request.stream:
                pass
            return httpx.Response(200, headers={"x-amz-version-id": "v1"}, stream=AckBody())

        async def aclose(self):
            pass

    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)

    def invoke():
        return asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke) for _ in range(2)]
        try:
            entered.wait(timeout=2)
            with pytest.raises(storage.PublicationStorageRefused, match="storage_put_busy"):
                invoke()
        finally:
            release.set()
        assert [future.result(timeout=2).version_id for future in futures] == ["v1", "v1"]


def test_private_logs_do_not_hide_unrelated_thread_logs(monkeypatch, spool, caplog):
    # Keep the real filter while isolating capture from Alembic and app logging.
    logger = logging.getLogger("httpcore.http11")
    caplog.set_level(logging.DEBUG, logger=logger.name)
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    assert logger.isEnabledFor(logging.DEBUG)

    class Transport:
        def __init__(self, **options):
            pass

        async def handle_async_request(self, request):
            logging.getLogger("httpcore.http11").debug("synthetic-private-key-header")
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(
                    logging.getLogger("httpcore.http11").debug, "unrelated-client-event"
                ).result(timeout=1)
            async for _chunk in request.stream:
                pass
            return httpx.Response(200, headers={"x-amz-version-id": "v1"}, stream=AckBody())

        async def aclose(self):
            pass

    monkeypatch.setattr(storage.httpx, "AsyncHTTPTransport", Transport)
    asyncio.run(storage.publish_spooled_object(config(), **arguments(spool[1])))
    messages = [record.getMessage() for record in caplog.records]
    assert "unrelated-client-event" in messages and "synthetic-private-key-header" not in messages


def test_real_total_deadline_stops_trickling_ack_and_closes_socket(monkeypatch, spool):
    async def exercise():
        peer_done = asyncio.Event()
        calls = []
        peers = set()

        async def handle(reader, writer):
            peers.add(asyncio.current_task())
            try:
                await reader.readuntil(b"\r\n\r\n")
                assert await reader.readexactly(14) == b"synthetic body"
                calls.append("PUT")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nx-amz-version-id: v1\r\n\r\n"
                )
                for _ in range(100):
                    writer.write(b"a")
                    await writer.drain()
                    await asyncio.sleep(0.01)
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
                peer_done.set()

        monkeypatch.setattr(storage, "TOTAL_SECONDS", 0.08)
        monkeypatch.setattr(storage, "IO_SECONDS", 0.05)
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        try:
            start = asyncio.get_running_loop().time()
            with pytest.raises(
                storage.PublicationStorageUnknown, match="storage_put_timeout"
            ) as result:
                await storage.publish_spooled_object(
                    config(server.sockets[0].getsockname()[1]), **arguments(spool[1])
                )
            elapsed = asyncio.get_running_loop().time() - start
            assert 0.06 <= elapsed < 0.5
            assert result.value.publication_id == PUB and result.value.operation_id == OP
            await asyncio.wait_for(peer_done.wait(), 1)
            assert calls == ["PUT"]
        finally:
            server.close()
            await server.wait_closed()
            await asyncio.gather(*peers, return_exceptions=True)

    asyncio.run(exercise())
