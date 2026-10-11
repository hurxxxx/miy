from argparse import Namespace
from datetime import timedelta
import importlib.util
from uuid import uuid4

import pytest
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget
from miy_api.core.settings import Settings, WORKSPACE_ROOT
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeploymentRequest
from miy_api.domains.independent_apps.delivery import (
    Observation,
    execute_deployment,
    reconcile_deployment,
)
from miy_api.domains.independent_apps.executor import poll_once
from miy_api.domains.independent_apps.models import AppInstallationRecord
from test_independent_app_delegation import delegated as delegated, grant
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    enqueue,
)
from test_independent_app_workspaces import workspace as workspace


def target(tmp_path, installation_id=None, **changes):
    return IndependentDeliveryTarget(
        **{
            "app_id": "sample-independent",
            "installation_id": installation_id or uuid4(),
            "source_root": tmp_path / "app",
            "work_root": tmp_path / "scratch",
            "state_root": tmp_path / "runtime",
            "toolchain_image": "sha256:" + "a" * 64,
            "ingress_image": "sha256:" + "b" * 64,
            "platform_origin": "https://platform.test",
            "platform_api_origin": "https://api.platform.test",
            **changes,
        }
    )


def settings_for(targets):
    return Settings(
        _env_file=None,
        independent_app_platform_origins=["https://platform.test"],
        independent_app_delivery_targets=targets,
    )


def queue_build(client, app):
    _, headers, path = grant(client, app)
    request_id = str(uuid4())
    response = client.post(
        path + "/builds",
        headers=headers,
        json={
            "request_id": request_id,
            "source_revision": "a" * 40,
            "definition_digest": app[2]["definition_digest"],
        },
    )
    assert response.status_code == 202
    return request_id


def test_pg_unknown_build_keeps_slot_but_does_not_block_independent_deployment_queue(
    client, delegated, tmp_path
):
    release = build_release(delegated[2])
    first = queue_build(client, delegated)
    second = queue_build(client, delegated)
    deployment, _ = enqueue(client, delegated, release)
    with get_session_factory()() as db:
        row = db.get(AppBuildJob, first)
        row.state, row.active_slot = "unknown", 1
        db.commit()
    seen = []
    settings = settings_for([target(tmp_path, delegated[3]["id"])])
    poll_once(
        settings, get_session_factory(), lambda args: seen.append(vars(args)) or {"state": "queued"}
    )
    assert len(seen) == 1 and seen[0]["request_id"] == deployment["request_id"]
    with get_session_factory()() as db:
        assert db.get(AppBuildJob, second).state == "queued"
        record = db.get(AppDeploymentRequest, deployment["request_id"])
        record.state, record.active_slot = "unknown", 1
        db.commit()
    assert poll_once(settings, get_session_factory(), None)["state"] == "idle"


@pytest.mark.parametrize("state", ["unknown"])
def test_pg_poller_observes_interrupted_deployment_without_replaying_side_effects(
    client, delegated, tmp_path, monkeypatch, state
):
    release = build_release(delegated[2])
    deployment, _ = enqueue(client, delegated, release)
    request_id = deployment["request_id"]
    runtime = FakeRuntime()
    runtime.lose_response = state != "cleanup"
    with get_session_factory()() as db:
        expected = "succeeded" if state == "cleanup" else "unknown"
        assert execute_deployment(db, request_id, runtime).state == expected
        row = db.get(AppDeploymentRequest, request_id)
        row.state, row.active_slot = state, 1
        db.commit()
    settings = settings_for([target(tmp_path, delegated[3]["id"])])
    calls = []

    def consume(args):
        assert args.command == "reconcile" and args.request_id == request_id
        calls.append(vars(args))
        with get_session_factory()() as db:
            return reconcile_deployment(db, args.request_id, runtime).model_dump(mode="json")

    def replay_denied(_spec):
        pytest.fail("Reconciliation must not prepare or activate a runtime")

    monkeypatch.setattr(runtime, "prepare", replay_denied)
    monkeypatch.setattr(runtime, "activate", replay_denied)
    assert poll_once(settings_for([target(tmp_path)]), get_session_factory(), consume) == {
        "state": "idle"
    }

    # Do not block on or interfere with an executor that still owns its row.
    with get_session_factory()() as running:
        running.scalar(
            select(AppDeploymentRequest)
            .where(AppDeploymentRequest.id == request_id)
            .with_for_update()
        )
        assert poll_once(settings, get_session_factory(), consume) == {"state": "idle"}
        assert calls == []
    assert poll_once(settings, get_session_factory(), consume)["state"] == "succeeded"
    assert len(calls) == 1
    assert runtime.activations == [request_id]
    assert list(runtime.candidates) == [request_id]
    assert poll_once(settings, get_session_factory(), consume) == {"state": "idle"}
    with get_session_factory()() as db:
        assert len(list(db.scalars(select(AppDeploymentRequest)))) == 1
        assert db.get(AppInstallationRecord, delegated[3]["id"]).runtime_ref == request_id


class AbsenceAwareRuntime(FakeRuntime):
    def observe(self, spec):
        observed = super().observe(spec)
        return Observation(
            observed.active,
            observed.healthy,
            observed.image_id,
            observed.candidate_exists,
            ingress_absent=self.active is None,
        )


