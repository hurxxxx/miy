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
