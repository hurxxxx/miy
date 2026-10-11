"""Candidate isolation and authority are exercised through the real API and DB."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps.models import AppDefinitionRecord, AppInstallationRecord
from miy_api.domains.independent_apps.delivery_models import AppBuildJob
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from miy_api.domains.independent_apps.workspace_maintenance import _maintain
from test_independent_apps import setup_app
from test_independent_app_delegation import grant


@pytest.fixture
def workspace(client, monkeypatch, tmp_path, request):
    profile = dict(
        id="app",
        repository_root=str(tmp_path / "repo"),
        repository="https://example.test/team/sample.git",
        worktree_root=str(tmp_path / "trees"),
        work_root=str(tmp_path / "builds"),
        state_root=str(tmp_path / "state"),
        toolchain_image="sha256:" + "a" * 64,
        ingress_image="sha256:" + "b" * 64,
        platform_origin="https://platform.test",
        origins=[
            dict(origin="https://work.test" if i == 0 else f"https://work-{i}.test", port=19500 + i)
            for i in range(getattr(request, "param", 1))
        ],
    )
    monkeypatch.setenv("MIY_ENVIRONMENT", "development")
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    monkeypatch.setenv("MIY_INDEPENDENT_APP_WORKSPACE_PROFILES", json.dumps([profile]))
    get_settings.cache_clear()
    app = list(setup_app(client))
    definition = app[2]["definition"]
    definition["source"]["directory"] = "personal-apps/sample-independent"
    update = client.put(
        "/api/v1/independent-apps/definitions",
        headers=app[1],
        json=dict(
            definition=definition,
            source_revision="a" * 40,
            expected_digest=app[2]["definition_digest"],
            expected_source_revision="a" * 40,
        ),
    )
    assert update.status_code == 200, update.text
    app[2] = update.json()
    _, headers, path = grant(client, app, ["read", "sync", "build", "deploy", "workspace"])
    path += "/workspaces/" + str(uuid4())
    body = dict(profile_id="app", definition=definition, source_revision="b" * 40)
    response = client.post(path + "/prepare", headers=headers, json=body)
    assert response.status_code == 200, response.text
    yield app, headers, path, body, response.json()
    get_settings.cache_clear()


def test_candidate_and_build_are_isolated_from_canonical_installation(client, workspace):
    app, headers, path, body, state = workspace
    assert state["installation"]["id"] != app[3]["id"]
    assert state["portal_url"].endswith("/installed/" + state["installation"]["id"])
    assert client.post(path + "/prepare", headers=headers, json=body).json()["id"] == state["id"]
    definition = json.loads(json.dumps(body["definition"]))
    definition["display"]["name"] = "Candidate only"
    updated = client.post(
        path + "/sync",
        headers=headers,
        json=dict(
            definition=definition, source_revision="c" * 40, expected_version=state["version"]
        ),
    )
    assert updated.status_code == 200, updated.text
    candidate = updated.json()
    request = dict(
        request_id=str(uuid4()),
        source_revision="c" * 40,
        definition_digest=candidate["definition_digest"],
    )
    build = client.post(path + "/builds", headers=headers, json=request)
    assert build.status_code == 202, build.text
    with get_session_factory()() as db:
        assert (
            db.get(AppDefinitionRecord, "sample-independent").manifest["display"]["name"]
            == "Test application"
        )
        job = db.get(AppBuildJob, request["request_id"])
        assert job.installation_id == state["installation"]["id"]
        assert db.get(AppInstallationRecord, app[3]["id"]).release_id is None
    conflict = client.post(
        path + "/sync",
        headers=headers,
        json=dict(
            definition=definition, source_revision="d" * 40, expected_version=state["version"]
        ),
    )
    assert conflict.status_code == 409
    assert (
        client.post(
            path + "/cleanup", headers=headers, json={"expected_version": candidate["version"]}
        ).status_code
        == 409
    )
    stopped = client.post(
        path + "/stop", headers=headers, json={"expected_version": candidate["version"]}
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "stopping"
    with get_session_factory()() as db:
        assert db.get(AppBuildJob, request["request_id"]).state == "failed"
        assert not db.get(AppInstallationRecord, state["installation"]["id"]).enabled
    calls = []

    class Runtime:
        def clean_workspace_files(self, specs, *, installation_id):
            pass

        def stop_workspace(self, specs, *, installation_id):
            calls.append((specs, installation_id))

    result = _maintain(get_settings(), get_session_factory(), state["id"], lambda *_: Runtime())
    assert result["state"] == "stopped"
    assert calls == [([], state["installation"]["id"])]
    assert (
        client.post(
            path + "/builds", headers=headers, json=request | {"request_id": str(uuid4())}
        ).status_code
        == 403
    )


def test_existing_grant_does_not_gain_workspace_authority_and_capacity_is_bounded(
    client, workspace
):
    app, headers, path, body, state = workspace
    _, old_headers, _ = grant(client, app)
    assert client.get(path + "/context", headers=old_headers).status_code == 403
    other = path.rsplit("/", 1)[0] + "/" + str(uuid4())
    assert client.post(other + "/prepare", headers=headers, json=body).status_code == 409
    with get_session_factory()() as db:
        assert len(list(db.scalars(select(AppWorkspaceRecord)))) == 1
    broadened = json.loads(json.dumps(body))
    broadened["definition"]["source"]["directory"] = "."
    assert client.post(other + "/prepare", headers=headers, json=broadened).status_code == 403


def test_merged_source_handoff_survives_cleanup_and_requires_observed_dev_release(
    client, workspace, monkeypatch
):
    import subprocess
    from miy_api.domains.independent_apps import workspace_maintenance, production
    from miy_api.domains.independent_apps.builds import BuildEvidence
    from miy_api.domains.independent_apps.delivery import (
        start_build_job,
        persist_verified_build,
        execute_deployment,
    )
    from test_independent_app_delivery import FakeRuntime

    app, headers, path, body, state = workspace
    profile = get_settings().independent_app_workspace_profiles[0]
    root = profile.repository_root
    root.mkdir()
    directory = root / "personal-apps/sample-independent"
    directory.mkdir(parents=True)
    (directory / "app.manifest.json").write_text(json.dumps(body["definition"]))
    (directory / "api.py").write_text("# Synthetic merged source\n")

    def git(*args):
        return (
            subprocess.check_output(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.test",
                    "-c",
                    "commit.gpgsign=false",
                    "-C",
                    str(root),
                    *args,
                ],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )

    git("init")
    git("remote", "add", "origin", profile.repository)
    git("add", ".")
    git("commit", "-m", "Synthetic merged dev source")
    revision = git("rev-parse", "HEAD")
    payload = dict(
        definition=body["definition"],
        source_revision=revision,
        expected_version=1,
        expected_digest=app[2]["definition_digest"],
        expected_source_revision="a" * 40,
    )
    # A locally existing commit alone does not establish origin/dev integration.
    assert client.post(path + "/integrate", headers=headers, json=payload).status_code == 409
    git("update-ref", "refs/remotes/origin/dev", revision)
    integrated = client.post(path + "/integrate", headers=headers, json=payload)
    assert integrated.status_code == 200, integrated.text
    state = integrated.json()
    assert not state["source_handoff_complete"]
    target = dict(
        app_id="sample-independent",
        installation_id=app[3]["id"],
        source_root=str(root.parent / "legacy-source"),
        work_root=str(root.parent / "permanent-build"),
        state_root=str(root.parent / "permanent-state"),
        toolchain_image="sha256:" + "a" * 64,
        ingress_image="sha256:" + "b" * 64,
        platform_origin="https://platform.test",
        app_origin="https://sample.test",
        loopback_port=19901,
    )
    monkeypatch.setenv("MIY_INDEPENDENT_APP_DELIVERY_TARGETS", json.dumps([target]))
    get_settings.cache_clear()
    with get_session_factory()() as db:
        installation = db.get(AppInstallationRecord, app[3]["id"])
        assert production.runtime_target(installation, db).source_root == root
        canonical = db.get(AppDefinitionRecord, "sample-independent")
        job, claimed = start_build_job(db, canonical.app_id, revision, str(uuid4()))
        assert claimed
        release = persist_verified_build(
            db,
            job,
            BuildEvidence(
                app_id=canonical.app_id,
                source_revision=revision,
                definition_digest=canonical.definition_digest,
                source_archive_sha256="c" * 64,
                artifact_digest="sha256:" + "e" * 64,
                builder_profile_digest="sha256:" + "d" * 64,
                checks={"test": 0, "build": 0},
            ),
        )
        release_id = release.id
    parent_path = path.split("/workspaces/")[0]
    deployment_id = str(uuid4())
    response = client.post(
        parent_path + "/deployments",
        headers=headers,
        json=dict(
            request_id=deployment_id,
            installation_id=app[3]["id"],
            release_id=release_id,
            expected_generation=app[3]["generation"],
            expected_release_id=None,
        ),
    )
    assert response.status_code == 202, response.text
    assert (
        client.post(
            path + "/complete", headers=headers, json={"deployment_id": deployment_id}
        ).status_code
        == 409
    )
    with get_session_factory()() as db:
        assert execute_deployment(db, deployment_id, FakeRuntime()).state == "succeeded"
    proof = client.post(path + "/complete", headers=headers, json={"deployment_id": deployment_id})
    assert proof.status_code == 200 and proof.json()["source_handoff_complete"]
    assert proof.json()["permanent_portal_url"].endswith("/installed/" + app[3]["id"])
    requested = client.post(
        path + "/cleanup", headers=headers, json={"expected_version": state["version"]}
    )
    assert requested.status_code == 200, requested.text

    # A cancelled request may store JSON null, distinct from SQL NULL. It has
    # never produced a runtime and must not make cleanup invent a RuntimeSpec.
    from miy_api.domains.independent_apps.delivery_models import AppDeploymentRequest

    with get_session_factory()() as db:
        original = db.get(AppDeploymentRequest, deployment_id)
        cancelled = AppDeploymentRequest(
            **{
                c.name: getattr(original, c.name)
                for c in AppDeploymentRequest.__table__.columns
                if c.name
                not in {
                    "id",
                    "installation_id",
                    "request_hash",
                    "state",
                    "runtime_config",
                    "observed_image_id",
                }
            }
        )
        cancelled.id, cancelled.installation_id = str(uuid4()), state["installation"]["id"]
        cancelled.request_hash, cancelled.state = "f" * 64, "failed"
        cancelled.runtime_config = None
        cancelled_id = cancelled.id
        db.add(cancelled)
        db.commit()

    class Data:
        def remove_temporary(self, **kwargs):
            assert kwargs["installation_id"] != app[3]["id"]
            kwargs["persist_receipt"]({"state": "absent"})

    class Runtime:
        def clean_workspace_files(self, specs, *, installation_id):
            pass

        def stop_workspace(self, specs, *, installation_id):
            assert installation_id == state["installation"]["id"]

    monkeypatch.setattr(workspace_maintenance, "configured_store", lambda *_: Data())
    assert (
        _maintain(get_settings(), get_session_factory(), state["id"], lambda *_: Runtime())["state"]
        == "cleaned"
    )
    with get_session_factory()() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        assert row.slot is None
        archived = db.get(AppInstallationRecord, state["installation"]["id"])
        assert archived.state == "archived" and not archived.enabled
        assert archived.origin is None and archived.archived_origin == "https://work.test"
        assert row.resources["installation_archive"] == {
            "installation_id": archived.id,
            "origin": "https://work.test",
            "generation": archived.generation,
            "profile_id": "app",
            "slot": 0,
        }
        assert db.get(AppDeploymentRequest, cancelled_id).installation_id == archived.id
        assert db.get(AppWorkspaceRecord, state["id"]).candidate_id is not None
        assert (
            production.runtime_target(db.get(AppInstallationRecord, app[3]["id"]), db).source_root
            == root
        )

    _assert_archived_slot_recycles(client, app, headers, path, body, state, cancelled_id)

    from test_app_integrations import issue
    from test_organization_integrations import _auth_headers

    key = issue(client, app[0], ["app-catalog:read"])
    response = client.get(
        "/api/v1/integrations/apps/sample-independent/installations",
        headers=_auth_headers(key["api_key"]),
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    archived = next(
        item for item in response.json()["items"] if item["id"] == state["installation"]["id"]
    )
    assert archived["origin"] == state["installation"]["origin"]
    assert archived["state"] == "archived" and not archived["enabled"]
    assert not {"archived_origin", "user_ids", "group_ids", "runtime_config"} & archived.keys()

    expanded = profile.model_dump(mode="json")
    expanded["origins"].append({"origin": "https://future-work.test", "port": 19902})
    monkeypatch.setenv("MIY_INDEPENDENT_APP_WORKSPACE_PROFILES", json.dumps([expanded]))
    get_settings.cache_clear()
    with get_session_factory()() as db:
        assert (
            production.runtime_target(db.get(AppInstallationRecord, app[3]["id"]), db).source_root
            == root
        )


def _assert_archived_slot_recycles(client, app, headers, path, body, state, historical_request_id):
    from alembic import command

    from miy_api.core.db import _alembic_config
    from miy_api.domains.independent_apps.delivery_models import AppDeploymentRequest

    # Replaying the original operation returns history without reclaiming a slot.
    archived_snapshot = client.post(path + "/prepare", headers=headers, json=body)
    assert archived_snapshot.status_code == 200, archived_snapshot.text
    archived = archived_snapshot.json()["installation"]
    assert archived_snapshot.json()["state"] == "cleaned"
    assert archived["state"] == "archived" and archived["origin"] == "https://work.test"
    for action in ("stop", "resume"):
        assert (
            client.post(
                path + "/" + action,
                headers=headers,
                json={"expected_version": archived_snapshot.json()["version"]},
            ).status_code
            == 409
        )
    assert (
        client.put(
            "/api/v1/independent-apps/sample-independent/installations/" + archived["id"],
            headers=app[1],
            json=app[4] | {"origin": "https://work.test"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/independent-apps/launch",
            headers=app[1],
            json={"installation_id": archived["id"], "code_challenge": "a" * 43},
        ).status_code
        == 404
    )
    catalog = client.get("/api/v1/independent-apps/catalog", headers=app[1])
    assert catalog.status_code == 200, catalog.text
    history = next(
        item
        for entry in catalog.json()["items"]
        for item in entry["installations"]
        if item["id"] == archived["id"]
    )
    assert history["origin"] == "https://work.test"
    assert not history["launchable"] and history["ui_entrypoint"] is None

    # A different app uses the exact origin and slot while every old FK remains.
    other_definition = json.loads(json.dumps(body["definition"]))
    other_definition["app_id"] = "other-independent"
    other_definition["source"]["directory"] = "personal-apps/other-independent"
    registered = client.put(
        "/api/v1/independent-apps/definitions",
        headers=app[1],
        json={"definition": other_definition, "source_revision": "a" * 40},
    )
    assert registered.status_code == 200, registered.text
    other_installation = client.post(
        "/api/v1/independent-apps/other-independent/installations",
        headers=app[1],
        json=app[4] | {"origin": "https://other-stable.test"},
    )
    assert other_installation.status_code == 201, other_installation.text
    other_id = other_installation.json()["id"]
    other_grant = client.post(
        f"/api/v1/independent-apps/other-independent/installations/{other_id}/delegations",
        headers=app[1],
        json={"actions": ["read", "sync", "workspace"]},
    )
    assert other_grant.status_code == 201, other_grant.text
    other_headers = {"Authorization": "Bearer " + other_grant.json()["token"]}
    other_path = (
        f"/api/v1/independent-apps/delegated/other-independent/installations/{other_id}"
        "/workspaces/" + str(uuid4())
    )
    prepared = client.post(
        other_path + "/prepare",
        headers=other_headers,
        json={"profile_id": "app", "definition": other_definition, "source_revision": "b" * 40},
    )
    assert prepared.status_code == 200, prepared.text
    replacement = prepared.json()
    assert replacement["installation"]["id"] != archived["id"]
    assert replacement["installation"]["origin"] == "https://work.test"
    assert _maintain(get_settings(), get_session_factory(), state["id"], None)["state"] == "idle"
    with get_session_factory()() as db:
        assert db.get(AppWorkspaceRecord, replacement["id"]).slot == 0
        assert db.get(AppInstallationRecord, archived["id"]).archived_origin == "https://work.test"
        assert db.get(AppDeploymentRequest, historical_request_id).installation_id == archived["id"]
        assert db.get(AppInstallationRecord, app[3]["id"]).origin == "https://sample.test"
        # Both lifecycle CHECK and the original global UNIQUE stay authoritative.
        for installation_id, updates in (
            (archived["id"], {"enabled": True}),
            (replacement["installation"]["id"], {"origin": None}),
            (app[3]["id"], {"origin": "https://work.test"}),
        ):
            with pytest.raises(IntegrityError), db.begin_nested():
                record = db.get(AppInstallationRecord, installation_id)
                for key, value in updates.items():
                    setattr(record, key, value)
                db.flush()

    # A downgrade cannot safely restore an origin already claimed by another app.
    with pytest.raises(RuntimeError, match="Archived installation history"):
        command.downgrade(_alembic_config(), "independent_workspaces_20261011")
    with get_session_factory()() as db:
        assert db.get(AppInstallationRecord, archived["id"]).state == "archived"
        assert db.get(AppWorkspaceRecord, replacement["id"]).slot == 0


@pytest.mark.parametrize("failure", ["runtime_cleanup"])
def test_incomplete_cleanup_keeps_origin_and_slot_reserved(client, workspace, failure):
    _, _, _, _, state = workspace
    with get_session_factory()() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        row.state = "cleanup_pending"
        row.resources = {"integration_deployment_id": str(uuid4())}
        installation = db.get(AppInstallationRecord, row.installation_id)
        installation.enabled, installation.state = False, "disabled"
        db.commit()

    class Runtime:
        def stop_workspace(self, specs, *, installation_id):
            assert installation_id == state["installation"]["id"]

        def clean_workspace_files(self, specs, *, installation_id):
            if failure == "runtime_cleanup":
                raise ValueError("Fixture runtime cleanup is uncertain")
            with get_session_factory()() as db:
                installation = db.get(AppInstallationRecord, installation_id)
                installation.enabled, installation.state = True, "configured"
                installation.generation += 1
                db.commit()

    with pytest.raises(ValueError, match="uncertain|identity changed"):
        _maintain(get_settings(), get_session_factory(), state["id"], lambda *_: Runtime())
    with get_session_factory()() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        installation = db.get(AppInstallationRecord, row.installation_id)
        assert row.state == "cleanup_pending" and row.slot == 0
        assert "installation_archive" not in row.resources
        assert installation.origin == "https://work.test"
        assert installation.archived_origin is None and installation.state != "archived"
