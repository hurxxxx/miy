from argparse import Namespace
from datetime import timedelta
import importlib.util
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import flag_modified

from miy_api.core.db import get_session_factory
from miy_api.core.independent_delivery_settings import IndependentDeliveryTarget, validate_targets
from miy_api.core.settings import Settings, WORKSPACE_ROOT
from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeploymentRequest
from miy_api.domains.independent_apps.delivery import (
    Observation,
    execute_deployment,
    reconcile_deployment,
)
from miy_api.domains.independent_apps.executor import poll_once, serve
from miy_api.domains.independent_apps.models import AppInstallationRecord
from test_independent_app_delegation import delegated as delegated, grant
from test_independent_app_delivery import (
    FakeRuntime,
    build_release,
    current_installation,
    enqueue,
)


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


@pytest.mark.parametrize(
    "changes",
    [
        {"platform_origin": "https://user:password@platform.test"},
        {"platform_api_origin": "https://api.platform.test/private"},
        {"platform_api_origin": "https://api.platform.test?token=test"},
        {"platform_api_origin": "http://192.0.2.1"},
        {"platform_api_origin": "https://api.platform.test#fragment"},
        {"toolchain_image": "untrusted:latest"},
        {"source_root": Path("relative")},
        {"command": "host command"},
    ],
)
def test_target_has_exact_origins_paths_images_and_no_commands(tmp_path, changes):
    with pytest.raises(ValidationError):
        target(tmp_path, **changes)


def test_settings_reject_duplicate_installations_cross_target_overlap_and_core_source(tmp_path):
    first = target(tmp_path)
    assert settings_for([first]).independent_app_delivery_targets == [first]
    invalid = [
        [first, first],
        [target(tmp_path, state_root=first.work_root / "state")],
        [first, target(tmp_path / "other", source_root=first.state_root / "nested")],
        [target(tmp_path, source_root=WORKSPACE_ROOT / "templates")],
        [target(tmp_path, platform_origin="https://not-allowed.test")],
    ]
    for targets in invalid:
        with pytest.raises(ValidationError):
            settings_for(targets)
    with pytest.raises(ValidationError, match="development only"):
        Settings(
            _env_file=None,
            environment="preview",
            independent_app_platform_origins=[first.platform_origin],
            independent_app_delivery_targets=[first],
        )


def test_replaced_root_is_revalidated_before_any_database_or_consumer_access(tmp_path):
    binding = target(tmp_path)
    settings = settings_for([binding])
    outside = tmp_path / "outside"
    outside.mkdir()
    binding.source_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="without symlinks"):
        poll_once(settings, None, None)
    with pytest.raises(ValueError):
        validate_targets(
            [binding], platform_root=WORKSPACE_ROOT, platform_origins=[binding.platform_origin]
        )


def test_empty_targets_never_access_database_and_serve_is_opt_in():
    assert poll_once(settings_for([]), None, None) == {"state": "disabled"}
    output = []
    with pytest.raises(ValueError, match="Configure"):
        serve(lambda: {"state": "disabled"}, stop=Event(), emit=output.append, poll_seconds=1)
    assert output == [{"state": "disabled"}]


def test_foreground_stop_and_interval_are_bounded():
    stop = Event()
    output = []

    def operation():
        stop.set()
        return {"state": "unknown", "id": "one-operation"}

    serve(operation, stop=stop, emit=output.append, poll_seconds=1)
    assert output == [{"state": "unknown", "id": "one-operation"}]
    with pytest.raises(ValueError, match="interval"):
        serve(operation, stop=stop, emit=output.append, poll_seconds=0)


