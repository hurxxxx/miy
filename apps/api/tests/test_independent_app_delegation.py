from uuid import uuid4
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.delivery import (
    execute_deployment,
)
from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeliveryDelegation
from miy_api.domains.independent_apps.models import AppReleaseRecord
from test_independent_app_delivery import FakeRuntime, build_release, current_installation
from test_independent_apps import setup_app

BASE = "/api/v1/independent-apps"


@pytest.fixture
def delegated(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    app = setup_app(client)
    yield app
    get_settings.cache_clear()


def paths(app):
    suffix = f"sample-independent/installations/{app[3]['id']}"
    return BASE + "/" + suffix + "/delegations", BASE + "/delegated/" + suffix


def grant(client, app, actions=None):
    owner, delegated = paths(app)
    response = client.post(
        owner,
        headers=app[1],
        json={"actions": actions or ["read", "sync", "build", "deploy", "rollback"]},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return data, {"Authorization": "Bearer " + data["token"]}, delegated


def test_explicit_actions_and_sync_preserve_authority_policy_and_source_cas(client, delegated):
    _, limited, path = grant(client, delegated, ["read"])
    payload = {
        "request_id": str(uuid4()),
        "source_revision": "a" * 40,
        "definition_digest": delegated[2]["definition_digest"],
    }
    assert client.post(path + "/builds", headers=limited, json=payload).status_code == 403
    _, headers, _ = grant(client, delegated)
    definition = delegated[2]["definition"]
    update = {
        "definition": definition | {"display": {"name": "Updated label"}},
        "source_revision": "b" * 40,
        "expected_digest": delegated[2]["definition_digest"],
        "expected_source_revision": "a" * 40,
    }
    for mutation in (
        {"ownership": "official"},
        {"source": {"repository": "https://other.test/app.git"}},
        {"runtime_profile": "web-api-postgres-v1"},
        {"requested_permissions": []},
        {"app_id": "another-app"},
    ):
        assert (
            client.post(
                path + "/sync", headers=headers, json=update | {"definition": definition | mutation}
            ).status_code
            == 403
        )
    response = client.post(path + "/sync", headers=headers, json=update)
    assert response.status_code == 200, response.text
    assert client.post(path + "/sync", headers=headers, json=update).status_code == 409
    assert client.get(path + "/context", headers=headers).json()["source_revision"] == "b" * 40


def test_core_consumer_rechecks_revocation_before_publishing_build_evidence(
    client, delegated, monkeypatch, tmp_path
):
    from miy_api.domains.independent_apps import builds

    data, headers, path = grant(client, delegated)
    build_id = str(uuid4())
    payload = {
        "request_id": build_id,
        "source_revision": "a" * 40,
        "definition_digest": delegated[2]["definition_digest"],
    }
    assert client.post(path + "/builds", headers=headers, json=payload).status_code == 202

    def completed_build(**kwargs):
        assert kwargs["revision"] == "a" * 40 and kwargs["build_id"] == build_id
        with get_session_factory()() as db:
            db.get(AppDeliveryDelegation, data["id"]).revoked_at = utcnow_naive()
            db.commit()
        return builds.BuildEvidence(
            app_id="sample-independent",
            source_revision="a" * 40,
            definition_digest=delegated[2]["definition_digest"],
            source_archive_sha256="b" * 64,
            artifact_digest="sha256:" + "c" * 64,
            builder_profile_digest="sha256:" + "d" * 64,
            checks={"test": 0, "build": 0},
        )

    monkeypatch.setattr(builds, "build_app", completed_build)
    root = Path(__file__).resolve().parents[3]
    loader = importlib.util.spec_from_file_location(
        "delegation_cli", root / "scripts/independent-app-delivery.py"
    )
    cli = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(cli)
    monkeypatch.chdir(root)
    result = cli.run(
        cli.parser().parse_args(
            [
                "build-request",
                "--app-id",
                "sample-independent",
                "--installation-id",
                delegated[3]["id"],
                "--build-id",
                build_id,
                "--source",
                str(tmp_path),
                "--work-root",
                str(tmp_path),
                "--toolchain-image",
                "sha256:" + "e" * 64,
            ]
        )
    )
    assert result["state"] == "failed" and result["failure_code"] == "authority_changed"
    assert result["release_id"] is None
    with get_session_factory()() as db:
        assert db.get(AppBuildJob, build_id).active_slot is None
        assert db.scalar(select(AppReleaseRecord)) is None


def test_delegation_survives_generation_cutover_but_revoke_blocks_next_activation(
    client, delegated
):
    data, headers, path = grant(client, delegated)
    release = build_release(delegated[2])
    runtime = FakeRuntime()

    def enqueue():
        current = current_installation(delegated[3]["id"])
        payload = {
            "request_id": str(uuid4()),
            "installation_id": current["id"],
            "release_id": release,
            "expected_generation": current["generation"],
            "expected_release_id": current["release_id"],
        }
        response = client.post(path + "/deployments", headers=headers, json=payload)
        assert response.status_code == 202, response.text
        return payload

    first = enqueue()
    with get_session_factory()() as db:
        assert execute_deployment(db, first["request_id"], runtime).state == "succeeded"
    context = client.get(path + "/context", headers=headers)
    assert context.status_code == 200
    assert context.json()["installation"]["generation"] > first["expected_generation"]
    assert context.json()["releases"][0]["rollback_allowed"]
    assert (
        client.post(
            path + "/deployments", headers=headers, json=first | {"request_id": str(uuid4())}
        ).status_code
        == 409
    )
    second = enqueue()

    def revoke():
        with get_session_factory()() as db:
            db.get(AppDeliveryDelegation, data["id"]).revoked_at = utcnow_naive()
            db.commit()

    runtime.prepare_hook = revoke
    with get_session_factory()() as db:
        assert execute_deployment(db, second["request_id"], runtime).state == "failed"
    assert runtime.activations == [first["request_id"]]
