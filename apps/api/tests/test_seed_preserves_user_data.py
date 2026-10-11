"""Company bootstrap is idempotent and preserves app policies and business data."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_dev_accounts() -> None:
    from dev_accounts import configure_company_app_access

    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.access import ensure_dev_login_seed_data

    with get_session_factory()() as db:
        ensure_dev_login_seed_data(db)
        configure_company_app_access(db)


def test_seed_preserves_existing_master_and_audience_policy(client: TestClient) -> None:
    from miy_api.core.db import get_session_factory
    from miy_api.domains.auth.access import ensure_dev_login_seed_data, ensure_seed_data
    from miy_api.domains.auth.app_access_models import AppAccessPolicy
    from miy_api.domains.auth.models import CompanyAppControl

    _seed_dev_accounts()
    with get_session_factory()() as db:
        db.get(CompanyAppControl, "docs").enabled = False
        db.get(AppAccessPolicy, "pms").audience = "selected"
        db.commit()
        ensure_seed_data(db)
        ensure_dev_login_seed_data(db)
        assert db.get(CompanyAppControl, "docs").enabled is False
        assert db.get(AppAccessPolicy, "pms").audience == "selected"
