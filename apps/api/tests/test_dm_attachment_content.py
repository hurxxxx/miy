from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from miy_api.domains.content_access.grants import (
    ContentGrantIssuer,
    InvalidContentGrant,
    decode_content_grant,
)
from miy_api.domains.dm import attachment_content, attachment_links
from miy_api.domains.dm.models import DmMessageAttachment


@pytest.fixture
def authorized_source(monkeypatch):
    attachment = DmMessageAttachment(
        id="attachment-1",
        conversation_id="conversation-1",
        message_id="message-1",
        uploader_id="user-1",
        filename="report.txt",
        content_type="image/png",
        size_bytes=12,
        storage_key="dm/private/report.txt",
        created_at=datetime(2026, 9, 8),
    )
    url = attachment_links.build_dm_attachment_content_url(
        attachment,
        issuer=ContentGrantIssuer(user_id="user-1", session_id="session-1"),
        disposition="inline",
    )
    claims = decode_content_grant(parse_qs(urlparse(url).fragment)["grant"][0])
    monkeypatch.setattr(
        attachment_content.attachment_records,
        "require_attachment_access",
        lambda _db, **kwargs: attachment,
    )
    return SimpleNamespace(get=lambda _model, _id: SimpleNamespace(id="user-1")), attachment, claims


def test_dm_content_grant_stream_preserves_storage_cleanup(monkeypatch, authorized_source):
    db, attachment, claims = authorized_source
    stored = SimpleNamespace(closed=False, released=False)

    def stream(*, storage_key, chunk_size):
        assert storage_key == attachment.storage_key
        assert chunk_size == attachment_content.DM_ATTACHMENT_PROXY_CHUNK_SIZE

        class Object:
            def stream(self, chunk_size):
                yield b"first"
                yield b"second"

            def close(self):
                stored.closed = True

            def release_conn(self):
                stored.released = True

        return attachment_content.attachment_storage.stream_attachment_storage_object(
            Object(), chunk_size=chunk_size
        )

    monkeypatch.setattr(
        attachment_content.attachment_storage,
        "dm_attachment_storage",
        lambda: SimpleNamespace(open_stream=stream),
    )
    content = attachment_content.open_dm_attachment_content_grant(db, claims=claims)
    assert content.media_type == "image/png"
    assert list(content.body) == [b"first", b"second"]
    assert stored.closed and stored.released


@pytest.mark.parametrize(
    "binding",
    ["source_id", "object_identity"],
)
def test_dm_content_grant_rejects_wrong_binding_before_storage(
    monkeypatch, authorized_source, binding
):
    db, _attachment, claims = authorized_source
    monkeypatch.setattr(
        attachment_content.attachment_storage,
        "dm_attachment_storage",
        lambda: pytest.fail("invalid grants must not open storage"),
    )
    with pytest.raises(InvalidContentGrant, match="binding"):
        attachment_content.open_dm_attachment_content_grant(
            db, claims=replace(claims, **{binding: "wrong-binding"})
        )
