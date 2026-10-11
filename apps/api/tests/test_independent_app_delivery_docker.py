"""Disposable PostgreSQL + real immutable Docker delivery, recovery and rollback."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps.builds import build_app
from miy_api.domains.independent_apps.delivery import (
    RuntimeFailure,
    RuntimeSpec,
    execute_deployment,
    persist_verified_build,
    reconcile_deployment,
    start_build_job,
)
from miy_api.domains.independent_apps.delivery_models import AppDeploymentRequest
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from miy_api.domains.independent_apps.models import AppInstallationRecord, AppReleaseRecord
from test_independent_app_runtime import INGRESS, ROOT, TOOLCHAIN
from test_organization_integrations import _auth_headers, _bootstrap_admin


@pytest.mark.skipif(
    os.getenv("MIY_TEST_INDEPENDENT_DOCKER") != "1",
    reason="Opt-in synthetic local Docker + PostgreSQL delivery test",
)
def test_real_verified_deploy_response_loss_reconciliation_and_artifact_rollback(
    client, monkeypatch
):
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", '["http://127.0.0.1:4200"]')
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    headers = _auth_headers(admin["token"])
    app_id = "delivery-runtime-fixture"
    prefix = "/api/v1/independent-apps"
    (ROOT / ".runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="independent-delivery-test-", dir=ROOT / ".runtime"
    ) as temporary:
        work = Path(temporary)
        docker_config = work / "docker-config"
        docker_config.mkdir(mode=0o700)
        environment = {"PATH": os.defpath, "DOCKER_CONFIG": str(docker_config)}

        def command(*args):
            result = subprocess.run(
                args,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            assert result.returncode == 0, "Synthetic command failed: " + args[0]
            return result.stdout.decode().strip()

        loader = importlib.util.spec_from_file_location(
            "delivery_app_env", ROOT / "scripts/independent-app-env.py"
        )
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        source = work / "app"
        repository = "https://example.test/delivery-runtime-fixture.git"
        module.scaffold(source, app_id=app_id, name="Delivery fixture", repository=repository)
        git = (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Delivery fixture",
            "-c",
            "user.email=delivery@example.test",
            "-C",
            str(source),
        )
        command(*git, "init")
        command(*git, "remote", "add", "origin", repository)
        definition = None
        images = set()
        installation_id = None
        delegated_headers = None
        try:

            def build(version):
                nonlocal definition, delegated_headers
                html = source / "index.html"
                html.write_text(
                    html.read_text().replace("</head>", f"<!-- version-{version} --></head>")
                )
                command(*git, "add", ".")
                command(*git, "commit", "-m", "Synthetic delivery version " + version)
                revision = command(*git, "rev-parse", "HEAD")
                manifest = json.loads((source / "app.manifest.json").read_text())
                request = {"definition": manifest, "source_revision": revision}
                if definition:
                    request |= {
                        "expected_digest": definition["definition_digest"],
                        "expected_source_revision": definition["source_revision"],
                    }
                response = client.put(prefix + "/definitions", headers=headers, json=request)
                assert response.status_code == 200, response.text
                definition = response.json()
                if installation_id:
                    base = prefix + f"/delegated/{app_id}/installations/{installation_id}"
                    issued = client.post(
                        prefix + f"/{app_id}/installations/{installation_id}/delegations",
                        headers=headers,
                        json={"actions": ["read", "build", "deploy", "rollback"]},
                    )
                    assert issued.status_code == 201
                    delegated_headers = {"Authorization": "Bearer " + issued.json()["token"]}
                    build_id = str(uuid4())
                    queued = client.post(
                        base + "/builds",
                        headers=delegated_headers,
                        json={
                            "request_id": build_id,
                            "source_revision": revision,
                            "definition_digest": definition["definition_digest"],
                        },
                    )
                    assert queued.status_code == 202, queued.text
                    cli_loader = importlib.util.spec_from_file_location(
                        "delivery_cli", ROOT / "scripts/independent-app-delivery.py"
                    )
                    cli = importlib.util.module_from_spec(cli_loader)
                    cli_loader.loader.exec_module(cli)
                    monkeypatch.chdir(ROOT)
                    result = cli.run(
                        cli.parser().parse_args(
                            [
                                "build-request",
                                "--app-id",
                                app_id,
                                "--installation-id",
                                installation_id,
                                "--build-id",
                                build_id,
                                "--source",
                                str(source),
                                "--work-root",
                                str(work),
                                "--toolchain-image",
                                TOOLCHAIN,
                            ]
                        )
                    )
                    assert result["state"] == "succeeded", result
                    status = client.get(base + "/builds/" + build_id, headers=delegated_headers)
                    assert (
                        status.status_code == 200
                        and status.json()["release_id"] == result["release_id"]
                    )
                    with get_session_factory()() as db:
                        release = db.get(AppReleaseRecord, result["release_id"])
                        images.add(release.artifact)
                        return release.id, SimpleNamespace(artifact_digest=release.artifact)
                with get_session_factory()() as db:
                    job, claimed = start_build_job(db, app_id, revision, str(uuid4()))
                    assert claimed
                    evidence = build_app(
                        source=source,
                        revision=revision,
                        expected_definition=manifest,
                        toolchain_image=TOOLCHAIN,
                        work_root=work,
                        build_id=job.id,
                    )
                    images.add(evidence.artifact_digest)
                    release = persist_verified_build(db, job, evidence)
                    return release.id, evidence

            first_release, first_evidence = build("one")
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            origin = f"http://127.0.0.1:{port}"
            response = client.post(
                prefix + f"/{app_id}/installations",
                headers=headers,
                json={
                    "environment": "development",
                    "origin": origin,
                    "enabled": True,
                    "user_ids": [admin["user"]["id"]],
                    "granted_permissions": ["identity:read"],
                },
            )
            assert response.status_code == 201, response.text
            installation_id = response.json()["id"]
            runtime = DockerRuntime(
                state_root=work / "executor",
                ingress_image=INGRESS,
                platform_origin="http://127.0.0.1:4200",
            )

            def enqueue(release_id, action="deploy"):
                with get_session_factory()() as db:
                    installed = db.get(AppInstallationRecord, installation_id)
                    payload = {
                        "request_id": str(uuid4()),
                        "installation_id": installation_id,
                        "release_id": release_id,
                        "action": action,
                        "expected_generation": installed.generation,
                        "expected_release_id": installed.release_id,
                    }
                response = client.post(
                    (
                        prefix + f"/delegated/{app_id}/installations/{installation_id}/deployments"
                        if delegated_headers
                        else prefix + f"/{app_id}/deployments"
                    ),
                    headers=delegated_headers or headers,
                    json=payload,
                )
                assert response.status_code == 202, response.text
                return payload["request_id"]

            def execute(request_id):
                with get_session_factory()() as db:
                    return execute_deployment(db, request_id, runtime)

            first_request = enqueue(first_release)
            assert execute(first_request).state == "succeeded"
            with httpx.Client(base_url=origin, timeout=5, trust_env=False) as browser:
                assert "version-one" in browser.get("/").text
                second_release, second_evidence = build("two")
                assert second_evidence.artifact_digest != first_evidence.artifact_digest
                second_request = enqueue(second_release)
                real_activate = runtime.activate
                activations = []

                def lose_response(spec):
                    real_activate(spec)
                    activations.append(spec.request_id)
                    raise RuntimeFailure("synthetic_response_lost")

                monkeypatch.setattr(runtime, "activate", lose_response)
                assert execute(second_request).state == "unknown"
                status = client.get(
                    prefix + f"/{app_id}/deployments/{second_request}", headers=headers
                )
                assert status.status_code == 200 and status.json()["state"] == "unknown"
                assert execute(second_request).state == "unknown"
                assert activations == [second_request]
                assert "version-two" in browser.get("/").text
                with get_session_factory()() as db:
                    confirmed = reconcile_deployment(db, second_request, runtime)
                    assert confirmed.state == "succeeded"
                    assert confirmed.observed_image_id == second_evidence.artifact_digest
                    assert db.get(AppDeploymentRequest, second_request).active_slot is None
                monkeypatch.setattr(runtime, "activate", real_activate)
                rollback = enqueue(first_release, "rollback")
                restored = execute(rollback)
                assert restored.state == "succeeded"
                assert restored.observed_image_id == first_evidence.artifact_digest
                html = browser.get("/").text
                assert "version-one" in html and "version-two" not in html
                with get_session_factory()() as db:
                    for previous in (first_request, second_request):
                        record = db.get(AppDeploymentRequest, previous)
                        assert runtime._container(RuntimeSpec(**record.runtime_config)) is None
                    current = db.get(AppInstallationRecord, installation_id)
                    assert current.release_id == first_release and current.runtime_ref == rollback
        finally:
            failures = []
            if installation_id:
                label = "miy.independent-installation=" + installation_id
                for kind, listing, removal in (
                    ("container", ("ps", "-aq"), ("rm", "--force")),
                    ("network", ("network", "ls", "-q"), ("network", "rm")),
                ):
                    try:
                        for identifier in command(
                            "docker", *listing, "--filter", "label=" + label
                        ).splitlines():
                            command("docker", *removal, identifier)
                    except (AssertionError, OSError, subprocess.SubprocessError):
                        failures.append(kind)
            for image in images:
                try:
                    command("docker", "image", "rm", image)
                except (AssertionError, OSError, subprocess.SubprocessError):
                    failures.append("artifact")
            get_settings.cache_clear()
            assert not failures, "Owned synthetic cleanup requires inspection: " + ",".join(
                failures
            )
