from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps.builds import BuildEvidence
from miy_api.domains.independent_apps.delivery import (
    Observation,
    RuntimeFailure,
    execute_deployment,
    persist_verified_build,
    reconcile_deployment,
    start_build_job,
)
from miy_api.domains.independent_apps.delivery_models import (
    AppBuildJob,
    AppBuildVerification,
    AppDeploymentRequest,
    AppRuntimeSlot,
)
from miy_api.domains.independent_apps.models import AppInstallationRecord
from test_independent_apps import setup_app


@pytest.fixture
def delivery_app(client, monkeypatch):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["https://platform.test"]')
    get_settings.cache_clear()
    result = setup_app(client)
    yield result
    get_settings.cache_clear()


def build_release(definition, digit="a", revision="a" * 40):
    with get_session_factory()() as db:
        job, claimed = start_build_job(db, "sample-independent", revision, str(uuid4()))
        assert claimed
        release = persist_verified_build(
            db,
            job,
            BuildEvidence(
                app_id="sample-independent",
                source_revision=revision,
                definition_digest=definition["definition_digest"],
                source_archive_sha256="c" * 64,
                artifact_digest="sha256:" + digit * 64,
                builder_profile_digest="sha256:" + "d" * 64,
                checks={"test": 0, "build": 0},
            ),
        )
        return release.id


def enqueue(client, app, release_id, *, installation=None, action="deploy", status=202):
    _, headers, _, default_installation, _ = app
    installation = installation or default_installation
    payload = {
        "request_id": str(uuid4()),
        "installation_id": installation["id"],
        "release_id": release_id,
        "expected_generation": installation["generation"],
        "expected_release_id": installation.get("release_id"),
        "action": action,
    }
    response = client.post(
        "/api/v1/independent-apps/sample-independent/deployments", headers=headers, json=payload
    )
    assert response.status_code == status, response.text
    return payload, response.json()


def current_installation(installation_id):
    with get_session_factory()() as db:
        row = db.get(AppInstallationRecord, installation_id)
        return {"id": row.id, "generation": row.generation, "release_id": row.release_id}


class FakeRuntime:
    def __init__(self):
        self.active = None
        self.candidates = {}
        self.activations = []
        self.retired = []
        self.fail_health = False
        self.lose_response = False
        self.before_activate = None
        self.prepare_hook = None

    def prepare(self, spec):
        self.candidates[spec.request_id] = spec
        if self.prepare_hook:
            self.prepare_hook()
        if self.fail_health:
            raise RuntimeFailure("health_check_failed", uncertain=False)

    def activate(self, spec):
        if self.before_activate:
            self.before_activate()
        self.active = spec.request_id
        self.activations.append(spec.request_id)
        if self.lose_response:
            self.lose_response = False
            raise RuntimeFailure("daemon_response_lost")

    def observe(self, spec):
        return Observation(
            self.active == spec.request_id, True, spec.image_id, spec.request_id in self.candidates
        )

    def discard(self, spec):
        assert self.active != spec.request_id
        self.candidates.pop(spec.request_id, None)

    def retire(self, spec):
        assert self.active != spec.request_id
        self.retired.append(spec.request_id)


def execute(request, runtime):
    with get_session_factory()() as db:
        return execute_deployment(db, request["request_id"], runtime)


def test_actual_verification_required_and_no_caller_boolean(client, delivery_app):
    _, headers, definition, installation, _ = delivery_app
    candidate = client.post(
        "/api/v1/independent-apps/sample-independent/releases",
        headers=headers,
        json={
            "source_revision": "a" * 40,
            "definition_digest": definition["definition_digest"],
            "artifact": "sha256:" + "a" * 64,
        },
    )
    assert candidate.status_code == 201, candidate.text
    enqueue(client, delivery_app, candidate.json()["id"], status=409)
    response = client.post(
        "/api/v1/independent-apps/sample-independent/deployments",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "installation_id": installation["id"],
            "release_id": candidate.json()["id"],
            "expected_generation": installation["generation"],
            "verified": True,
        },
    )
    assert response.status_code == 422


