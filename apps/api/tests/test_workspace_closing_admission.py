"""Native closing fences protect cleanup across receipt commits and owner races."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
from threading import Event, get_ident
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import text

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps import delegation, service, workspace_maintenance, workspaces
from miy_api.domains.independent_apps.contracts import InstallationInput
from miy_api.domains.independent_apps.delivery import RuntimeSpec
from miy_api.domains.independent_apps.delivery_models import AppDeploymentRequest
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord
from miy_api.domains.independent_apps.workspace_contracts import WorkspaceTransition
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from test_independent_app_bootstrap import context
from test_independent_app_workspaces import workspace as workspace

BASE = "/api/v1/independent-apps"


def enable_input(app, state):
    return app[4] | {"origin": state["installation"]["origin"], "enabled": True}


def allow_cleanup(state):
    with get_session_factory()() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        row.resources = {**row.resources, "integration_deployment_id": str(uuid4())}
        db.commit()


def token(client, workspace):
    app, _, _, _, state = workspace
    verifier = "v" * 43
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    launched = client.post(
        BASE + "/launch",
        headers=app[1],
        json={"installation_id": state["installation"]["id"], "code_challenge": challenge},
    )
    assert launched.status_code == 200, launched.text
    exchanged = client.post(
        BASE + "/exchange",
        headers={"Origin": state["installation"]["origin"]},
        json={
            "installation_id": state["installation"]["id"],
            "code": launched.json()["code"],
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return {"Authorization": "Bearer " + exchanged.json()["token"]}


def test_native_workspace_closing_fences_queued_and_existing_admission(
    client, workspace, monkeypatch
):
    app, headers, path, _, state = workspace
    from test_workspace_job_cancellation import _queued_requests

    queued = _queued_requests(client, workspace)
    bearer = token(client, workspace)
    factory = get_session_factory()
    params = {
        "installation_id": state["installation"]["id"],
        "audience": state["installation"]["origin"],
    }
    assert client.get(BASE + "/session", headers=bearer, params=params).status_code == 200
    # A synthetic historical PostgreSQL runtime receipt selects the actual data
    # cleanup branch. The app runtime and data deletion below are bounded adapters.
    with factory() as db:
        actor = context(db, app[0])
        release_id, historical_request_id = str(uuid4()), str(uuid4())
        db.add(
            AppReleaseRecord(
                id=release_id,
                app_id=state["app_id"],
                definition_snapshot=state["definition"]
                | {"runtime_profile": "web-api-postgres-v1"},
                definition_digest=state["definition_digest"],
                source_revision=state["source_revision"],
                artifact="sha256:" + "a" * 64,
            )
        )
        db.flush()
        db.add(
            AppDeploymentRequest(
                id=historical_request_id,
                actor_user_id=actor.user.id,
                source_session_id=actor.session.id,
                installation_id=state["installation"]["id"],
                release_id=release_id,
                action="deploy",
                request_hash="a" * 64,
                expected_generation=state["installation"]["generation"],
                state="succeeded",
                runtime_config=asdict(
                    RuntimeSpec(
                        historical_request_id,
                        state["installation"]["id"],
                        state["app_id"],
                        "sha256:" + "a" * 64,
                        state["installation"]["origin"],
                        "/healthz",
                        "development",
                        "web-api-postgres-v1",
                    )
                ),
            )
        )
        db.commit()
    allow_cleanup(state)
    factory = get_session_factory()
    cached, configure_now, closing_locked, release_closing = (Event() for _ in range(4))
    configuration_pid, closing_thread = [], []
    original_commit = service._commit

    def commit(db):
        if closing_thread and get_ident() == closing_thread[0]:
            db.flush()
            closing_locked.set()
            assert release_closing.wait(5)
        original_commit(db)

    monkeypatch.setattr(service, "_commit", commit)

    def configure():
        with factory() as db:
            old_workspace = db.get(AppWorkspaceRecord, state["id"])
            db.get(AppInstallationRecord, state["installation"]["id"])
            actor = context(db, app[0])
            configuration_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            cached.set()
            assert configure_now.wait(5)
            with pytest.raises(HTTPException) as denied:
                service.configure_installation(
                    db,
                    state["app_id"],
                    InstallationInput.model_validate(enable_input(app, state)),
                    actor,
                    platform_origin="https://platform.test",
                    installation_id=state["installation"]["id"],
                )
            assert old_workspace.state == "ready"
            return denied.value.status_code

    def close():
        closing_thread.append(get_ident())
        with factory() as db:
            grant, actor = delegation.resolve(
                db, headers["Authorization"], "workspace", state["app_id"], app[3]["id"]
            )
            return workspaces.transition(
                db,
                grant,
                actor,
                state["id"],
                WorkspaceTransition(expected_version=state["version"]),
                action="cleanup",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        configuring = pool.submit(configure)
        try:
            assert cached.wait(5)
            closing = pool.submit(close)
            assert closing_locked.wait(5)
            configure_now.set()
            with factory() as observer:
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    if observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"),
                        {"pid": configuration_pid[0]},
                    ):
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Configure did not wait on the native installation row lock")
        finally:
            configure_now.set()
            release_closing.set()
        assert closing.result(timeout=10)["state"] == "cleanup_pending"
        assert configuring.result(timeout=10) == 409
    with factory() as db:
        assert db.get(AppWorkspaceRecord, state["id"]).state == "cleanup_pending"
        installation = db.get(AppInstallationRecord, state["installation"]["id"])
        assert (
            not installation.enabled
            and installation.generation == state["installation"]["generation"] + 1
        )
    assert client.get(BASE + "/session", headers=bearer, params=params).status_code == 401
    with factory() as db:
        for model, request_id in queued.values():
            row = db.get(model, request_id)
            assert (row.state, row.active_slot, row.failure_code) == (
                "failed",
                None,
                "workspace_stopped",
            )
    # The normal closing transition is already durable; the same installation cannot reactivate during data cleanup's receipt commit window.
    removal, finish = Event(), Event()

    class Data:
        def remove_temporary(self, **arguments):
            assert arguments["installation_id"] == state["installation"]["id"]
            arguments["persist_receipt"]({"phase": "verified"})
            removal.set()  # The real Core receipt transaction has already committed.
            assert finish.wait(5)
            arguments["persist_receipt"]({"phase": "removed"})

    class Runtime:
        def stop_workspace(self, specs, *, installation_id):
            assert installation_id == state["installation"]["id"]
            assert {spec.request_id for spec in specs} == {
                queued["deploy"][1],
                historical_request_id,
            }
            assert all(
                spec.installation_id == installation_id
                and spec.app_id == state["app_id"]
                and spec.environment == "development"
                for spec in specs
            )

        def clean_workspace_files(self, specs, *, installation_id):
            assert installation_id == state["installation"]["id"]

    monkeypatch.setattr(workspace_maintenance, "configured_store", lambda _: Data())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            workspace_maintenance._maintain,
            get_settings(),
            factory,
            state["id"],
            lambda *_: Runtime(),
        )
        try:
            assert removal.wait(5)
            installation_path = (
                f"{BASE}/{state['app_id']}/installations/{state['installation']['id']}"
            )
            assert (
                client.put(
                    installation_path, headers=app[1], json=enable_input(app, state)
                ).status_code
                == 409
            )
            preview = client.get(installation_path + "/owner-preview", headers=app[1])
            assert preview.status_code == 200, preview.text
            snapshot = preview.json()
            assert not snapshot["can_configure"]
            assert snapshot["unavailable_reason"] == "already_deployed"
            assert (
                client.patch(
                    installation_path + "/owner-preview",
                    headers=app[1],
                    json={
                        "expected_generation": snapshot["generation"],
                        "expected_definition_digest": snapshot["definition_digest"],
                        "expected_source_revision": snapshot["source_revision"],
                        "enabled": True,
                        "granted_permissions": snapshot["granted_permissions"],
                    },
                ).status_code
                == 409
            )
            for action in ("stop", "resume"):
                assert (
                    client.post(
                        path + "/" + action,
                        headers=headers,
                        json={"expected_version": state["version"] + 1},
                    ).status_code
                    == 409
                )
            with factory() as db:
                installation = db.get(AppInstallationRecord, state["installation"]["id"])
                assert not installation.enabled
                assert installation.generation == state["installation"]["generation"] + 1
                row = db.get(AppWorkspaceRecord, state["id"])
                assert row.state == "cleanup_pending" and row.resources["data_cleanup"] == {
                    "phase": "verified"
                }
        finally:
            finish.set()
        assert future.result(timeout=10)["state"] == "cleaned"
    with factory() as db:
        installation = db.get(AppInstallationRecord, state["installation"]["id"])
        assert installation.state == "archived" and not installation.enabled
        row = db.get(AppWorkspaceRecord, state["id"])
        assert row.resources["data_cleanup"] == {"phase": "removed"}
