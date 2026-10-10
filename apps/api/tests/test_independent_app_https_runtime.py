"""Opt-in real Docker ingress behind a synthetic, certificate-verified TLS origin.

No live platform, public DNS, image pulls, or changes to production certificate
trust are involved. Both bound environments reuse one locally built artifact.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from miy_api.domains.independent_apps.builds import build_app
from miy_api.domains.independent_apps import local_runtime
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from test_independent_app_runtime import INGRESS, ROOT, TOOLCHAIN, spec


pytestmark = pytest.mark.skipif(
    os.getenv("MIY_TEST_INDEPENDENT_DOCKER") != "1",
    reason="Opt-in synthetic certificate-verified HTTPS Docker runtime test",
)


@pytest.fixture(scope="module")
def https_artifact():
    (ROOT / ".runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="independent-https-runtime-", dir=ROOT / ".runtime"
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
            assert result.returncode == 0, "Synthetic HTTPS command failed: " + args[0]
            return result.stdout.decode().strip()

        for image in (TOOLCHAIN, INGRESS):
            assert command("docker", "image", "inspect", image, "--format", "{{.Id}}") == image

        # OpenSSL only creates disposable test certificates. stdlib SSLContext
        # performs the TLS handshake, CA validation, and hostname validation.
        command(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-days",
            "1",
            "-subj",
            "/CN=MIY synthetic runtime CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            str(work / "ca.key"),
            "-out",
            str(work / "ca.pem"),
        )
        command(
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(work / "server.key"),
            "-out",
            str(work / "server.csr"),
        )
        (work / "server.ext").write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n"
        )
        command(
            "openssl",
            "x509",
            "-req",
            "-in",
            str(work / "server.csr"),
            "-CA",
            str(work / "ca.pem"),
            "-CAkey",
            str(work / "ca.key"),
            "-set_serial",
            "1",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(work / "server.ext"),
            "-out",
            str(work / "server.pem"),
        )
        for key in (work / "ca.key", work / "server.key"):
            key.chmod(0o600)
        trust = ssl.create_default_context(cafile=str(work / "ca.pem"))
        assert trust.check_hostname and trust.verify_mode == ssl.CERT_REQUIRED

        loader = importlib.util.spec_from_file_location(
            "https_app_env", ROOT / "scripts/independent-app-env.py"
        )
        module = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        source = work / "app"
        repository = "https://example.test/runtime-fixture.git"
        module.scaffold(
            source, app_id="runtime-fixture", name="HTTPS runtime fixture", repository=repository
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
            "user.name=HTTPS runtime fixture",
            "-c",
            "user.email=https-runtime@example.test",
            "-C",
            str(source),
        )
        command(*git, "init")
        command(*git, "remote", "add", "origin", repository)
        command(*git, "add", ".")
        command(*git, "commit", "-m", "Synthetic HTTPS runtime fixture")
        evidence = build_app(
            source=source,
            revision=command(*git, "rev-parse", "HEAD"),
            expected_definition=json.loads((source / "app.manifest.json").read_text()),
            toolchain_image=TOOLCHAIN,
            work_root=work,
        )
        assert evidence.artifact_digest not in {TOOLCHAIN, INGRESS}
        try:
            yield SimpleNamespace(
                work=work, command=command, image=evidence.artifact_digest, trust=trust
            )
        finally:
            command("docker", "image", "rm", evidence.artifact_digest)


@pytest.mark.parametrize("environment", ["development", "production"])
def test_real_bound_https_marker_health_replacement_and_rollback(
    https_artifact, monkeypatch, environment
):
    fixture = https_artifact
    installation = str(uuid4())
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        loopback_port = listener.getsockname()[1]
    forwarded = []

    class TLSFrontDoor(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path not in {"/__miy_release", "/healthz"}:
                self.send_error(404)
                return
            try:
                # Forward only these synthetic probes to the fixed Docker
                # loopback listener, without proxy environment or redirects.
                with closing(HTTPConnection("127.0.0.1", loopback_port, timeout=2)) as upstream:
                    upstream.request("GET", self.path, headers={"Accept-Encoding": "identity"})
                    response = upstream.getresponse()
                    body = response.read(65537)
                    if len(body) > 65536:
                        self.send_error(502)
                        return
                    forwarded.append(self.path)
                    self.send_response(response.status)
                    self.send_header(
                        "Content-Type",
                        response.getheader("Content-Type", "application/octet-stream"),
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except OSError:
                self.send_error(502)

    front = ThreadingHTTPServer(("127.0.0.1", 0), TLSFrontDoor)
    front.timeout = 2
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(fixture.work / "server.pem", fixture.work / "server.key")
    front.socket = server_tls.wrap_socket(front.socket, server_side=True)
    thread = Thread(target=lambda: front.serve_forever(poll_interval=0.05), daemon=True)
    thread.start()
    origin = f"https://localhost:{front.server_port}"
    binding = hashlib.sha256(f"{environment}:{origin}:{loopback_port}".encode()).hexdigest()
    label = "miy.independent-installation=" + installation

    class VerifiedTestClient(httpx.AsyncClient):
        def __init__(self, **options):
            assert "verify" not in options and options["trust_env"] is False
            super().__init__(verify=fixture.trust, **options)

    # Scoped replacement only of this runtime module's HTTP client reference:
    # real TLS transport stays enabled and production code remains unchanged.
    monkeypatch.setattr(
        local_runtime,
        "httpx",
        SimpleNamespace(AsyncClient=VerifiedTestClient, HTTPError=httpx.HTTPError),
    )
    try:
        with httpx.Client(timeout=2, trust_env=False) as untrusted:
            with pytest.raises(httpx.ConnectError):
                untrusted.get(origin + "/__miy_release")
        with httpx.Client(verify=fixture.trust, timeout=2, trust_env=False) as wrong_host:
            with pytest.raises(httpx.ConnectError):
                wrong_host.get(f"https://127.0.0.1:{front.server_port}/__miy_release")
        assert not forwarded  # CA and hostname failures cannot reach Docker.

        runtime = DockerRuntime(
            state_root=fixture.work / ("executor-" + environment),
            ingress_image=INGRESS,
            platform_origin="https://localhost:4200",
            app_origin=origin,
            loopback_port=loopback_port,
            operator_binding_digest=binding,
            environment=environment,
        )
        first = spec(
            installation_id=installation,
            image_id=fixture.image,
            origin=origin,
            environment=environment,
            loopback_port=loopback_port,
            operator_binding_digest=binding,
        )

        def assert_live(selected):
            observed = runtime.observe(selected)
            assert observed.active and observed.healthy and observed.image_id == fixture.image
            with httpx.Client(verify=fixture.trust, timeout=5, trust_env=False) as browser:
                marker = browser.get(origin + "/__miy_release")
                assert marker.status_code == 200
                assert marker.json() == {
                    "request_id": selected.request_id,
                    "image_id": fixture.image,
                }
                assert browser.get(origin + "/healthz").status_code == 200

        runtime.prepare(first)
        runtime.activate(first)
        assert_live(first)
        proxy = runtime._proxy(first)
        assert proxy["HostConfig"]["PortBindings"] == {
            "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(loopback_port)}]
        }
        # Distinct intents select the same retained immutable artifact; another
        # app build is unnecessary to prove ingress replacement and rollback.
        second = replace(first, request_id=str(uuid4()))
        runtime.prepare(second)
        runtime.activate(second)
        assert_live(second)
        assert not runtime.observe(first).active
        runtime.retire(first)
        assert runtime._container(first) is None

        runtime.prepare(first)
        runtime.activate(first)
        assert_live(first)
        assert not runtime.observe(second).active
        runtime.retire(second)
        assert runtime._container(second) is None
        assert {"/__miy_release", "/healthz"} <= set(forwarded)
    finally:
        front.shutdown()
        front.server_close()
        thread.join(timeout=2)
        failures = []
        if thread.is_alive():
            failures.append("TLS listener")
        for kind, list_args, remove_args in (
            ("container", ("ps", "-aq"), ("rm", "--force")),
            ("network", ("network", "ls", "-q"), ("network", "rm")),
        ):
            try:
                identifiers = fixture.command(
                    "docker", *list_args, "--filter", "label=" + label
                ).splitlines()
            except (AssertionError, OSError, subprocess.SubprocessError):
                failures.append(kind)
                continue
            for identifier in identifiers:
                try:
                    fixture.command("docker", *remove_args, identifier)
                except (AssertionError, OSError, subprocess.SubprocessError):
                    failures.append(kind)
        assert not failures, "Synthetic HTTPS cleanup requires inspection: " + ",".join(failures)
