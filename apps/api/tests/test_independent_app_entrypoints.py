from miy_api.core.db import get_session_factory
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import AppReleaseRecord
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    delivery_app as delivery_app,
    enqueue,
    execute,
)


BASE = "/api/v1/independent-apps"


def catalog_installation(client, app, installation_id=None):
    response = client.get(BASE + "/catalog", headers=app[1])
    assert response.status_code == 200
    data = response.json()
    item = next(
        item
        for item in data["items"]
        if item["definition"]["definition"]["app_id"] == "sample-independent"
    )
    installation = next(
        entry for entry in item["installations"] if entry["id"] == (installation_id or app[3]["id"])
    )
    return installation, data["catalog_revision"], item["definition"]


def register_ui(client, app, previous, revision, ui):
    definition = previous["definition"] | {
        "entrypoints": previous["definition"]["entrypoints"] | {"ui": ui}
    }
    response = client.put(
        BASE + "/definitions",
        headers=app[1],
        json={
            "definition": definition,
            "source_revision": revision,
            "expected_digest": previous["definition_digest"],
            "expected_source_revision": previous["source_revision"],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_installed_route_follows_verified_release_through_source_changes_and_rollback(
    client, delivery_app
):
    app, runtime = delivery_app, FakeRuntime()
    initial, _, _ = catalog_installation(client, app)
    assert (
        initial["release_id"] is None and initial["ui_entrypoint"] == "/" and initial["launchable"]
    )
    old = register_ui(client, app, app[2], "b" * 40, "/old")
    old_release = build_release(old, revision="b" * 40)
    first, _ = enqueue(client, app, old_release)
    assert execute(first, runtime).state == "succeeded"
    installed, before, _ = catalog_installation(client, app)
    assert installed["ui_entrypoint"] == "/old"
    new = register_ui(client, app, old, "c" * 40, "/new")
    unchanged, after, current = catalog_installation(client, app)
    assert after != before and current["definition"]["entrypoints"]["ui"] == "/new"
    assert unchanged["ui_entrypoint"] == "/old" and unchanged["release_id"] == old_release
    new_release = build_release(new, "b", revision="c" * 40)
    second, _ = enqueue(client, app, new_release, installation=current_installation(app[3]["id"]))
    assert execute(second, runtime).state == "succeeded"
    installed_new, _, _ = catalog_installation(client, app)
    assert installed_new["ui_entrypoint"] == "/new"
    rollback, _ = enqueue(
        client, app, old_release, action="rollback", installation=current_installation(app[3]["id"])
    )
    assert execute(rollback, runtime).state == "succeeded"
    reverted, _, current = catalog_installation(client, app)
    assert reverted["ui_entrypoint"] == "/old" and reverted["launchable"]
    assert current["definition"]["entrypoints"]["ui"] == "/new"
    with get_session_factory()() as db:
        release = db.get(AppReleaseRecord, old_release)
        db.get(AppBuildVerification, release.verification_id).revoked_at = utcnow_naive()
        db.commit()
    revoked, _, _ = catalog_installation(client, app)
    assert revoked["ui_entrypoint"] is None and not revoked["launchable"]


def test_unbuilt_production_does_not_inherit_development_definition_route(client, delivery_app):
    app = delivery_app
    response = client.post(
        BASE + "/sample-independent/installations",
        headers=app[1],
        json={
            **app[4],
            "environment": "production",
            "enabled": False,
            "origin": "https://production.example.test",
        },
    )
    assert response.status_code == 201
    item, _, _ = catalog_installation(client, app, response.json()["id"])
    assert item["ui_entrypoint"] is None and item["release_id"] is None and not item["launchable"]
