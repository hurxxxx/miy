from fastapi.testclient import TestClient

from dev_accounts import create_company_user_session


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session(
    client: TestClient,
    *,
    login_id: str,
    email: str,
) -> dict:
    return create_company_user_session(
        client,
        login_id=login_id,
        email=email,
        full_name=login_id.replace("-", " ").title(),
    )
