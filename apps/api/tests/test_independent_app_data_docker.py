"""Actual notes container -> restricted proxy -> core session -> isolated PG data."""

from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Thread
from uuid import uuid4

import httpx
import pytest

from miy_api.core.db import get_session_factory
from miy_api.core.settings import get_settings
from miy_api.domains.independent_apps.builds import build_app
from miy_api.domains.independent_apps.data_api import get_store
from miy_api.domains.independent_apps.delivery import (
    execute_deployment,
    persist_verified_build,
    start_build_job,
)
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from miy_api.domains.independent_apps.models import AppInstallationRecord
from test_independent_app_data import (
    data_store as data_store,
    isolated_data_cluster as isolated_data_cluster,
)
from test_independent_app_runtime import INGRESS, ROOT, TOOLCHAIN
from test_organization_integrations import _auth_headers, _bootstrap_admin


@pytest.mark.skipif(
    os.getenv("MIY_TEST_INDEPENDENT_DOCKER") != "1",
    reason="Opt-in synthetic full data app Docker delivery",
)
def test_actual_data_app_proxy_auth_storage_and_code_rollback(client, monkeypatch, data_store):
    platform_origin = "http://127.0.0.1:4200"
    monkeypatch.setenv("MIY_INDEPENDENT_APP_PLATFORM_ORIGINS", json.dumps([platform_origin]))
    get_settings.cache_clear()
    admin = _bootstrap_admin(client)
    headers = _auth_headers(admin["token"])
    prefix, app_id = "/api/v1/independent-apps", "data-runtime-fixture"
    client.app.dependency_overrides[get_store] = lambda: data_store
    with tempfile.TemporaryDirectory(
        prefix="independent-data-delivery-", dir=ROOT / ".runtime"
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

        # Only the local Docker bridge can reach this synthetic core API relay.
        bridge = json.loads(command("docker", "network", "inspect", "bridge"))[0]["IPAM"]["Config"][
            0
        ]["Gateway"]

        class Relay(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def forward(self):
                if not self.path.startswith(prefix + "/"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length > 20 * 1024:
                    self.send_error(413)
                    return
                response = client.request(
                    self.command,
                    self.path,
                    headers={
                        key: value
                        for key, value in self.headers.items()
                        if key.lower() in {"authorization", "origin", "content-type"}
                    },
                    content=self.rfile.read(length),
                )
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)

            do_GET = forward
            do_POST = forward
            do_PUT = forward
            do_DELETE = forward

        relay = ThreadingHTTPServer((bridge, 0), Relay)
        thread = Thread(target=relay.serve_forever, daemon=True)
        thread.start()
        loader = importlib.util.spec_from_file_location(
            "data_app_env", ROOT / "scripts/independent-app-env.py"
        )
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        source = work / "app"
        repository = "https://example.test/data-runtime-fixture.git"
        module.scaffold(
            source,
            app_id=app_id,
            name="Data fixture",
            repository=repository,
            template="private-notes",
        )
        git = (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Data fixture",
            "-c",
            "user.email=data@example.test",
            "-C",
            str(source),
        )
        command(*git, "init")
        command(*git, "remote", "add", "origin", repository)
        definition = None
        images = set()
        installation_id = None
        try:

            def build(version):
                nonlocal definition
                html = source / "index.html"
                html.write_text(
                    html.read_text().replace("</head>", f"<!-- version-{version} --></head>")
                )
                command(*git, "add", ".")
                command(*git, "commit", "-m", "Synthetic data version " + version)
                revision = command(*git, "rev-parse", "HEAD")
                manifest = json.loads((source / "app.manifest.json").read_text())
                payload = {"definition": manifest, "source_revision": revision}
                if definition:
                    payload |= {
                        "expected_digest": definition["definition_digest"],
                        "expected_source_revision": definition["source_revision"],
                    }
                registered = client.put(prefix + "/definitions", headers=headers, json=payload)
                assert registered.status_code == 200, registered.text
                definition = registered.json()
                with get_session_factory()() as db:
                    job, claimed = start_build_job(db, app_id, revision, str(uuid4()))
                    assert claimed
                    proof = build_app(
                        source=source,
                        revision=revision,
                        expected_definition=manifest,
                        toolchain_image=TOOLCHAIN,
                        work_root=work,
                        build_id=job.id,
                    )
                    images.add(proof.artifact_digest)
                    return persist_verified_build(db, job, proof).id

            first = build("one")
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            created = client.post(
                prefix + f"/{app_id}/installations",
                headers=headers,
                json={
                    "environment": "development",
                    "origin": origin,
                    "enabled": True,
                    "user_ids": [admin["user"]["id"]],
                    "granted_permissions": ["identity:read", "data:read", "data:write"],
                },
            )
            assert created.status_code == 201, created.text
            installation_id = created.json()["id"]
            runtime = DockerRuntime(
                state_root=work / "executor",
                ingress_image=INGRESS,
                platform_origin=platform_origin,
                platform_api_origin=f"http://127.0.0.1:{relay.server_port}",
                data_store=data_store,
            )

            def deploy(release_id, action="deploy"):
                with get_session_factory()() as db:
                    current = db.get(AppInstallationRecord, installation_id)
                    payload = {
                        "request_id": str(uuid4()),
                        "installation_id": installation_id,
                        "release_id": release_id,
                        "action": action,
                        "expected_generation": current.generation,
                        "expected_release_id": current.release_id,
                    }
                accepted = client.post(
                    prefix + f"/{app_id}/deployments", headers=headers, json=payload
                )
                assert accepted.status_code == 202, accepted.text
                with get_session_factory()() as db:
                    result = execute_deployment(db, payload["request_id"], runtime)
                    assert result.state == "succeeded", result.failure_code

            def app_token(browser):
                verifier = "v" * 43
                challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                    .decode()
                    .rstrip("=")
                )
                code = client.post(
                    prefix + "/launch",
                    headers=headers,
                    json={
                        "installation_id": installation_id,
                        "code_challenge": challenge,
                    },
                )
                assert code.status_code == 200, code.text
                exchanged = browser.post(
                    "/api/session/exchange",
                    headers={"Origin": origin},
                    json={
                        "installation_id": installation_id,
                        "code": code.json()["code"],
                        "code_verifier": verifier,
                    },
                )
                assert exchanged.status_code == 200, exchanged.text
                return {"Authorization": "Bearer " + exchanged.json()["token"]}

            deploy(first)
            with httpx.Client(base_url=origin, timeout=10, trust_env=False) as browser:
                assert "version-one" in browser.get("/").text
                token = app_token(browser)
                created = browser.post(
                    "/api/notes", headers=token, json={"text": "개발 앱의 개인 메모"}
                )
                assert created.status_code == 201, created.text
                record_id = created.json()["id"]
                second = build("two")
                deploy(second)
                assert browser.get("/api/notes", headers=token).status_code == 401
                token = app_token(browser)
                assert (
                    browser.get("/api/notes", headers=token).json()["items"][0]["id"] == record_id
                )
                deploy(first, "rollback")
                token = app_token(browser)
                assert "version-two" not in browser.get("/").text
                restored = browser.get("/api/notes", headers=token)
                assert restored.status_code == 200
                assert restored.json()["items"][0]["payload"]["text"] == "개발 앱의 개인 메모"
            database, migrator, _ = data_store.names(installation_id)
            with data_store._connect(database=database, role=migrator) as conn:
                assert conn.execute("SELECT count(*) FROM miy_data.migrations").fetchone() == (3,)
        finally:
            relay.shutdown()
            relay.server_close()
            thread.join(timeout=5)
            failures = []
            if installation_id:
                label = "miy.independent-installation=" + installation_id
                for listing, removal in (
                    (("ps", "-aq"), ("rm", "--force")),
                    (("network", "ls", "-q"), ("network", "rm")),
                ):
                    try:
                        for identifier in command(
                            "docker", *listing, "--filter", "label=" + label
                        ).splitlines():
                            command("docker", *removal, identifier)
                    except (AssertionError, OSError, subprocess.SubprocessError):
                        failures.append("runtime")
            for image in images:
                try:
                    command("docker", "image", "rm", image)
                except (AssertionError, OSError, subprocess.SubprocessError):
                    failures.append("artifact")
            client.app.dependency_overrides.pop(get_store, None)
            get_settings.cache_clear()
            assert not failures, "Synthetic fixture cleanup needs inspection"
