from __future__ import annotations

from fastapi.testclient import TestClient

from dev_accounts import auth_headers, dev_login


def _admin_headers(client: TestClient) -> dict[str, str]:
    return auth_headers(dev_login(client)["token"])
