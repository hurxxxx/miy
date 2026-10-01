from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from miy_api.domains.integrations import platform_api_keys as keys


@pytest.fixture
def configured_key(monkeypatch):
    monkeypatch.setattr(
        keys,
        "get_settings",
        lambda: SimpleNamespace(platform_api_key_encryption_key=SecretStr("test-only-brand-root")),
    )


def test_pre_rebrand_ciphertext_remains_decryptable(configured_key):
    # Frozen ciphertext produced by the previous release, using a test-only root.
    ciphertext = (
        "gAAAAABqvemb7-MWBy42gFYBHgqaKZwJ1oE4Q_cyzrv6Dy-OLBYPc3SIP7bDV5gigKmcA_27PipMyty0jYwlrWYWnd"
        "1HmW3BuhymbZkDQWGNjxXGa5Aj0BzMQ8yswlV5Jaof0WMFPL_GX0GbFDxzTg0fszYaOP9YkA=="
    )
    assert keys.decrypt_platform_api_key(ciphertext).get_secret_value() == "mty_pk_" + "A" * 43


@pytest.mark.parametrize("prefix", ["miy_pk_", "mty_pk_"])
def test_current_and_existing_api_key_tokens_roundtrip(configured_key, prefix):
    token = prefix + "A" * 43
    assert (
        keys.decrypt_platform_api_key(keys.encrypt_platform_api_key(token)).get_secret_value()
        == token
    )


@pytest.mark.parametrize("token", ["mty_pk_short", "miy_pk_short", "other_pk_" + "A" * 43])
def test_renaming_does_not_accept_invalid_tokens(configured_key, token):
    with pytest.raises(keys.PlatformApiKeyServiceError, match="platform_api_key.invalid"):
        keys.encrypt_platform_api_key(token)
