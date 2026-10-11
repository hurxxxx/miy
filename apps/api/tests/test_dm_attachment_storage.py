from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO


class _FakeStorageClient:
    def __init__(self, *, storage_object: "_FakeStorageObject | None" = None) -> None:
        self.storage_object = storage_object
        self.put_calls = []
        self.remove_calls = []
        self.get_calls = []

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        *,
        length: int,
        content_type: str,
    ) -> None:
        self.put_calls.append((bucket_name, object_name, data, length, content_type, data.tell()))

    def remove_object(self, bucket_name: str, object_name: str) -> None:
        self.remove_calls.append((bucket_name, object_name))

    def get_object(self, bucket_name: str, object_name: str) -> "_FakeStorageObject":
        self.get_calls.append((bucket_name, object_name))
        assert self.storage_object is not None
        return self.storage_object


class _FakeStorageObject:
    def __init__(
        self,
        *,
        chunks: tuple[bytes, ...] = (b"chunk-a", b"chunk-b"),
        error: Exception | None = None,
    ) -> None:
        self.chunks = chunks
        self.error = error
        self.chunk_size: int | None = None
        self.closed = False
        self.released = False
        self.events: list[str] = []

    def stream(self, chunk_size: int) -> Iterator[bytes]:
        self.chunk_size = chunk_size
        self.events.append(f"stream:{chunk_size}")
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True
        self.events.append("close")

    def release_conn(self) -> None:
        self.released = True
        self.events.append("release")
