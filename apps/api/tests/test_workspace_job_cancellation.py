"""Native row-lock races preserve delivery claims and completion evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event, get_ident
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps import delegation, delivery, workspaces
from miy_api.domains.independent_apps.builds import BuildEvidence
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppDeploymentRequest,
    AppRuntimeSlot,
)
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord
from miy_api.domains.independent_apps.workspace_contracts import WorkspaceTransition
from miy_api.domains.independent_apps.workspace_models import AppWorkspaceRecord
from miy_api.domains.independent_apps.workspace_maintenance import _maintain
from test_independent_app_workspaces import workspace as workspace


def _queued_requests(client, workspace):
    _, headers, path, _, state = workspace

    def build():
        request_id = str(uuid4())
        response = client.post(
            path + "/builds",
            headers=headers,
            json={
                "request_id": request_id,
                "source_revision": state["source_revision"],
                "definition_digest": state["definition_digest"],
            },
        )
        assert response.status_code == 202, response.text
        return request_id

    verified_id = build()
    with get_session_factory()() as db:
        job, claimed = delivery.start_build_job(
            db, state["app_id"], state["source_revision"], verified_id
        )
        assert claimed
        release = delivery.persist_verified_build(
            db,
            job,
            BuildEvidence(
                app_id=job.app_id,
                source_revision=state["source_revision"],
                definition_digest=state["definition_digest"],
                source_archive_sha256="c" * 64,
                artifact_digest="sha256:" + "e" * 64,
                builder_profile_digest="sha256:" + "d" * 64,
                checks={"test": 0, "build": 0},
            ),
        )
        release_id = release.id
    build_id = build()
    deployment_id = str(uuid4())
    response = client.post(
        path + "/deployments",
        headers=headers,
        json={
            "request_id": deployment_id,
            "installation_id": state["installation"]["id"],
            "release_id": release_id,
            "expected_generation": state["installation"]["generation"],
            "expected_release_id": None,
        },
    )
    assert response.status_code == 202, response.text
    return {"build": (AppBuildJob, build_id), "deploy": (AppDeploymentRequest, deployment_id)}


@pytest.mark.parametrize("kind", ["build", "deploy"])
@pytest.mark.parametrize("outcome", ["claimed", "completed"])
def test_pg_workspace_stop_preserves_concurrent_delivery_owner(client, workspace, kind, outcome):
    requests = _queued_requests(client, workspace)
    model, request_id = requests[kind]
    app, headers, _, _, state = workspace
    factory = get_session_factory()
    started = Event()
    backend = []

    def stop():
        with factory() as db:
            backend.append(db.scalar(text("SELECT pg_backend_pid()")))
            started.set()
            grant, actor = delegation.resolve(
                db, headers["Authorization"], "workspace", state["app_id"], app[3]["id"]
            )
            return workspaces.transition(
                db,
                grant,
                actor,
                state["id"],
                WorkspaceTransition(expected_version=state["version"]),
                action="stop",
            )

    # This transaction holds a real native row claim while the stop transaction
    # sees the committed queued version. No SQL predicates or row locks are mocked.
    with ThreadPoolExecutor(max_workers=1) as pool, factory() as consumer:
        row = consumer.scalar(select(model).where(model.id == request_id).with_for_update())
        row.state, row.active_slot = "running", 1
        if kind == "deploy":
            installation = consumer.get(AppInstallationRecord, row.installation_id)
            release = consumer.get(AppReleaseRecord, row.release_id)
            row.runtime_config = asdict(
                delivery._runtime_spec(row, installation, release, consumer)
            )
        consumer.flush()
        future = pool.submit(stop)
        try:
            assert started.wait(5)
            deadline = monotonic() + 5
            with factory() as observer:
                while monotonic() < deadline:
                    if (
                        observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": backend[0]}
                        )
                        > 0
                    ):
                        break
                    sleep(0.01)
                else:
                    pytest.fail("Workspace stop did not reach the real PostgreSQL row lock")
            if outcome == "completed":
                row.state, row.active_slot = "succeeded", None
                if kind == "deploy":
                    row.observed_image_id = release.artifact
            row.failure_code = None
            row.updated_at = utcnow_naive()
            expected = (row.state, row.active_slot, row.failure_code, row.updated_at)
            runtime_config = row.runtime_config if kind == "deploy" else None
            observed_image = row.observed_image_id if kind == "deploy" else None
            consumer.commit()
        finally:
            consumer.rollback()
        stopped = future.result(timeout=10)
    assert stopped["state"] == "stopping"
    with factory() as db:
        row = db.get(model, request_id)
        assert (row.state, row.active_slot, row.failure_code, row.updated_at) == expected
        assert row.installation_id == state["installation"]["id"]
        if kind == "deploy":
            assert row.runtime_config == runtime_config and row.observed_image_id == observed_image
        other_model, other_id = requests["deploy" if kind == "build" else "build"]
        other = db.get(other_model, other_id)
        assert (other.state, other.active_slot, other.failure_code) == (
            "failed",
            None,
            "workspace_stopped",
        )
        installation = db.get(AppInstallationRecord, state["installation"]["id"])
        assert not installation.enabled
        assert db.get(AppWorkspaceRecord, state["id"]).state == "stopping"


def test_pg_workspace_stop_cancels_only_queued_unclaimed_requests(client, workspace):
    requests = _queued_requests(client, workspace)
    _, headers, path, _, state = workspace
    response = client.post(
        path + "/stop", headers=headers, json={"expected_version": state["version"]}
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        for model, request_id in requests.values():
            row = db.get(model, request_id)
            assert (row.state, row.active_slot, row.failure_code) == (
                "failed",
                None,
                "workspace_stopped",
            )


@pytest.mark.parametrize("kind", ["build", "deploy"])
def test_pg_workspace_stop_preserves_a_queued_request_with_a_reserved_slot(client, workspace, kind):
    requests = _queued_requests(client, workspace)
    model, request_id = requests[kind]
    _, headers, path, _, state = workspace
    with get_session_factory()() as db:
        row = db.get(model, request_id)
        row.active_slot = 1
        original_updated_at = row.updated_at
        db.commit()
    response = client.post(
        path + "/stop", headers=headers, json={"expected_version": state["version"]}
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as db:
        row = db.get(model, request_id)
        assert (row.state, row.active_slot, row.failure_code, row.updated_at) == (
            "queued",
            1,
            None,
            original_updated_at,
        )


def test_pg_maintenance_stop_completion_preserves_approved_cleanup(client, workspace, monkeypatch):
    _, headers, path, _, state = workspace
    factory = get_session_factory()
    with factory() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        # Synthetic owned handoff evidence permits the real approval boundary;
        # this race does not claim an actual merged or deployed app.
        row.resources = {**row.resources, "integration_deployment_id": str(uuid4())}
        db.add(AppRuntimeSlot(installation_id=row.installation_id, slot=0))
        db.commit()
    stopped = client.post(
        path + "/stop", headers=headers, json={"expected_version": state["version"]}
    )
    assert stopped.status_code == 200, stopped.text
    refreshed, approved = Event(), Event()
    maintenance_thread = []
    original_refresh = Session.refresh

    def refresh(db, instance, *args, **kwargs):
        original_refresh(db, instance, *args, **kwargs)
        if (
            maintenance_thread
            and get_ident() == maintenance_thread[0]
            and isinstance(instance, AppWorkspaceRecord)
            and instance.id == state["id"]
        ):
            # Only scheduling is controlled: both refresh and approval use
            # native PostgreSQL transactions and the production predicates.
            assert instance.state == "stopping"
            refreshed.set()
            assert approved.wait(5)

    monkeypatch.setattr(Session, "refresh", refresh)

    class Runtime:
        def stop_workspace(self, specs, *, installation_id):
            assert specs == [] and installation_id == state["installation"]["id"]

    def maintain():
        maintenance_thread.append(get_ident())
        return _maintain(get_settings(), factory, state["id"], lambda *_: Runtime())

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(maintain)
        try:
            assert refreshed.wait(5)
            cleanup = client.post(
                path + "/cleanup",
                headers=headers,
                json={"expected_version": stopped.json()["version"]},
            )
            assert cleanup.status_code == 200, cleanup.text
            assert cleanup.json()["state"] == "cleanup_pending"
            with factory() as db:
                row = db.get(AppWorkspaceRecord, state["id"])
                expected = (row.state, row.version, row.updated_at, dict(row.resources), row.slot)
                installation = db.get(AppInstallationRecord, row.installation_id)
                expected_admission = (
                    installation.enabled,
                    installation.state,
                    installation.generation,
                )
        finally:
            approved.set()
        assert future.result(timeout=10) == {"state": "idle"}
    with factory() as db:
        row = db.get(AppWorkspaceRecord, state["id"])
        assert (row.state, row.version, row.updated_at, row.resources, row.slot) == expected
        installation = db.get(AppInstallationRecord, row.installation_id)
        assert (
            installation.enabled,
            installation.state,
            installation.generation,
        ) == expected_admission
        assert db.get(AppRuntimeSlot, row.installation_id).slot == 0
