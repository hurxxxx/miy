from __future__ import annotations

import pytest

from miy_api.domains.ai import model_discovery
from miy_api.domains.ai.model_discovery import (
    ProviderModelDiscoveryError,
    discover_provider_models,
)


class _FakeModels:
    def __init__(self, items: list[object], *, error: Exception | None = None) -> None:
        self.items = items
        self.error = error
        self.calls: list[dict[str, object]] = []

    def list(self, **kwargs: object) -> list[object]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.items


class _FakeClient:
    def __init__(self, items: list[object], *, error: Exception | None = None) -> None:
        self.models = _FakeModels(items, error=error)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_provider_errors_are_replaced_with_a_safe_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_message = "request failed with Authorization: Bearer top-secret"
    client = _FakeClient([], error=RuntimeError(raw_message))
    monkeypatch.setattr(
        model_discovery,
        "_new_openai_client",
        lambda **_kwargs: client,
    )

    with pytest.raises(ProviderModelDiscoveryError) as caught:
        discover_provider_models(
            "openai",
            "https://api.openai.test/v1",
            "top-secret",
            10,
        )

    assert caught.value.code == "provider_unavailable"
    assert raw_message not in str(caught.value)
    assert "top-secret" not in repr(caught.value)
    assert client.closed is True


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_discovery_does_not_send_credentials_to_redirect_targets(provider):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    paths = []

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            if self.path == "/redirected":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data": [], "models": []}')
            else:
                self.send_response(307)
                self.send_header("Location", "/redirected")
                self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(ProviderModelDiscoveryError):
            discover_provider_models(
                provider, f"http://127.0.0.1:{server.server_port}", "synthetic-key", 2
            )
        assert len(paths) == 1
        assert "/redirected" not in paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
