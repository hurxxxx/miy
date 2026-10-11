from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from miy_api.domains.realtime import docs_pages_subscription as subscriptions


class _FakeDb:
    closed = False

    def close(self):
        self.closed = True


def _auth(monkeypatch, user_id="user-1"):
    monkeypatch.setattr(
        subscriptions,
        "resolve_auth_context_from_token",
        lambda _db, _token, update_last_seen: SimpleNamespace(user=SimpleNamespace(id=user_id)),
    )


def test_docs_pages_subscription_rejects_mismatched_connection_user(monkeypatch):
    _auth(monkeypatch, "another-user")
    monkeypatch.setattr(
        subscriptions,
        "_ensure_docs_app_access",
        lambda *_args: pytest.fail("mismatched principal reached admission"),
    )
    with pytest.raises(HTTPException) as denied:
        subscriptions.resolve_docs_pages_subscription_in_session(
            _FakeDb(), item_id="doc-1", share_token=None, token="token", user_id="user-1"
        )
    assert denied.value.status_code == 401
