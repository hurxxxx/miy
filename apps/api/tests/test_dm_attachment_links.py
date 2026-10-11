from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from miy_api.core.model_registry import import_all_models
from miy_api.domains.content_access import grants
from miy_api.domains.dm.models import DmMessageAttachment


@pytest.fixture(scope="module", autouse=True)
def load_attachment_model_registry():
    import_all_models()


@pytest.fixture(autouse=True)
def shared_content_signing(monkeypatch):
    settings = SimpleNamespace(
        api_prefix="/api/v1", content_grant_signing_key="unit-test-shared-signing-key"
    )
    monkeypatch.setattr(grants, "get_settings", lambda: settings)
    return settings


def _attachment(*, content_type="image/png") -> DmMessageAttachment:
    return DmMessageAttachment(
        id="attachment-1",
        conversation_id="conversation-1",
        message_id="message-1",
        uploader_id="user-1",
        filename="file.png",
        content_type=content_type,
        size_bytes=12,
        storage_key="dm/conversation-1/attachment-1/file.png",
        created_at=datetime(2026, 9, 8),
    )


def _token(url):
    parsed = urlparse(url)
    assert parsed.path == "/api/v1/content" and not parsed.query
    return parse_qs(parsed.fragment)["grant"][0]
