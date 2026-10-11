from __future__ import annotations

import asyncio
import logging
import ssl
import time
import traceback
from dataclasses import replace

import pytest

from miy_api.domains.files import selected_storage as storage
from miy_api.core.logging_security import install_sensitive_http_logging_guard


def _config(port=9000):
    return storage.SelectedStorageConfig(
        endpoint=f"http://127.0.0.1:{port}",
        access_key="synthetic-access-key",
        secret_key="synthetic-secret-key",
        bucket="synthetic-bucket",
        region="us-east-1",
    )


def test_presign_is_local_fixed_authority_and_escaped_path(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("Presign must never contact storage")

    monkeypatch.setattr(storage.Minio, "_url_open", forbid)
    value = storage._signed_url(_config(), "files/synthetic name%?#.bin")
    assert value.startswith(
        "http://127.0.0.1:9000/synthetic-bucket/files/synthetic%20name%25%3F%23.bin?"
    )
    assert "X-Amz-Signature=" in value


def test_transport_keeps_verified_tls_and_existing_minio_ca_precedence(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    context = storage._tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    calls = []

    def create_default_context(*, cafile):
        calls.append(cafile)
        return context

    monkeypatch.setattr(storage.ssl, "create_default_context", create_default_context)
    monkeypatch.setenv("SSL_CERT_FILE", "/synthetic/ca.pem")
    assert storage._tls_context() is context and calls == ["/synthetic/ca.pem"]
    monkeypatch.delenv("SSL_CERT_FILE")
    assert storage._tls_context() is context and calls[-1] == storage.certifi.where()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:pass@example.test",
        "https://example.test/path",
        "https://example.test?query=1",
        "ftp://example.test",
        "https://example.test#fragment",
    ],
)
def test_configured_url_rejects_credentials_or_extra_components(endpoint):
    with pytest.raises(storage.SelectedStorageUnavailable):
        storage._signed_url(replace(_config(), endpoint=endpoint), "file")


@pytest.mark.parametrize(
    "mode",
    [
        "good",
        "zero",
        "headers",
        "body",
        "oversize",
        "mismatch",
        "truncated",
        "redirect",
        "encoding",
        "duplicate_length",
        "cancel",
    ],
)
def test_real_async_socket_deadline_closes_peer_and_hides_private_headers(
    mode, monkeypatch, caplog
):
    monkeypatch.setattr(storage, "READ_SECONDS", 0.12)
    # Exercise the same precondition as a combined API suite, then deliberately
    # turn DEBUG on for this test to stress the adapter's own narrow filter.
    for name in ("httpx", "httpx2", "httpcore"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "level", logger.level)
        monkeypatch.setattr(logger, "propagate", logger.propagate)
    install_sensitive_http_logging_guard()
    caplog.set_level(logging.DEBUG)
    # The API's normal logging guard disables HTTP internals. Explicitly stress
    # this adapter with DEBUG enabled, independently of prior API fixtures.
    caplog.set_level(logging.DEBUG, logger="httpcore")
    monkeypatch.setattr(logging.getLogger("httpcore"), "propagate", True)
    for name in ("httpcore.connection", "httpcore.http11"):
        logger = logging.getLogger(name)
        caplog.set_level(logging.DEBUG, logger=name)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        assert logger.isEnabledFor(logging.DEBUG)

    async def exercise():
        peer_closed = asyncio.Event()
        header_written = asyncio.Event()
        request_seen = asyncio.Event()
        handlers = set()

        async def handler(reader, writer):
            handlers.add(asyncio.current_task())
            try:
                request = await reader.readuntil(b"\r\n\r\n")
                assert b"X-Amz-Signature=" in request
                request_seen.set()
                if mode == "headers":
                    await reader.read()
                    return
                if mode == "redirect":
                    headers = b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\nLocation: https://invalid.test/?X-Amz-Signature=PRIVATE-REDIRECT\r\n"
                else:
                    length = {"zero": 0, "oversize": storage.MAX_BYTES + 1, "mismatch": 5}.get(
                        mode, 4
                    )
                    headers = f"HTTP/1.1 200 OK\r\nContent-Length: {length}\r\n".encode()
                    if mode == "encoding":
                        headers += b"Content-Encoding: gzip\r\n"
                    if mode == "duplicate_length":
                        headers += b"Content-Length: 5\r\n"
                headers += b"X-Amz-Meta-Private: SYNTHETIC-PRIVATE-METADATA\r\n\r\n"
                writer.write(headers)
                if mode in {"good", "encoding", "mismatch", "oversize"}:
                    writer.write(b"data")
                elif mode == "truncated":
                    writer.write(b"da")
                await writer.drain()
                header_written.set()
                if mode == "truncated":
                    writer.close()
                    await writer.wait_closed()
                else:
                    await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                peer_closed.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        expected = 0 if mode == "zero" else 4
        started = time.monotonic()
        try:
            task = asyncio.create_task(
                storage.read_selected_object(
                    _config(port),
                    storage_key="SYNTHETIC-PRIVATE-OBJECT",
                    expected_size=expected,
                )
            )
            if mode == "cancel":
                await asyncio.wait_for(header_written.wait(), 1)
                task.cancel()
            if mode in {"good", "zero"}:
                assert await task == (b"data" if mode == "good" else b"")
            elif mode == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(storage.SelectedStorageUnavailable) as caught:
                    await task
                rendered = "".join(traceback.format_exception(caught.value))
                assert "X-Amz-Signature" not in rendered
                assert "SYNTHETIC-PRIVATE" not in rendered
            assert time.monotonic() - started < 1.0
            await asyncio.wait_for(request_seen.wait(), 1)
            await asyncio.wait_for(peer_closed.wait(), 1)
            assert storage._active_reads == 0
        finally:
            server.close()
            await server.wait_closed()
            await asyncio.gather(*handlers)

    asyncio.run(exercise())
    assert not storage._private_io.get()
    assert "X-Amz-Signature" not in caplog.text
    assert "synthetic-secret-key" not in caplog.text
    assert "SYNTHETIC-PRIVATE" not in caplog.text
    assert "PRIVATE-REDIRECT" not in caplog.text
    logging.getLogger("httpcore.connection").debug("unrelated-client-still-visible")
    assert "unrelated-client-still-visible" in caplog.text


def test_size_and_concurrency_fail_before_presign(monkeypatch):
    monkeypatch.setattr(storage, "_signed_url", lambda *args: pytest.fail("must not sign/open"))
    with pytest.raises(storage.SelectedFileTooLarge):
        asyncio.run(
            storage.read_selected_object(
                _config(), storage_key="x", expected_size=storage.MAX_BYTES + 1
            )
        )
    monkeypatch.setattr(storage, "_active_reads", storage.MAX_CONCURRENT_READS)
    with pytest.raises(storage.SelectedStorageUnavailable):
        asyncio.run(storage.read_selected_object(_config(), storage_key="x", expected_size=1))
    assert storage._active_reads == storage.MAX_CONCURRENT_READS
