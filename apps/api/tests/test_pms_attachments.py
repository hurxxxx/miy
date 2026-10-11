from __future__ import annotations


def _install_fake_store(monkeypatch, store: "_FakeTaskAttachmentStore") -> None:
    from miy_api.domains.pms import attachments

    monkeypatch.setattr(attachments, "task_attachment_object_store", lambda: store)


class _FakeTaskAttachmentStore:
    def __init__(self, *, remove_raises: bool = False) -> None:
        self.remove_raises = remove_raises
        self.puts: list[dict] = []
        self.removes: list[str] = []

    def put(
        self,
        *,
        storage_key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.puts.append(
            {
                "storage_key": storage_key,
                "content": content,
                "content_type": content_type,
            }
        )

    def remove(self, *, storage_key: str) -> None:
        self.removes.append(storage_key)
        if self.remove_raises:
            raise FileNotFoundError(storage_key)

    def open_stream(self, *, storage_key: str, chunk_size: int):
        del chunk_size
        for item in self.puts:
            if item["storage_key"] == storage_key:
                yield item["content"]
                return
        raise FileNotFoundError(storage_key)
