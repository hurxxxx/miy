"""Opt-in real local Docker proof; never pull images or contact a live platform."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from miy_api.domains.independent_apps.builds import build_app
from miy_api.domains.independent_apps.contracts import Entrypoints
from miy_api.domains.independent_apps.delivery import RuntimeFailure, RuntimeSpec
from miy_api.domains.independent_apps.local_runtime import DockerRuntime


ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN = "sha256:eefe09d5bd59a0b9f30ca40ef251ccc52bd63294969b23f090ef9576df135e52"
INGRESS = "sha256:6769dc3a703c719c1d2756bda113659be28ae16cf0da58dd5fd823d6b9a050ea"


def spec(**changes):
    return replace(
        RuntimeSpec(
            str(uuid4()),
            str(uuid4()),
            "runtime-fixture",
            TOOLCHAIN,
            "http://127.0.0.1:19391",
            "/healthz",
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "origin", ["https://example.test", "http://localhost:19391", "http://127.0.0.1:81"]
)
def test_local_executor_rejects_remote_or_privileged_ingress(origin):
    with pytest.raises(RuntimeFailure, match="local_origin_required"):
        DockerRuntime.port(spec(origin=origin))


def test_core_activation_marker_cannot_be_an_app_health_endpoint():
    for path in ("/__miy_release", "/__miy_release/"):
        with pytest.raises(ValidationError):
            Entrypoints(health=path)
    with pytest.raises(RuntimeFailure, match="immutable_image_required"):
        DockerRuntime.port(spec(image_id="example/app:latest"))


@pytest.mark.parametrize("environment", ["development", "production"])
def test_https_ingress_is_bound_to_environment_origin_listener_and_operator_receipt(
    tmp_path, monkeypatch, environment
):
    monkeypatch.setattr(DockerRuntime, "_run", lambda self, *_: INGRESS)
    runtime = DockerRuntime(
        state_root=tmp_path / "runtime",
        ingress_image=INGRESS,
        platform_origin="https://platform.example.test",
        app_origin="https://app.example.test",
        loopback_port=19431,
        operator_binding_digest="a" * 64,
        environment=environment,
    )
    selected = spec(
        environment=environment,
        origin="https://app.example.test",
        loopback_port=19431,
        operator_binding_digest="a" * 64,
    )
    assert runtime._port(selected) == 19431
    for changed in (
        replace(
            selected, environment="production" if environment == "development" else "development"
        ),
        replace(selected, origin="https://another.example.test"),
        replace(selected, loopback_port=19432),
        replace(selected, operator_binding_digest="b" * 64),
    ):
        with pytest.raises(RuntimeFailure, match="runtime_identity_mismatch"):
            runtime._port(changed)


def test_existing_foreign_image_is_not_reused(monkeypatch):
    runtime = object.__new__(DockerRuntime)
    selected = spec()
    monkeypatch.setattr(
        runtime,
        "_inspect",
        lambda *_: {
            "Image": "sha256:" + "b" * 64,
            "Config": {},
            "HostConfig": {},
        },
    )
    with pytest.raises(RuntimeFailure, match="runtime_identity_mismatch"):
        runtime._container(selected)


@pytest.mark.skipif(
    os.getenv("MIY_TEST_INDEPENDENT_DOCKER") != "1",
    reason="Opt-in synthetic local Docker runtime test",
)
def test_real_runtime_build_activate_replace_retire_and_http_contract():
    (ROOT / ".runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="independent-runtime-test-", dir=ROOT / ".runtime"
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
            assert result.returncode == 0, "Synthetic runtime command failed: " + args[0]
            return result.stdout.decode().strip()

        for image in (TOOLCHAIN, INGRESS):
            assert command("docker", "image", "inspect", image, "--format", "{{.Id}}") == image
        loader = importlib.util.spec_from_file_location(
            "app_env", ROOT / "scripts/independent-app-env.py"
        )
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        source = work / "app"
        module.scaffold(
            source,
            app_id="runtime-fixture",
            name="Runtime fixture",
            repository="https://example.test/runtime-fixture.git",
        )
        prefix = (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Runtime fixture",
            "-c",
            "user.email=runtime@example.test",
            "-C",
            str(source),
        )
        command(*prefix, "init")
        command(*prefix, "remote", "add", "origin", "https://example.test/runtime-fixture.git")
        command(*prefix, "add", ".")
        command(*prefix, "commit", "-m", "Synthetic runtime fixture")
        evidence = build_app(
            source=source,
            revision=command(*prefix, "rev-parse", "HEAD"),
            expected_definition=json.loads((source / "app.manifest.json").read_text()),
            toolchain_image=TOOLCHAIN,
            work_root=work,
        )
        installation = str(uuid4())
        label = "miy.independent-installation=" + installation
        relay = None
        try:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            first = spec(
                installation_id=installation,
                image_id=evidence.artifact_digest,
                origin=f"http://127.0.0.1:{port}",
            )
            # Synthetic transport proof only. Real current auth/ACL is checked in
            # the separate Core selected-file tests, never through this fixture.
            requests = []
            selected_bytes = b"\x00synthetic selected file\xff"

            class SelectedFileCore(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def forward(self):
                    requests.append((self.command, self.path))
                    assert self.headers.get("Authorization") == "Bearer synthetic-app-session"
                    path = urlsplit(self.path)
                    if self.command == "POST" and path.path.endswith("/_files/selection-request"):
                        size = int(self.headers.get("Content-Length", "0"))
                        assert size <= 8192
                        body = json.loads(self.rfile.read(size))
                        assert body["installation_id"] == installation
                        assert body["audience"] == first.origin and body["schema_version"] == 1
                        data = json.dumps(
                            {
                                **body,
                                "selection_request": "synthetic-selection-proof",
                                "expires_at": (
                                    datetime.now(timezone.utc) + timedelta(seconds=60)
                                ).isoformat(),
                                "max_bytes": 10485760,
                            }
                        ).encode()
                        media_type = "application/json"
                    elif self.command == "GET" and path.path.endswith("/_files/content"):
                        assert parse_qs(path.query) == {
                            "installation_id": [installation],
                            "audience": [first.origin],
                        }
                        assert self.headers.get("X-MIY-Selected-File") == "synthetic-read-proof"
                        data, media_type = selected_bytes, "application/octet-stream"
                    else:
                        self.send_error(500)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", media_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                do_GET = forward
                do_POST = forward

            bridge = json.loads(command("docker", "network", "inspect", "bridge"))[0]["IPAM"][
                "Config"
            ][0]["Gateway"]
            relay = ThreadingHTTPServer((bridge, 0), SelectedFileCore)
            relay_thread = Thread(target=relay.serve_forever, daemon=True)
            relay_thread.start()
            runtime = DockerRuntime(
                state_root=work / "executor",
                ingress_image=INGRESS,
                platform_origin="http://127.0.0.1:8001",
                platform_api_origin=f"http://127.0.0.1:{relay.server_port}",
            )
            runtime.prepare(first)
            runtime.activate(first)
            observation = runtime.observe(first)
            assert observation.active and observation.healthy
            assert observation.image_id == evidence.artifact_digest
            with httpx.Client(base_url=first.origin, timeout=5, trust_env=False) as client:
                assert '<div id="root"></div>' in client.get("/").text
                assert client.get("/api/config").json()["app_id"] == "runtime-fixture"
                assert client.get("/api/me").status_code == 401
                assert client.get("/api/platform-files/content").status_code == 401
                headers = {"Authorization": "Bearer synthetic-app-session"}
                proof = client.post(
                    "/api/platform-files/selection-request",
                    headers=headers,
                    json={"schema_version": 1, "selection_id": str(uuid4())},
                )
                assert proof.status_code == 200 and proof.json()["installation_id"] == installation
                content = client.get(
                    "/api/platform-files/content",
                    headers={**headers, "X-MIY-Selected-File": "synthetic-read-proof"},
                )
                assert content.status_code == 200 and content.content == selected_bytes
                assert content.headers["Content-Length"] == str(len(selected_bytes))
                assert content.headers["Content-Type"] == "application/octet-stream"
                assert content.headers["Cache-Control"] == "private, no-store"
            denied = command(
                "docker",
                "exec",
                runtime.names(first)[0],
                "/opt/miy/venvs/api/bin/python",
                "-c",
                "import httpx,json; "
                "paths=[('POST','candidates'),('POST','authorize-selection'),('POST','content'),('GET','selection-request'),('GET','content/')]; "
                "client=httpx.Client(timeout=3,trust_env=False); "
                "print(json.dumps([client.request(m,'http://miy-platform-gateway:8081/api/v1/independent-apps/_files/'+p).status_code for m,p in paths]))",
            )
            assert json.loads(denied) == [404, 404, 405, 405, 404]
            assert len(requests) == 2
            second = replace(first, request_id=str(uuid4()))
            runtime.prepare(second)
            runtime.activate(second)
            assert runtime.observe(second).healthy
            assert not runtime.observe(first).active
            runtime.retire(first)
            assert runtime._container(first) is None
            current = runtime._container(second)
            assert current["HostConfig"]["ReadonlyRootfs"]
            assert current["HostConfig"]["Memory"] == 536870912
            assert current["HostConfig"]["NanoCpus"] == 1000000000
            assert current["HostConfig"]["PidsLimit"] == 256
            assert not current["HostConfig"].get("Binds")
            assert set(current["NetworkSettings"]["Networks"]) == {runtime.names(second)[1]}
            # A retired version can be selected explicitly from the retained image.
            runtime.prepare(first)
            runtime.activate(first)
            assert runtime.observe(first).healthy
            runtime.retire(second)
            assert runtime._container(second) is None
        finally:
            if relay is not None:
                relay.shutdown()
                relay.server_close()
                relay_thread.join(timeout=2)
            failures = []
            for kind, list_args, remove_args in (
                ("container", ("ps", "-aq"), ("rm", "--force")),
                ("network", ("network", "ls", "-q"), ("network", "rm")),
            ):
                try:
                    identifiers = command(
                        "docker", *list_args, "--filter", "label=" + label
                    ).splitlines()
                except (AssertionError, OSError, subprocess.SubprocessError):
                    failures.append(kind)
                    continue
                for identifier in identifiers:
                    try:
                        command("docker", *remove_args, identifier)
                    except (AssertionError, OSError, subprocess.SubprocessError):
                        failures.append(kind)
            try:
                command("docker", "image", "rm", evidence.artifact_digest)
            except (AssertionError, OSError, subprocess.SubprocessError):
                failures.append("artifact")
            assert not failures, "Synthetic runtime cleanup requires inspection: " + ",".join(
                failures
            )