@pytest.mark.parametrize(
    "operation,commit_state", [("execute", "running"), ("reconcile", "cleanup")]
)
def test_pg_live_operation_survives_poller_between_commit_and_relock(
    client, delegated, tmp_path, monkeypatch, operation, commit_state
):
    release = build_release(delegated[2])
    runtime = AbsenceAwareRuntime()
    previous_id = None
    installation = delegated[3]
    if commit_state == "cleanup":
        previous, _ = enqueue(client, delegated, release)
        previous_id = previous["request_id"]
        with get_session_factory()() as db:
            assert execute_deployment(db, previous_id, runtime).state == "succeeded"
        installation = current_installation(installation["id"])
    deployment, _ = enqueue(client, delegated, release, installation=installation)
    request_id = deployment["request_id"]
    settings = settings_for([target(tmp_path, installation["id"])])
    if operation == "reconcile":
        runtime.lose_response = True
        with get_session_factory()() as db:
            assert execute_deployment(db, request_id, runtime).state == "unknown"
    observations = []

    def consume(args):
        assert args.command == "reconcile" and args.request_id == request_id
        with get_session_factory()() as db:
            result = reconcile_deployment(db, request_id, runtime)
            observations.append(result.state)
            return result.model_dump(mode="json")

    with get_session_factory()() as db:
        original_commit = db.commit
        polled = False

        def commit_then_poll():
            nonlocal polled
            expected_window = db.get(AppDeploymentRequest, request_id).state == commit_state
            original_commit()
            if expected_window and not polled:
                polled = True
                # This is a real second PostgreSQL consumer in the exact gap
                # where the row lock is gone but the first operation is alive.
                result = poll_once(settings, get_session_factory(), consume)
                assert result["state"] == commit_state
                assert runtime.retired == []
                if commit_state == "running":
                    assert runtime.activations == [] and runtime.candidates == {}

        monkeypatch.setattr(db, "commit", commit_then_poll)
        run = execute_deployment if operation == "execute" else reconcile_deployment
        assert run(db, request_id, runtime).state == "succeeded"
    assert observations == [commit_state]
    assert runtime.activations == ([previous_id] if previous_id else []) + [request_id]
    assert runtime.retired == ([previous_id] if previous_id else [])
    assert poll_once(settings, get_session_factory(), consume) == {"state": "idle"}


@pytest.mark.parametrize("kind,change", [("deployment", "terminal")])
def test_pg_failed_attempt_preserves_concurrent_consumer_metadata(
    client, delegated, tmp_path, kind, change
):
    if kind == "build":
        request_id = queue_build(client, delegated)
        model = AppBuildJob
    else:
        release = build_release(delegated[2])
        deployment, _ = enqueue(client, delegated, release)
        request_id, model = deployment["request_id"], AppDeploymentRequest
    original_attempt = utcnow_naive() - timedelta(minutes=2)
    with get_session_factory()() as db:
        db.get(model, request_id).updated_at = original_attempt
        db.commit()
    expected = []

    with get_session_factory()() as competing:

        def consume(_args):
            record = competing.scalar(select(model).where(model.id == request_id).with_for_update())
            if change == "updated":
                record.updated_at += timedelta(seconds=1)
                record.failure_code = "competing_attempt"
            elif change == "claimed":
                # A durable claim changes state/slot before its timestamp advances.
                record.state, record.active_slot = "running", 1
            elif change == "terminal":
                record.state, record.failure_code = "failed", "competing_failure"
            expected.extend(
                [record.updated_at, record.state, record.active_slot, record.failure_code]
            )
            if change != "locked":
                competing.commit()
            return {"state": "unknown", "failure_code": "operator_check_required"}

        assert (
            poll_once(
                settings_for([target(tmp_path, delegated[3]["id"])]), get_session_factory(), consume
            )["failure_code"]
            == "operator_check_required"
        )
    with get_session_factory()() as db:
        record = db.get(model, request_id)
        assert [
            record.updated_at,
            record.state,
            record.active_slot,
            record.failure_code,
        ] == expected


def test_claimed_build_losing_workspace_before_execution_releases_capacity(
    client, delegated, monkeypatch, tmp_path
):
    from miy_api.domains.independent_apps import workspaces

    request_id = queue_build(client, delegated)
    spec = importlib.util.spec_from_file_location(
        "claimed_workspace_cli", WORKSPACE_ROOT / "scripts/independent-app-delivery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(WORKSPACE_ROOT)
    original = workspaces.definition_for_installation
    reads = 0

    def definition(db, app_id, installation_id):
        nonlocal reads
        reads += 1
        return original(db, app_id, installation_id) if reads == 1 else None

    monkeypatch.setattr(workspaces, "definition_for_installation", definition)
    result = module.run(
        Namespace(
            command="build-request",
            app_id="sample-independent",
            installation_id=delegated[3]["id"],
            build_id=request_id,
            source=tmp_path,
            work_root=tmp_path,
            toolchain_image="sha256:" + "a" * 64,
        )
    )
    assert result["state"] == "failed" and result["failure_code"] == "source_changed"
    with get_session_factory()() as db:
        assert db.get(AppBuildJob, request_id).active_slot is None
