from __future__ import annotations


from miy_api.domains.media.object_storage import (
    MediaObjectStorage,
)


def test_open_stream_streams_and_closes_storage_object() -> None:
    class FakeStorageObject:
        def __init__(self) -> None:
            self.chunk_size: int | None = None
            self.closed = False
            self.released = False

        def stream(self, amt: int):
            self.chunk_size = amt
            yield b"png-"
            yield b"bytes"

        def close(self) -> None:
            self.closed = True

        def release_conn(self) -> None:
            self.released = True

    class FakeClient:
        def __init__(self, obj: FakeStorageObject) -> None:
            self.obj = obj
            self.request: tuple[str, str] | None = None

        def get_object(self, bucket_name: str, object_name: str) -> FakeStorageObject:
            self.request = (bucket_name, object_name)
            return self.obj

    obj = FakeStorageObject()
    client = FakeClient(obj)
    storage = MediaObjectStorage(bucket_name="bucket", client=client)

    chunks = list(
        storage.open_stream(
            storage_key="media/user-1/media-1/fixture.png",
            chunk_size=16,
        )
    )

    assert chunks == [b"png-", b"bytes"]
    assert client.request == ("bucket", "media/user-1/media-1/fixture.png")
    assert obj.chunk_size == 16
    assert obj.closed is True
    assert obj.released is True