def test_idempotent_deploy_failed_health_retry_and_code_rollback(client, delivery_app):
    _, headers, definition, installation, _ = delivery_app
    runtime = FakeRuntime()
    first_release = build_release(definition)
    first, _ = enqueue(client, delivery_app, first_release)
    assert execute(first, runtime).state == "succeeded"
    assert execute(first, runtime).state == "succeeded"
    assert runtime.activations == [first["request_id"]]
    response = client.post(
        "/api/v1/independent-apps/sample-independent/deployments", headers=headers, json=first
    )
    assert response.status_code == 202 and response.json()["state"] == "succeeded"
    assert (
        client.post(
            "/api/v1/independent-apps/sample-independent/deployments",
            headers=headers,
            json=first | {"action": "rollback"},
        ).status_code
        == 409
    )
    second_release = build_release(definition, "b")
    current = current_installation(installation["id"])
    failed, _ = enqueue(client, delivery_app, second_release, installation=current)
    runtime.fail_health = True
    assert execute(failed, runtime).state == "failed"
    assert runtime.active == first["request_id"]
    assert current_installation(installation["id"]) == current
    runtime.fail_health = False
    retry, _ = enqueue(client, delivery_app, second_release, installation=current)
    assert execute(retry, runtime).state == "succeeded"
    assert runtime.retired == [first["request_id"]]
    rollback, _ = enqueue(
        client,
        delivery_app,
        first_release,
        installation=current_installation(installation["id"]),
        action="rollback",
    )
    assert execute(rollback, runtime).state == "succeeded"
    assert current_installation(installation["id"])["release_id"] == first_release
    assert runtime.retired[-1] == retry["request_id"]


def test_response_loss_reconciles_without_repeating_side_effects(client, delivery_app):
    release = build_release(delivery_app[2])
    request, _ = enqueue(client, delivery_app, release)
    runtime = FakeRuntime()
    runtime.lose_response = True
    assert execute(request, runtime).state == "unknown"
    assert execute(request, runtime).state == "unknown"
    with get_session_factory()() as db:
        assert db.get(AppDeploymentRequest, request["request_id"]).active_slot == 1
        assert reconcile_deployment(db, request["request_id"], runtime).state == "succeeded"
    assert runtime.activations == [request["request_id"]]


@pytest.mark.parametrize(
    "revocation", ["verification", "company", "source_session", "user", "installation"]
)
def test_policy_revocation_during_prepare_prevents_activation_and_releases_first_slot(
    client, delivery_app, revocation
):
    release = build_release(delivery_app[2])
    request, _ = enqueue(client, delivery_app, release)
    runtime = FakeRuntime()

    def revoke():
        with get_session_factory()() as db:
            from miy_api.domains.auth.models import (
                AuthSession,
                CompanyAppControl,
                User,
                utcnow_naive,
            )

            if revocation == "verification":
                db.scalar(select(AppBuildVerification)).revoked_at = utcnow_naive()
            elif revocation == "company":
                db.get(CompanyAppControl, "sample-independent").enabled = False
            elif revocation == "source_session":
                record = db.get(AppDeploymentRequest, request["request_id"])
                db.get(AuthSession, record.source_session_id).revoked_at = utcnow_naive()
            elif revocation == "user":
                db.get(User, delivery_app[0]["user"]["id"]).login_blocked = True
            else:
                installation = db.get(AppInstallationRecord, request["installation_id"])
                installation.enabled = False
                installation.generation += 1
            db.commit()

    runtime.prepare_hook = revoke
    assert execute(request, runtime).state == "failed"
    assert not runtime.activations and not runtime.candidates
    with get_session_factory()() as db:
        assert db.get(AppRuntimeSlot, request["installation_id"]) is None


def test_reconcile_returns_current_state_without_touching_live_executor(client, delivery_app):
    release = build_release(delivery_app[2])
    request, _ = enqueue(client, delivery_app, release)
    runtime = FakeRuntime()
    preparing, resume, reconciling = Event(), Event(), Event()

    def wait_prepare():
        preparing.set()
        assert resume.wait(10)

    runtime.prepare_hook = wait_prepare

    def reconcile():
        reconciling.set()
        with get_session_factory()() as db:
            return reconcile_deployment(db, request["request_id"], runtime)

    with ThreadPoolExecutor(max_workers=2) as pool:
        deploying = pool.submit(execute, request, runtime)
        assert preparing.wait(5)
        recovery = pool.submit(reconcile)
        assert reconciling.wait(5)
        assert recovery.result(timeout=5).state == "running"
        resume.set()
        assert deploying.result(timeout=10).state == "succeeded"
    with get_session_factory()() as db:
        assert reconcile_deployment(db, request["request_id"], runtime).state == "succeeded"
    assert len(runtime.activations) == 1


