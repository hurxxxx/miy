from dev_accounts import create_company_user_session
from fastapi.testclient import TestClient

from miy_api.core.db import get_session_factory
from miy_api.domains.auth.app_access import can_use_app
from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant
from miy_api.domains.auth.models import CompanyAppControl


def test_app_admission_requires_company_master_and_selected_user(client: TestClient) -> None:
    member = create_company_user_session(
        client,
        login_id="admission-member",
        email="admission@example.test",
        full_name="Admission Member",
    )
    with get_session_factory()() as db:
        policy = db.get(AppAccessPolicy, "docs")
        policy.audience = "selected"
        db.flush()
        assert not can_use_app(db, user_id=member["user"]["id"], app_id="docs")
        db.add(AppUserGrant(app_id="docs", user_id=member["user"]["id"]))
        db.flush()
        assert can_use_app(db, user_id=member["user"]["id"], app_id="docs")
        db.get(CompanyAppControl, "docs").enabled = False
        db.flush()
        assert not can_use_app(db, user_id=member["user"]["id"], app_id="docs")
