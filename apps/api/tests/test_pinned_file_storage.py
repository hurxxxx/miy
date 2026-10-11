"""Pinned public presigning and real bounded TCP reads; no live storage access."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from miy_api.domains.files import selected_storage as storage


def config(port=9000):
    return storage.SelectedStorageConfig(
        endpoint=f"http://127.0.0.1:{port}",
        access_key="synthetic-access-key",
        secret_key="synthetic-secret-key",
        bucket="synthetic-bucket",
        region="us-east-1",
    )


def test_opaque_version_is_signed_locally_as_one_exact_query_value(monkeypatch):
    monkeypatch.setattr(
        storage.Minio, "_url_open", lambda *args, **kwargs: pytest.fail("no discovery I/O")
    )
    version = "opaque+/=version&part?%25"
    value = storage._signed_url(config(), "private/input", version_id=version)
    parsed = urlsplit(value)
    assert parsed.path == "/synthetic-bucket/private/input"
    assert parse_qs(parsed.query)["versionId"] == [version]
    assert "X-Amz-Signature" in parse_qs(parsed.query)


@pytest.mark.parametrize("version", [None, "", "null", 12, "line\nbreak", "\ud800"])
def test_pinned_reader_refuses_missing_mutable_or_invalid_version_before_io(version, monkeypatch):
    monkeypatch.setattr(
        storage, "read_selected_object", lambda *args, **kwargs: pytest.fail("no latest read")
    )
    with pytest.raises(storage.SelectedStorageUnavailable, match="storage_object_version"):
        asyncio.run(
            storage.read_pinned_object(
                config(), storage_key="private/input", version_id=version, expected_size=4
            )
        )
    assert storage._active_reads == 0


def test_presigner_cannot_silently_drop_or_replace_the_requested_version(monkeypatch):
    def dropped(_self, bucket, key, **_kwargs):
        return f"http://127.0.0.1:9000/{bucket}/{key}?versionId=other"

    monkeypatch.setattr(storage.Minio, "presigned_get_object", dropped)
    with pytest.raises(storage.SelectedStorageUnavailable, match="storage_configuration"):
        storage._signed_url(config(), "private/input", version_id="original")


@pytest.mark.parametrize("exists", [True, False])
def test_real_peer_receives_exact_version_once_and_missing_never_reads_latest(exists):
    async def exercise():
        requests = []
        peers = set()
        peer_closed = asyncio.Event()

        async def handle(reader, writer):
            peers.add(asyncio.current_task())
            try:
                request = await reader.readuntil(b"\r\n\r\n")
                requests.append(request.split(b" ", 2)[1].decode("ascii"))
                if exists:
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\ndata")
                else:
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                peer_closed.set()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            pending = storage.read_pinned_object(
                config(port),
                storage_key="private/input",
                version_id="opaque+/=version",
                expected_size=4,
            )
            if exists:
                assert await pending == b"data"
            else:
                with pytest.raises(storage.SelectedStorageUnavailable, match="storage_unavailable"):
                    await pending
            await asyncio.wait_for(peer_closed.wait(), 1)
            assert len(requests) == 1
            assert parse_qs(urlsplit(requests[0]).query)["versionId"] == ["opaque+/=version"]
            assert storage._active_reads == 0
        finally:
            server.close()
            await server.wait_closed()
            await asyncio.gather(*peers)

    asyncio.run(exercise())