def test_build_capacity_and_same_id_do_not_repeat_claim(client, delivery_app):
    first_id, second_id = str(uuid4()), str(uuid4())
    with get_session_factory()() as db:
        first, claimed = start_build_job(db, "sample-independent", "a" * 40, first_id)
        assert claimed
        _, claimed = start_build_job(db, "sample-independent", "a" * 40, first_id)
        assert not claimed
        second, claimed = start_build_job(db, "sample-independent", "a" * 40, second_id)
        assert not claimed and second.state == "queued" and second.failure_code == "build_capacity"
        first = db.get(AppBuildJob, first_id)
        first.state, first.active_slot = "failed", None
        db.commit()
        _, claimed = start_build_job(db, "sample-independent", "a" * 40, second_id)
        assert claimed


def test_four_preview_admission_and_uncertain_cleanup_keep_capacity(client, delivery_app):
    _, headers, definition, installation, data = delivery_app
    release = build_release(definition)
    runtime = FakeRuntime()
    for index in range(5):
        if index:
            response = client.post(
                "/api/v1/independent-apps/sample-independent/installations",
                headers=headers,
                json=data | {"origin": f"https://sample{index}.test"},
            )
            assert response.status_code == 201, response.text
            installation = response.json()
        request, _ = enqueue(client, delivery_app, release, installation=installation)
        result = execute(request, runtime)
        if index < 4:
            assert result.state == "succeeded"
        else:
            assert result.state == "queued" and result.failure_code == "preview_capacity"
    with get_session_factory()() as db:
        assert len(db.scalars(select(AppRuntimeSlot)).all()) == 4


def test_cleanup_failure_keeps_slot_and_reconciles_after_switch(client, delivery_app):
    runtime = FakeRuntime()
    release = build_release(delivery_app[2])
    first, _ = enqueue(client, delivery_app, release)
    assert execute(first, runtime).state == "succeeded"
    second, _ = enqueue(
        client, delivery_app, release, installation=current_installation(first["installation_id"])
    )
    normal_retire = runtime.retire
    runtime.retire = lambda spec: (_ for _ in ()).throw(RuntimeFailure("daemon_unavailable"))
    assert execute(second, runtime).state == "unknown"
    with get_session_factory()() as db:
        assert db.get(AppDeploymentRequest, second["request_id"]).active_slot == 1
        assert (
            db.get(AppInstallationRecord, first["installation_id"]).runtime_ref
            == second["request_id"]
        )
    runtime.retire = normal_retire
    with get_session_factory()() as db:
        assert reconcile_deployment(db, second["request_id"], runtime).state == "succeeded"
    assert len(runtime.activations) == 2


def test_installed_verification_revocation_denies_launch_but_owner_can_replace(
    client, delivery_app
):
    from miy_api.domains.auth.models import utcnow_naive

    release = build_release(delivery_app[2])
    runtime = FakeRuntime()
    first, _ = enqueue(client, delivery_app, release)
    assert execute(first, runtime).state == "succeeded"
    with get_session_factory()() as db:
        proof = db.scalar(select(AppBuildVerification))
        proof.revoked_at = utcnow_naive()
        db.commit()
    response = client.post(
        "/api/v1/independent-apps/launch",
        headers=delivery_app[1],
        json={"installation_id": first["installation_id"], "code_challenge": "a" * 43},
    )
    # Launch conceals non-admitted installations using its existing 404 contract.
    assert response.status_code == 404
    replacement = build_release(delivery_app[2], "b")
    request, _ = enqueue(
        client,
        delivery_app,
        replacement,
        installation=current_installation(first["installation_id"]),
    )
    assert execute(request, runtime).state == "succeeded"


def test_process_loss_before_first_activation_can_reconcile_definitive_absence(
    client, delivery_app
):
    release = build_release(delivery_app[2])
    request, _ = enqueue(client, delivery_app, release)
    runtime = FakeRuntime()
    runtime.prepare_hook = lambda: (_ for _ in ()).throw(RuntimeError("synthetic process loss"))
    with pytest.raises(RuntimeError):
        execute(request, runtime)
    runtime.observe = lambda spec: Observation(
        False, False, spec.image_id, True, ingress_absent=True
    )
    with get_session_factory()() as db:
        assert db.get(AppDeploymentRequest, request["request_id"]).state == "running"
        result = reconcile_deployment(db, request["request_id"], runtime)
        assert result.state == "failed" and result.failure_code == "activation_not_started"
        assert db.get(AppRuntimeSlot, request["installation_id"]) is None
