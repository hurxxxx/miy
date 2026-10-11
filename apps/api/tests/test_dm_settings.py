from __future__ import annotations

import pytest
from pydantic import ValidationError

from miy_api.core.settings import DEFAULT_CONTENT_GRANT_SIGNING_KEY, Settings

POSTGRES_DSN = "postgresql+psycopg://test:test@127.0.0.1:5432/test"


@pytest.fixture(autouse=True)
def isolated_shared_signing_setting(monkeypatch):
    monkeypatch.delenv("MIY_CONTENT_GRANT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("MIY_API_SEED_DEV_LOGIN_ACCOUNT", "0")
    monkeypatch.setenv("MIY_API_OBJECT_STORAGE_REQUIRED", "1")


@pytest.mark.parametrize(
    "environment, key",
    [
        (
            "production",
            None,
        ),
        (
            "production",
            DEFAULT_CONTENT_GRANT_SIGNING_KEY,
        ),
    ],
)
def test_shared_content_grants_reject_missing_or_default_signing_key_in_production_like_environments(
    environment, key
):
    extra = {} if key is None else {"content_grant_signing_key": key}
    with pytest.raises(ValidationError, match="MIY_CONTENT_GRANT_SIGNING_KEY"):
        Settings(_env_file=None, postgres_dsn=POSTGRES_DSN, environment=environment, **extra)
