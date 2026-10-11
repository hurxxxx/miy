from __future__ import annotations


class _FakeMinioObject:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.chunk_sizes: list[int] = []
        self.closed = False
        self.released = False

    def stream(self, chunk_size: int):
        self.chunk_sizes.append(chunk_size)
        for offset in range(0, len(self.data), chunk_size):
            yield self.data[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _FakeMinioClient:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str, bytes, int, str]] = []
        self.fput_calls: list[tuple[str, str, str, str | None]] = []
        self.objects: dict[str, _FakeMinioObject] = {}

    def put_object(self, bucket: str, key: str, data, length: int, content_type: str) -> None:
        self.put_calls.append((bucket, key, data.read(), length, content_type))

    def fput_object(
        self, bucket: str, key: str, path: str, content_type: str | None = None
    ) -> None:
        self.fput_calls.append((bucket, key, path, content_type))

    def get_object(self, bucket: str, key: str) -> _FakeMinioObject:
        del bucket
        return self.objects[key]
