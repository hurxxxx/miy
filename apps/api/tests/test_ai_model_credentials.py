from __future__ import annotations

import pytest

from miy_api.core.settings import get_settings
from miy_api.domains.ai.model_credentials import (
    AiModelCredentialError,
    encrypt_api_key,
)


def test_ai_model_api_key_requires_encryption_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIY_AI_MODEL_CREDENTIAL_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(AiModelCredentialError, match="not configured"):
            encrypt_api_key("secret-value")
    finally:
        get_settings.cache_clear()