def test_serve_refuses_invalid_startup_before_entering_request_loop(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "executor_cli", WORKSPACE_ROOT / "scripts/independent-app-delivery.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr("sys.argv", [str(spec.origin), "serve"])
    monkeypatch.chdir(tmp_path)
    assert cli.main() == 2
    assert "consumer_configuration_required" in capsys.readouterr().out
    monkeypatch.chdir(WORKSPACE_ROOT)
    monkeypatch.setenv("MIY_INDEPENDENT_APP_DELIVERY_TARGETS", "[]")
    from miy_api.core.settings import get_settings

    get_settings.cache_clear()
    try:
        assert cli.main() == 2
        assert "consumer_configuration_required" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


def test_cli_passes_sanitized_consumer_failures_back_to_poller(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "executor_cli_failure_boundary", WORKSPACE_ROOT / "scripts/independent-app-delivery.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    run = cli.run

    def configuration_failure(_args):
        raise ValueError("synthetic configuration failure")

    def poll(_settings, _sessions, consume):
        # The real CLI must sanitize inside selection so it can record an attempt.
        # An outer-only exception boundary would hide this result from the poller.
        return consume(Namespace(command="reconcile"))

    monkeypatch.setattr(cli, "run", configuration_failure)
    monkeypatch.setattr("miy_api.domains.independent_apps.executor.poll_once", poll)
    monkeypatch.setattr("miy_api.core.db.get_session_factory", lambda: None)
    monkeypatch.chdir(WORKSPACE_ROOT)
    assert run(Namespace(command="poll-once")) == {
        "state": "unknown",
        "failure_code": "operator_check_required",
    }


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


def test_pg_poller_consumes_one_oldest_bound_intent_with_only_operator_arguments(
    client, delegated, tmp_path
):
    release = build_release(delegated[2])
    build_id = queue_build(client, delegated)
    deployment, _ = enqueue(client, delegated, release)
    with get_session_factory()() as db:
        db.get(AppBuildJob, build_id).updated_at = utcnow_naive() - timedelta(minutes=1)
        db.commit()
    binding = target(tmp_path, delegated[3]["id"])
    settings = settings_for([binding])
    called = []

    def consume(args):
        called.append(vars(args))
        # A real consumer owns the state transition; selection does not claim it.
        with get_session_factory()() as db:
            job = db.get(AppBuildJob, build_id)
            assert job.state == "queued"
            job.state = "failed"
            db.commit()
        return {"state": "failed", "id": build_id}

    assert poll_once(settings, get_session_factory(), consume)["id"] == build_id
    assert called == [
        {
            "command": "build-request",
            "app_id": binding.app_id,
            "installation_id": delegated[3]["id"],
            "build_id": build_id,
            "source": binding.source_root,
            "work_root": binding.work_root,
            "toolchain_image": binding.toolchain_image,
        }
    ]
    called.clear()
    poll_once(
        settings,
        get_session_factory(),
        lambda args: called.append(vars(args)) or {"state": "queued"},
    )
    assert called == [
        {
            "command": "execute",
            "app_id": binding.app_id,
            "installation_id": delegated[3]["id"],
            "request_id": deployment["request_id"],
            "state_root": binding.state_root,
            "ingress_image": binding.ingress_image,
            "platform_origin": binding.platform_origin,
            "platform_api_origin": binding.platform_api_origin,
        }
    ]


def test_pg_poller_excludes_wrong_bindings_production_and_uncertain_states(
    client, delegated, tmp_path
):
    build_id = queue_build(client, delegated)
    binding = target(tmp_path, delegated[3]["id"])
    assert (
        poll_once(settings_for([target(tmp_path)]), get_session_factory(), None)["state"] == "idle"
    )
    assert (
        poll_once(
            settings_for([target(tmp_path, delegated[3]["id"], app_id="other-app")]),
            get_session_factory(),
            None,
        )["state"]
        == "idle"
    )
    with get_session_factory()() as db:
        db.get(AppInstallationRecord, delegated[3]["id"]).environment = "production"
        db.commit()
    assert poll_once(settings_for([binding]), get_session_factory(), None)["state"] == "idle"
    with get_session_factory()() as db:
        db.get(AppInstallationRecord, delegated[3]["id"]).environment = "development"
        db.commit()
        for state in ("running", "unknown", "succeeded", "failed"):
            db.get(AppBuildJob, build_id).state = state
            db.commit()
            assert (
                poll_once(settings_for([binding]), get_session_factory(), None)["state"] == "idle"
            )


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


@pytest.mark.parametrize("state", ["running", "unknown", "cleanup"])
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
    ("operation", "commit_state"),
    [("execute", "running"), ("execute", "cleanup"), ("reconcile", "cleanup")],
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


@pytest.mark.parametrize("failure_phase", ["prepare", "retire"])
def test_pg_unexpected_exception_releases_guard_for_same_id_reconciliation(
    client, delegated, monkeypatch, failure_phase
):
    release = build_release(delegated[2])
    runtime = AbsenceAwareRuntime()
    installation = delegated[3]
    previous_id = None
    if failure_phase == "retire":
        previous, _ = enqueue(client, delegated, release)
        previous_id = previous["request_id"]
        with get_session_factory()() as db:
            assert execute_deployment(db, previous_id, runtime).state == "succeeded"
        installation = current_installation(installation["id"])
    deployment, _ = enqueue(client, delegated, release, installation=installation)
    request_id = deployment["request_id"]

    def interrupted(*_args):
        raise RuntimeError("synthetic process interruption")

    with monkeypatch.context() as interruption:
        interruption.setattr(
            runtime, "prepare_hook" if failure_phase == "prepare" else "retire", interrupted
        )
        with pytest.raises(RuntimeError, match="synthetic process interruption"):
            with get_session_factory()() as db:
                execute_deployment(db, request_id, runtime)

    def replay_denied(_spec):
        pytest.fail("Recovery must not replay prepare or activate")

    monkeypatch.setattr(runtime, "prepare", replay_denied)
    monkeypatch.setattr(runtime, "activate", replay_denied)
    with get_session_factory()() as db:
        result = reconcile_deployment(db, request_id, runtime)
        assert result.state == ("failed" if failure_phase == "prepare" else "succeeded")
        assert db.get(AppDeploymentRequest, request_id).active_slot is None
        if failure_phase == "prepare":
            assert result.failure_code == "activation_not_started"
    assert runtime.retired == ([previous_id] if previous_id else [])
    if failure_phase == "prepare":
        assert runtime.activations == [] and runtime.candidates == {}
    else:
        assert runtime.activations == [previous_id, request_id]


def test_pg_json_null_runtime_does_not_hide_next_reconciliation_candidate(
    client, delegated, tmp_path
):
    release = build_release(delegated[2])
    missing, _ = enqueue(client, delegated, release)
    with get_session_factory()() as db:
        record = db.get(AppDeploymentRequest, missing["request_id"])
        # An incomplete historical row is not a usable runtime specification.
        # Explicit Python None persists JSON null, unlike an omitted SQL NULL.
        record.state, record.runtime_config = "unknown", None
        flag_modified(record, "runtime_config")
        record.updated_at = utcnow_naive() - timedelta(hours=1)
        db.commit()
        assert (
            db.scalar(
                select(func.json_typeof(AppDeploymentRequest.runtime_config)).where(
                    AppDeploymentRequest.id == record.id
                )
            )
            == "null"
        )
        assert (
            db.scalar(
                select(AppDeploymentRequest.id).where(
                    AppDeploymentRequest.id == record.id,
                    AppDeploymentRequest.runtime_config.is_not(None),
                )
            )
            == record.id
        )
    created = client.post(
        "/api/v1/independent-apps/sample-independent/installations",
        headers=delegated[1],
        json=delegated[4] | {"origin": "https://second-preview.test"},
    )
    assert created.status_code == 201
    installation = created.json()
    deployment, _ = enqueue(client, delegated, release, installation=installation)
    runtime = AbsenceAwareRuntime()
    runtime.lose_response = True
    with get_session_factory()() as db:
        assert execute_deployment(db, deployment["request_id"], runtime).state == "unknown"
    settings = settings_for(
        [
            target(tmp_path / "missing", delegated[3]["id"]),
            target(tmp_path / "ready", installation["id"]),
        ]
    )
    calls = []

    def consume(args):
        assert args.command == "reconcile"
        calls.append(args.request_id)
        with get_session_factory()() as db:
            return reconcile_deployment(db, args.request_id, runtime).model_dump(mode="json")

    assert poll_once(settings, get_session_factory(), consume)["state"] == "succeeded"
    assert calls == [deployment["request_id"]]
    assert runtime.activations == [deployment["request_id"]]
    assert poll_once(settings, get_session_factory(), consume) == {"state": "idle"}
    with get_session_factory()() as db:
        assert db.get(AppDeploymentRequest, missing["request_id"]).state == "unknown"


def test_pg_configuration_failure_yields_to_independent_queued_build(client, delegated, tmp_path):
    release = build_release(delegated[2])
    deployment, _ = enqueue(client, delegated, release)
    runtime = AbsenceAwareRuntime()
    runtime.lose_response = True
    with get_session_factory()() as db:
        assert execute_deployment(db, deployment["request_id"], runtime).state == "unknown"
    build_id = queue_build(client, delegated)
    deployment_attempt = utcnow_naive() - timedelta(minutes=2)
    build_attempt = deployment_attempt + timedelta(minutes=1)
    with get_session_factory()() as db:
        record = db.get(AppDeploymentRequest, deployment["request_id"])
        record.updated_at = deployment_attempt
        original = (record.state, record.active_slot, record.failure_code, record.runtime_config)
        db.get(AppBuildJob, build_id).updated_at = build_attempt
        db.commit()
    settings = settings_for([target(tmp_path, delegated[3]["id"])])
    calls = []

    def consume(args):
        calls.append(args.command)
        if args.command == "reconcile":
            return {"state": "unknown", "failure_code": "operator_check_required"}
        assert args.command == "build-request" and args.build_id == build_id
        return {"state": "queued", "id": build_id}

    assert poll_once(settings, get_session_factory(), consume)["failure_code"] == (
        "operator_check_required"
    )
    with get_session_factory()() as db:
        record = db.get(AppDeploymentRequest, deployment["request_id"])
        assert record.updated_at > build_attempt
        assert (record.state, record.active_slot, record.failure_code, record.runtime_config) == (
            original
        )
    assert poll_once(settings, get_session_factory(), consume)["id"] == build_id
    assert calls == ["reconcile", "build-request"]
    assert runtime.activations == [deployment["request_id"]]


@pytest.mark.parametrize("kind", ["build", "deployment"])
@pytest.mark.parametrize("change", ["updated", "claimed", "terminal", "locked"])
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


@pytest.mark.parametrize(
    "result",
    [
        {"state": "succeeded"},
        {"state": "failed", "failure_code": "operator_check_required"},
        {"state": "unknown", "failure_code": "reconciliation_required"},
    ],
)
def test_pg_other_consumer_results_do_not_advance_attempt_timestamp(
    client, delegated, tmp_path, result
):
    build_id = queue_build(client, delegated)
    attempted_at = utcnow_naive() - timedelta(minutes=2)
    with get_session_factory()() as db:
        db.get(AppBuildJob, build_id).updated_at = attempted_at
        db.commit()
    assert (
        poll_once(
            settings_for([target(tmp_path, delegated[3]["id"])]),
            get_session_factory(),
            lambda _args: result,
        )
        == result
    )
    with get_session_factory()() as db:
        record = db.get(AppBuildJob, build_id)
        assert (record.updated_at, record.state, record.active_slot) == (
            attempted_at,
            "queued",
            None,
        )
