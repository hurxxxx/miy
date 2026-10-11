"""Same-host promotion keeps development proof and production observation separate."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from miy_api.core.db import get_session_factory
from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import UserSystemRole
from miy_api.domains.independent_apps import production
from miy_api.domains.independent_apps.delivery import reconcile_deployment
from miy_api.domains.independent_apps.delivery_models import AppBuildVerification
from miy_api.domains.independent_apps.models import AppInstallationRecord
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    delivery_app as delivery_app,
    enqueue,
    execute,
)


@pytest.fixture
def promotion_app(client, delivery_app, tmp_path, monkeypatch):
    installation = client.post(
        "/api/v1/independent-apps/sample-independent/installations",
        headers=delivery_app[1],
        json=delivery_app[4]
        | {
            "environment": "production",
            "origin": "https://production.sample.test",
            "enabled": False,
        },
    )
    assert installation.status_code == 201, installation.text
    installation = installation.json()
    target = IndependentDeliveryTarget(
        app_id="sample-independent",
        installation_id=installation["id"],
        environment="production",
        app_origin=installation["origin"],
        loopback_port=19431,
        source_root=tmp_path / "source",
        work_root=tmp_path / "scratch",
        state_root=tmp_path / "runtime",
        toolchain_image="sha256:" + "a" * 64,
        ingress_image="sha256:" + "b" * 64,
        platform_origin="https://platform.test",
    )
    settings = get_settings().model_copy(
        update={"environment": "production", "independent_app_delivery_targets": [target]}
    )
    monkeypatch.setattr(production, "get_settings", lambda: settings)
    return delivery_app, installation, target, settings


def observed_development(client, app, release):
    request, _ = enqueue(client, app, release, installation=current_installation(app[3]["id"]))
    assert execute(request, FakeRuntime()).state == "succeeded"


def promote(client, app, installation, release, *, action="deploy", status=202):
    payload = {
        "request_id": str(uuid4()),
        "installation_id": installation["id"],
        "release_id": release,
        "expected_generation": installation["generation"],
        "expected_release_id": installation.get("release_id"),
        "action": action,
    }
    response = client.post(
        "/api/v1/independent-apps/sample-independent/promotions", headers=app[1], json=payload
    )
    assert response.status_code == status, response.text
    return payload, response.json()


def test_promotion_requires_observed_development_and_exact_core_binding(
    client, promotion_app, monkeypatch
):
    app, installation, _, settings = promotion_app
    release = build_release(app[2])
    promote(client, app, installation, release, status=409)
    observed_development(client, app, release)
    monkeypatch.setattr(
        production,
        "get_settings",
        lambda: settings.model_copy(update={"independent_app_delivery_targets": []}),
    )
    promote(client, app, installation, release, status=409)
    monkeypatch.setattr(production, "get_settings", lambda: settings)
    request, _ = promote(client, app, installation, release)
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/deployments",
            headers=app[1],
            json=request | {"request_id": str(uuid4())},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/promotions",
            headers=app[1],
            json=request,
        ).json()["id"]
        == request["request_id"]
    )


def test_personal_promotion_cannot_adopt_official_app_release_contract(client, promotion_app):
    app, installation, _, _ = promotion_app
    changed = client.put(
        "/api/v1/independent-apps/definitions",
        headers=app[1],
        json={
            "definition": app[2]["definition"] | {"ownership": "official"},
            "source_revision": app[2]["source_revision"],
            "expected_digest": app[2]["definition_digest"],
            "expected_source_revision": app[2]["source_revision"],
        },
    )
    assert changed.status_code == 200, changed.text
    promote(client, app, installation, str(uuid4()), status=403)


def test_first_promotion_admits_only_after_observation_and_preserves_build_environment(
    client, promotion_app
):
    app, installation, target, _ = promotion_app
    release = build_release(app[2])
    observed_development(client, app, release)
    request, _ = promote(client, app, installation, release)
    with get_session_factory()() as db:
        assert not db.get(AppInstallationRecord, installation["id"]).enabled
    runtime = FakeRuntime()
    assert execute(request, runtime).state == "succeeded"
    selected = runtime.candidates[request["request_id"]]
    assert selected.environment == "production"
    assert selected.origin == target.app_origin
    assert selected.loopback_port == target.loopback_port
    assert selected.operator_binding_digest == production.binding_digest(target)
    with get_session_factory()() as db:
        assert db.scalar(select(AppBuildVerification)).target_environment == "development"
        installed = db.get(AppInstallationRecord, installation["id"])
        assert installed.enabled and installed.state == "ready"
        assert installed.release_id == release
    item = client.get("/api/v1/independent-apps/catalog", headers=app[1]).json()["items"][0]
    assert next(row for row in item["installations"] if row["id"] == installation["id"])[
        "launchable"
    ]


def test_owner_development_https_binding_does_not_grant_production_authority(
    client, promotion_app, monkeypatch
):
    app, production_installation, target, settings = promotion_app
    development_target = target.model_copy(
        update={
            "environment": "development",
            "installation_id": UUID(app[3]["id"]),
            "app_origin": app[3]["origin"],
        }
    )
    monkeypatch.setattr(
        production,
        "get_settings",
        lambda: settings.model_copy(
            update={"independent_app_delivery_targets": [development_target]}
        ),
    )
    with get_session_factory()() as db:
        db.execute(
            delete(UserSystemRole).where(
                UserSystemRole.user_id == app[0]["user"]["id"],
                UserSystemRole.role == "platform_admin",
            )
        )
        db.commit()
    release = build_release(app[2])
    request, _ = enqueue(client, app, release)
    runtime = FakeRuntime()
    assert execute(request, runtime).state == "succeeded"
    selected = runtime.candidates[request["request_id"]]
    assert selected.environment == "development"
    assert selected.origin == development_target.app_origin
    assert selected.loopback_port == development_target.loopback_port
    promote(client, app, production_installation, release, status=403)


@pytest.mark.parametrize("change", ["admin", "operator_binding"])
def test_current_authority_changes_before_cutover_leave_first_production_disabled(
    client, promotion_app, monkeypatch, change
):
    app, installation, target, settings = promotion_app
    release = build_release(app[2])
    observed_development(client, app, release)
    request, _ = promote(client, app, installation, release)
    runtime = FakeRuntime()

    def change_authority():
        if change == "admin":
            with get_session_factory()() as db:
                db.execute(
                    delete(UserSystemRole).where(
                        UserSystemRole.user_id == app[0]["user"]["id"],
                        UserSystemRole.role == "platform_admin",
                    )
                )
                db.commit()
        else:
            changed = settings.model_copy(
                update={
                    "independent_app_delivery_targets": [
                        target.model_copy(update={"loopback_port": 19432})
                    ]
                }
            )
            monkeypatch.setattr(production, "get_settings", lambda: changed)

    runtime.prepare_hook = change_authority
    assert execute(request, runtime).state == "failed"
    assert not runtime.activations and not runtime.candidates
    with get_session_factory()() as db:
        installed = db.get(AppInstallationRecord, installation["id"])
        assert not installed.enabled and installed.release_id is None


def test_lost_promotion_response_reconciles_original_effect_without_redeployment(
    client, promotion_app
):
    app, installation, _, _ = promotion_app
    release = build_release(app[2])
    observed_development(client, app, release)
    request, _ = promote(client, app, installation, release)
    runtime = FakeRuntime()
    runtime.lose_response = True
    assert execute(request, runtime).state == "unknown"
    assert execute(request, runtime).state == "unknown"
    assert runtime.activations == [request["request_id"]]
    with get_session_factory()() as db:
        assert reconcile_deployment(db, request["request_id"], runtime).state == "succeeded"
    assert runtime.activations == [request["request_id"]]


def test_production_code_rollback_reuses_prior_artifact_and_installation_identity(
    client, promotion_app
):
    app, installation, _, _ = promotion_app
    first = build_release(app[2])
    observed_development(client, app, first)
    request, _ = promote(client, app, installation, first)
    runtime = FakeRuntime()
    assert execute(request, runtime).state == "succeeded"
    updated = client.put(
        "/api/v1/independent-apps/definitions",
        headers=app[1],
        json={
            "definition": app[2]["definition"],
            "source_revision": "b" * 40,
            "expected_digest": app[2]["definition_digest"],
            "expected_source_revision": app[2]["source_revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    second = build_release(updated.json(), digit="b", revision="b" * 40)
    observed_development(client, app, second)
    request, _ = promote(client, app, current_installation(installation["id"]), second)
    assert execute(request, runtime).state == "succeeded"
    rollback, _ = promote(
        client, app, current_installation(installation["id"]), first, action="rollback"
    )
    assert execute(rollback, runtime).state == "succeeded"
    selected = runtime.candidates[rollback["request_id"]]
    assert selected.installation_id == installation["id"]
    assert selected.environment == "production" and selected.image_id == "sha256:" + "a" * 64
    with get_session_factory()() as db:
        assert db.get(AppInstallationRecord, installation["id"]).release_id == first
