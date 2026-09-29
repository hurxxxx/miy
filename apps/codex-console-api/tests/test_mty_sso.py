import httpx

from codex_console import mty_sso

OWNER_SUBJECT = "11111111-1111-4111-8111-111111111111"


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

    monkeypatch.setattr(mty_sso.httpx, "Client", client)
    assert (
        mty_sso.exchange_code(
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

    monkeypatch.setattr(mty_sso.httpx, "Client", client)
    for _ in range(3):
        assert mty_sso.exchange_code(
            issuer="https://dev.example.test",
            code="cc1_code",
        ) is None


def test_exchange_code_rejects_redirects_and_large_responses(monkeypatch):
    real_client = httpx.Client
    responses = iter(
        (
            httpx.Response(302, headers={"location": "http://127.0.0.1/private"}),
            httpx.Response(200, content=b"x" * (mty_sso.MAX_RESPONSE_BYTES + 1)),
        )
    )

    def client(**kwargs):
        return real_client(
            transport=httpx.MockTransport(lambda request: next(responses)),
            **kwargs,
        )

    monkeypatch.setattr(mty_sso.httpx, "Client", client)
    for _ in range(2):
        assert not mty_sso.exchange_code(
            issuer="https://dev.example.test",
            code="cc1_code",
        )
