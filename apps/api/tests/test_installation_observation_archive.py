"""Archived installations keep display metadata without reclaiming live origins."""

from uuid import uuid4

from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps import service, workspace_maintenance
from miy_api.domains.independent_apps.models import AppInstallationRecord
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from miy_api.domains.integrations.app_router import InstallationObservationResponse
from test_app_integrations import issue
from test_independent_app_workspaces import workspace as workspace
from test_organization_integrations import _auth_headers


def test_actual_cleaned_workspace_is_observable_without_reopening_origin(client, workspace):
    app, headers, path, _, state = workspace
    installation_id = state["installation"]["id"]
    original_origin = state["installation"]["origin"]
    factory = get_session_factory()
    with factory() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        row.resources = {**row.resources, "integration_deployment_id": str(uuid4())}
        db.commit()
    closing = client.post(
        path + "/cleanup", headers=headers, json={"expected_version": state["version"]}
    )
    assert closing.status_code == 200, closing.text

    class Runtime:
        def stop_workspace(self, specs, *, installation_id):
            assert specs == [] and installation_id == state["installation"]["id"]

        def clean_workspace_files(self, specs, *, installation_id):
            assert specs == [] and installation_id == state["installation"]["id"]

    assert (
        workspace_maintenance._maintain(get_settings(), factory, state["id"], lambda *_: Runtime())[
            "state"
        ]
        == "cleaned"
    )
    with factory() as db:
        installation = db.get(AppInstallationRecord, installation_id)
        assert installation.origin is None
        assert installation.archived_origin == original_origin
        assert installation.state == "archived" and not installation.enabled
        before = {
            column.name: getattr(installation, column.name)
            for column in AppInstallationRecord.__table__.columns
        }
        retained_ids = list(db.scalars(select(AppInstallationRecord.id)))

    key = issue(client, app[0], ["app-catalog:read"])
    response = client.get(
        f"/api/v1/integrations/apps/{state['app_id']}/installations",
        headers=_auth_headers(key["api_key"]),
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    item = next(item for item in response.json()["items"] if item["id"] == installation_id)
    assert InstallationObservationResponse.model_validate(item).origin == original_origin
    assert item["state"] == "archived" and not item["enabled"]
    assert item["generation"] == before["generation"]
    for private in ("archived_origin", "user_ids", "group_ids", "runtime_config"):
        assert private not in item

    catalog = client.get("/api/v1/independent-apps/catalog", headers=app[1])
    assert catalog.status_code == 200, catalog.text
    entry = next(
        entry
        for entry in catalog.json()["items"]
        if entry["definition"]["definition"]["app_id"] == state["app_id"]
    )
    archived = next(item for item in entry["installations"] if item["id"] == installation_id)
    assert archived["origin"] == original_origin
    assert not archived["launchable"] and archived["ui_entrypoint"] is None
    assert (
        client.post(
            "/api/v1/independent-apps/launch",
            headers=app[1],
            json={"installation_id": installation_id, "code_challenge": "a" * 43},
        ).status_code
        == 404
    )
    with factory() as db:
        installation = db.get(AppInstallationRecord, installation_id)
        assert service.installation_out(installation).origin == original_origin
        assert before == {
            column.name: getattr(installation, column.name)
            for column in AppInstallationRecord.__table__.columns
        }
        assert set(retained_ids) == set(db.scalars(select(AppInstallationRecord.id)))
        row = db.get(AppWorkspaceRecord, state["id"])
        assert row.state == "cleaned" and row.slot is None
        assert row.resources["installation_archive"]["origin"] == original_origin
