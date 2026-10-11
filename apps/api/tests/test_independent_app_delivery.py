from __future__ import annotations

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


@pytest.mark.parametrize("revocation", ["source_session"])
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
