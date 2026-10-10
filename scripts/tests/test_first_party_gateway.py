"""Fixed ingress ownership, trusted headers and opt-in native NGINX proof."""

from __future__ import annotations

import base64
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
NGINX = "sha256:6769dc3a703c719c1d2756bda113659be28ae16cf0da58dd5fd823d6b9a050ea"
module_spec = importlib.util.spec_from_file_location(
    "first_party_gateway", ROOT / "ops/first-party/gateway.py"
)
gateway = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = gateway
module_spec.loader.exec_module(gateway)


@pytest.fixture(scope="module")
def isolated_api_wheel(tmp_path_factory):
    directory = tmp_path_factory.mktemp("gateway-api-wheel")
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(directory),
            "--directory",
            str(ROOT / "apps/api"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (wheel,) = directory.glob("miy_api-*.whl")
    site = directory / "site"
    with zipfile.ZipFile(wheel) as archive:
        assert "miy_api/core/first_party_routes.generated.json" in archive.namelist()
        assert all(
            not Path(name).is_absolute() and ".." not in Path(name).parts
            for name in archive.namelist()
        )
        archive.extractall(site)
    cwd = directory / "cwd"
    cwd.mkdir()
    assert all(not (ancestor / ".env").exists() for ancestor in (cwd, *cwd.parents))
    return site, cwd


def native_configuration(isolated_api_wheel, settings):
    site, cwd = isolated_api_wheel
    # Use the actual matching API wheel and pinned API interpreter/dependencies.
    # The private package path wins over the editable source checkout, and no
    # project/env-file ancestor or application setting is supplied to this process.
    program = """
import os, pathlib, runpy, sys
import miy_api
assert {key for key in os.environ if key.startswith('MIY_')} == {
    'MIY_APP_BIND_HOST', 'MIY_APP_PORT', 'MIY_API_PREFIX', 'MIY_APP_FORWARDED_ALLOW_IPS'
}
assert pathlib.Path(miy_api.__file__).parent == pathlib.Path(sys.argv[1]) / 'miy_api'
entry = sys.argv[2]
sys.argv = [entry, '--print-config']
runpy.run_path(entry, run_name='__main__')
assert not any(name in sys.modules for name in ('miy_api.core.settings', 'miy_api.app', 'miy_api.api_registry'))
assert not any(name.startswith('miy_api.domains.') for name in sys.modules)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(site),
            str(ROOT / "ops/first-party/gateway.py"),
        ],
        cwd=cwd,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONPATH": str(site),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MIY_APP_BIND_HOST": settings.host,
            "MIY_APP_PORT": str(settings.port),
            "MIY_API_PREFIX": settings.api_prefix,
            "MIY_APP_FORWARDED_ALLOW_IPS": ",".join(settings.proxies),
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    return result.stdout


@pytest.fixture
def settings(monkeypatch):
    for key, value in {
        "MIY_APP_BIND_HOST": "127.0.0.1",
        "MIY_APP_PORT": "19499",
        "MIY_API_PREFIX": "/api/v1",
        "MIY_APP_FORWARDED_ALLOW_IPS": "127.0.0.1,::1",
    }.items():
        monkeypatch.setenv(key, value)
    return gateway.GatewaySettings.from_environment()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MIY_APP_BIND_HOST", "*"),
        ("MIY_APP_BIND_HOST", "example.com"),
        ("MIY_APP_PORT", "8000; include /secrets"),
        ("MIY_APP_PORT", "65536"),
        ("MIY_APP_PORT", "18779"),
        ("MIY_APP_PORT", "18780"),
        ("MIY_API_PREFIX", '/api/v1"; invalid'),
        ("MIY_API_PREFIX", "/api/v1/"),
        ("MIY_APP_FORWARDED_ALLOW_IPS", "*"),
        ("MIY_APP_FORWARDED_ALLOW_IPS", "127.0.0.0/8"),
        ("MIY_APP_FORWARDED_ALLOW_IPS", "localhost"),
        ("MIY_APP_FORWARDED_ALLOW_IPS", "127.0.0.1; include /secrets"),
    ],
)
def test_gateway_rejects_untrusted_or_injectable_configuration(settings, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        gateway.GatewaySettings.from_environment()


def test_render_uses_actual_owner_projection_and_preserves_native_boundaries(settings):
    from miy_api.first_party_routes import nginx_client_owner_map, nginx_owner_map

    configuration = gateway.render(settings, directory=Path("/tmp/synthetic-gateway"))
    assert nginx_owner_map(api_prefix=settings.api_prefix) in configuration
    assert nginx_client_owner_map() in configuration
    assert "geo $realip_remote_addr $miy_trusted_proxy" in configuration
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in configuration
    assert 'proxy_set_header Forwarded "";' in configuration
    assert "proxy_next_upstream off;" in configuration
    assert "proxy_request_buffering off;" in configuration
    assert "proxy_buffering off;" in configuration
    assert "proxy_set_header Host $http_host;" in configuration
    assert "127.0.0.1:18779" in configuration and "127.0.0.1:18780" in configuration


def test_gateway_wheel_prints_configuration_without_application_settings(
    settings, isolated_api_wheel
):
    configuration = native_configuration(isolated_api_wheel, settings)
    assert "map $uri $miy_api_owner" in configuration
    assert "map $uri $miy_ui_owner" in configuration
    assert "listen 127.0.0.1:19499;" in configuration
    assert "127.0.0.1:18779" in configuration and "127.0.0.1:18780" in configuration


def test_default_gateway_writes_private_config_before_native_exec(settings, monkeypatch):
    captured = []

    def observe_exec(executable, arguments):
        assert executable == "/usr/sbin/nginx"
        assert arguments[:2] == ["nginx", "-c"]
        assert arguments[3:] == ["-g", "daemon off;"]
        path = Path(arguments[2])
        captured.append(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        configuration = path.read_text()
        assert "map $uri $miy_api_owner" in configuration
        assert "listen 127.0.0.1:19499;" in configuration

    monkeypatch.setattr(sys, "argv", ["gateway.py"])
    monkeypatch.setattr(gateway.os, "execv", observe_exec)
    try:
        gateway.main()
        assert len(captured) == 1
    finally:
        for path in captured:
            assert path.parent.name.startswith("miy-first-party-gateway-")
            shutil.rmtree(path.parent)


def test_health_probes_only_gateway_fixed_local_paths(settings, monkeypatch):
    probes = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", settings.port, 3)

        def request(self, method, path):
            probes.append((method, path))

        def getresponse(self):
            return self

        status = 200

        def read(self, limit):
            assert limit == 4097

        def close(self):
            pass

    monkeypatch.setattr(gateway.http.client, "HTTPConnection", Connection)
    gateway.check(settings)
    assert probes == [
        ("GET", path)
        for path in (
            "/healthz",
            "/readyz",
            "/official-suite/healthz",
            "/official-suite/readyz",
        )
    ]
    Connection.status = 302
    with pytest.raises(ValueError, match="gateway_health_failed"):
        gateway.check(settings)


@pytest.mark.skipif(
    os.environ.get("MIY_TEST_INDEPENDENT_DOCKER") != "1",
    reason="Explicit local Docker opt-in required",
)
def test_actual_nginx_routes_sanitizes_headers_streams_and_tunnels_websocket(
    settings, isolated_api_wheel
):
    subprocess.run(["docker", "image", "inspect", NGINX], check=True, capture_output=True)
    release_stream = Event()
    servers = []
    name = "miy-first-party-gateway-test-" + uuid4().hex
    native_process = None

    def handler(owner):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.headers.get("Upgrade", "").lower() == "websocket":
                    assert self.headers.get("Connection", "").lower() == "upgrade"
                    key = self.headers["Sec-WebSocket-Key"]
                    accept = base64.b64encode(
                        hashlib.sha1(
                            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                        ).digest()
                    ).decode()
                    self.send_response(101)
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Sec-WebSocket-Accept", accept)
                    self.end_headers()
                    payload = owner.encode()
                    self.wfile.write(bytes((0x81, len(payload))) + payload)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if self.path == "/synthetic-stream":
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"a")
                    self.wfile.flush()
                    release_stream.wait(5)
                    self.wfile.write(b"b")
                    return
                payload = json.dumps(
                    {"owner": owner, "path": self.path, "headers": dict(self.headers)}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler

    try:
        for owner in ("platform", "official"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(owner))
            Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        native = gateway.GatewaySettings("127.0.0.1", port, "/api/v1", ("127.0.0.1",))
        configuration = native_configuration(isolated_api_wheel, native)
        # --print-config uses the same private-directory renderer as startup.
        # The immutable NGINX tool's rootless tmpfs must own that directory too.
        private_directory = configuration.split("pid ", 1)[1].split("/nginx.pid;", 1)[0]
        assert private_directory.startswith("/tmp/miy-first-party-gateway-")
        assert len(Path(private_directory).parts) == 3
        assert all(character.isalnum() or character in "_-/" for character in private_directory)
        # Synthetic upstreams use ephemeral ports. The product has no target override.
        configuration = configuration.replace(
            gateway.PLATFORM, f"127.0.0.1:{servers[0].server_port}"
        ).replace(gateway.OFFICIAL, f"127.0.0.1:{servers[1].server_port}")
        native_process = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--name",
                name,
                "--network",
                "host",
                "--user",
                "10001:10001",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,mode=1777",
                "--entrypoint",
                "/bin/sh",
                NGINX,
                "-c",
                f"umask 077; mkdir -p {private_directory}; cat > /tmp/nginx.conf; exec nginx -c /tmp/nginx.conf -g 'daemon off;'",
            ],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        native_process.stdin.write(configuration)
        native_process.stdin.close()
        native_process.stdin = None

        def observe(path, *, peer="127.0.0.1", headers=None):
            connection = http.client.HTTPConnection(
                "127.0.0.1", port, timeout=3, source_address=(peer, 0)
            )
            try:
                connection.request(
                    "GET",
                    path,
                    headers={"Host": "portal.example.test:443", **(headers or {})},
                )
                response = connection.getresponse()
                assert response.status == 200
                return json.loads(response.read())
            finally:
                connection.close()

        for attempt in range(300):
            if native_process.poll() is not None:
                pytest.fail("Synthetic NGINX startup failed: " + native_process.stderr.read(2048))
            try:
                observe("/healthz")
                break
            except OSError:
                if attempt == 299:
                    logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                    process = subprocess.run(
                        ["docker", "top", name], capture_output=True, text=True
                    )
                    pytest.fail(
                        "Synthetic NGINX is unavailable: "
                        + logs.stderr[:2048]
                        + process.stdout[:1024]
                    )
                time.sleep(0.1)
        for path, owner in (
            ("/api/v1/auth/me?probe=1", "platform"),
            ("/api/v1/docs/hub?probe=1", "official"),
            ("/official-suite/assets/synthetic.js", "official"),
            ("/apps/docs", "official"),
            ("/official-suite/healthz", "official"),
            ("/official-suite/readyz", "official"),
        ):
            result = observe(path)
            assert result["owner"] == owner
            assert result["headers"]["Host"] == "portal.example.test:443"
        assert observe("/official-suite/readyz")["path"] == "/readyz"
        spoofed = {
            "X-Forwarded-For": "198.51.100.9",
            "X-Forwarded-Proto": "https",
            "Forwarded": "for=198.51.100.9;proto=https",
        }
        trusted = observe("/healthz", headers=spoofed)["headers"]
        assert (
            trusted["X-Forwarded-For"] == "198.51.100.9" and trusted["X-Forwarded-Proto"] == "https"
        )
        assert "Forwarded" not in trusted
        rejected = observe("/healthz", peer="127.0.0.2", headers=spoofed)["headers"]
        assert (
            rejected["X-Forwarded-For"] == "127.0.0.2" and rejected["X-Forwarded-Proto"] == "http"
        )
        assert (
            observe("/healthz", headers={"X-Forwarded-Proto": "https,http"})["headers"][
                "X-Forwarded-Proto"
            ]
            == "http"
        )
        stream = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            stream.request("GET", "/synthetic-stream")
            response = stream.getresponse()
            assert response.read(1) == b"a"
            release_stream.set()
            assert response.read() == b"b"
        finally:
            stream.close()
        for path, owner in (
            ("/api/v1/realtime/ws", "platform"),
            ("/api/v1/docs/collab/pages/synthetic/ws", "official"),
        ):
            with socket.create_connection(("127.0.0.1", port), timeout=3) as websocket:
                websocket.sendall(
                    (
                        f"GET {path} HTTP/1.1\r\nHost: portal.example.test\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: c3ludGhldGljLXRlc3QxMg==\r\n\r\n"
                    ).encode()
                )
                response = websocket.makefile("rb")
                assert b"101" in response.readline()
                while response.readline() != b"\r\n":
                    pass
                assert response.read(2) == bytes((0x81, len(owner)))
                assert response.read(len(owner)) == owner.encode()
    finally:
        release_stream.set()
        subprocess.run(["docker", "rm", "--force", name], capture_output=True)
        if native_process is not None:
            native_process.wait(timeout=10)
        for server in servers:
            server.shutdown()
            server.server_close()
