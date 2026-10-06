import json
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import certifi
import httpx
import pytest

from codex_console import miy_sso

OWNER_SUBJECT = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def https_issuer(tmp_path):
    certificate, key = tmp_path / "issuer.crt", tmp_path / "issuer.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-days",
            "1",
            "-subj",
            "/CN=Console SSO test",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,digitalSignature",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == miy_sso.EXCHANGE_PATH
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert payload == {"code": "cc1_tls_check"}
            body = json.dumps({"authenticated": True, "subject": OWNER_SUBJECT}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}", certificate
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_exchange_uses_trusted_ca_without_environment_proxy(https_issuer, monkeypatch):
    issuer, certificate = https_issuer
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    assert miy_sso.exchange_code(issuer=issuer, code="cc1_tls_check") == OWNER_SUBJECT


def test_exchange_rejects_untrusted_https_certificate(https_issuer, monkeypatch):
    issuer, _certificate = https_issuer
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    assert miy_sso.exchange_code(issuer=issuer, code="cc1_tls_check") is None


def test_exchange_code_accepts_only_exact_bounded_success(monkeypatch):
    real_client = httpx.Client

    def client(**kwargs):
        return real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"authenticated": True, "subject": OWNER_SUBJECT},
                )
            ),
            **kwargs,
        )

    monkeypatch.setattr(miy_sso.httpx, "Client", client)
    assert (
        miy_sso.exchange_code(
            issuer="https://dev.example.test",
            code="cc1_code",
        )
        == OWNER_SUBJECT
    )


def test_exchange_code_rejects_invalid_or_extra_identity_data(monkeypatch):
    real_client = httpx.Client
    responses = iter(
        (
            httpx.Response(200, json={"authenticated": True}),
            httpx.Response(
                200,
                json={"authenticated": True, "subject": OWNER_SUBJECT, "role": "admin"},
            ),
            httpx.Response(200, json={"authenticated": True, "subject": "not-a-uuid"}),
        )
    )

    def client(**kwargs):
        return real_client(
            transport=httpx.MockTransport(lambda request: next(responses)),
            **kwargs,
        )

    monkeypatch.setattr(miy_sso.httpx, "Client", client)
    for _ in range(3):
        assert (
            miy_sso.exchange_code(
                issuer="https://dev.example.test",
                code="cc1_code",
            )
            is None
        )


def test_exchange_code_rejects_redirects_and_large_responses(monkeypatch):
    real_client = httpx.Client
    responses = iter(
        (
            httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
            httpx.Response(200, content=b"x" * (miy_sso.MAX_RESPONSE_BYTES + 1)),
        )
    )

    def client(**kwargs):
        return real_client(
            transport=httpx.MockTransport(lambda request: next(responses)),
            **kwargs,
        )

    monkeypatch.setattr(miy_sso.httpx, "Client", client)
    for _ in range(2):
        assert not miy_sso.exchange_code(
            issuer="https://dev.example.test",
            code="cc1_code",
        )
