"""Actual public SDK signing and bounded owned TCP; no live/shared storage."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
import os
import ssl
from threading import Barrier, Event
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


@pytest.mark.parametrize("case", ["ack", "early", "timeout"])
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
