"""Runtime observation must distinguish absence, foreign objects and daemon loss."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from miy_api.domains.independent_apps.delivery import RuntimeFailure, RuntimeSpec
from miy_api.domains.independent_apps.local_runtime import DockerRuntime


def runtime(monkeypatch, inventory, inspection=None):
    selected = object.__new__(DockerRuntime)
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ("container", "ls", "--all"):
            return "\n".join(json.dumps(row) for row in inventory)
        if isinstance(inspection, Exception):
            raise inspection
        return json.dumps(inspection)

    monkeypatch.setattr(selected, "_run", run)
    return selected, calls


def test_native_key_lookup_ingress_preserves_query_and_blocks_other_methods(tmp_path):
    import os
    import socket
    import subprocess
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    import httpx
    from test_independent_app_runtime import INGRESS

    if os.getenv("MIY_TEST_INDEPENDENT_DOCKER") != "1":
        pytest.skip("Actual local ingress checks require explicit Docker opt-in")

    observed = []

    class Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    def command(*args):
        result = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, "Owned ingress fixture command failed"
        return result.stdout.strip()

    assert command("image", "inspect", INGRESS, "--format", "{{.Id}}") == INGRESS
    with socket.socket() as web, socket.socket() as gateway:
        web.bind(("127.0.0.1", 0))
        gateway.bind(("127.0.0.1", 0))
        web_port, gateway_port = web.getsockname()[1], gateway.getsockname()[1]
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = f"http://127.0.0.1:{upstream.server_port}"
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "data-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile="web-api-postgres-v1",
    )
    app, _, _ = selected.names(spec)
    configuration = (
        selected._configuration(spec)
        .replace("listen 8080;", f"listen 127.0.0.1:{web_port};")
        .replace("listen 8081;", f"listen 127.0.0.1:{gateway_port};")
    )
    config = tmp_path / "nginx.conf"
    config.write_text(configuration)
    config.chmod(0o644)  # Public generated routing only; rootless NGINX must read it.
    name = "miy-key-ingress-test-" + uuid4().hex
    created = False
    try:
        command(
            "create",
            "--name",
            name,
            "--label",
            "miy.test.independent-key-ingress=1",
            "--network",
            "host",
            "--read-only",
            "--user",
            "10001:10001",
            "--memory",
            "64m",
            "--cpus",
            "0.25",
            "--pids-limit",
            "32",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--log-driver",
            "none",
            "--tmpfs",
            "/tmp:rw,size=16m,mode=1777",
            "--add-host",
            "host.docker.internal:127.0.0.1",
            "--add-host",
            app + ":127.0.0.1",
            "--mount",
            f"type=bind,src={config},dst=/etc/nginx/nginx.conf,readonly",
            "--entrypoint",
            "/usr/sbin/nginx",
            INGRESS,
            "-g",
            "daemon off;",
        )
        created = True
        command("start", name)
        path = "/api/v1/independent-apps/_data/items/by-key"
        base = f"http://127.0.0.1:{gateway_port}"
        with httpx.Client(timeout=2, trust_env=False) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get(
                        base + path,
                        params={"record_key": "opaque-key"},
                        headers={"Authorization": "Bearer synthetic-only"},
                    )
                    break
                except httpx.ConnectError:
                    if time.monotonic() >= deadline:
                        raise AssertionError("Owned ingress did not start") from None
                    time.sleep(0.05)
            assert response.status_code == 200
            assert observed == [(path + "?record_key=opaque-key", "Bearer synthetic-only")]
            assert client.post(base + path, json={}).status_code == 405
            assert client.get(base + path + "/extra").status_code == 404
            assert client.get(base + "/api/v1/admin/platform-api-keys").status_code == 404
            assert len(observed) == 1
    finally:
        if created:
            command("rm", "--force", "--volumes", name)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)


def command_runtime():
    import os
    import sys

    selected = object.__new__(DockerRuntime)
    selected.docker_bin = sys.executable
    selected.env = {"PATH": os.defpath}
    return selected


def observation_runtime(monkeypatch, *, origin="http://127.0.0.1:19391"):
    selected = object.__new__(DockerRuntime)
    spec = RuntimeSpec(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "io-fixture",
        "sha256:" + "a" * 64,
        origin,
        "/healthz",
    )
    monkeypatch.setattr(
        selected, "_container", lambda spec: {"Image": spec.image_id, "State": {"Running": True}}
    )
    monkeypatch.setattr(selected, "_proxy", lambda spec: {"State": {"Running": True}})
    return selected, spec


@pytest.mark.parametrize("operation,ui", [("prepare", "empty")])
def test_cold_ui_admission_checks_declared_html_without_full_body_or_redirects(
    monkeypatch, operation, ui
):
    import httpx

    selected, original = observation_runtime(monkeypatch)
    spec = replace(original, ui_path="/launch.html")
    selected.platform_origin = selected.platform_api_origin = "https://platform.example.test"
    selected.data_store = None
    requests, closed = [], []
    actual = httpx.AsyncClient

    class HTML(httpx.AsyncByteStream):
        async def __aiter__(self):
            if ui != "empty":
                yield b"<html>" + b" " * 8192
                pytest.fail("UI admission read beyond its nonempty prefix")

        async def aclose(self):
            closed.append("ui")

    async def handle(request):
        requests.append(request.url.path)
        assert request.headers["accept-encoding"] == "identity"
        if request.url.path == "/__miy_release":
            return httpx.Response(
                200, json={"request_id": spec.request_id, "image_id": spec.image_id}
            )
        if request.url.path == "/healthz":
            return httpx.Response(200, content=b"ok")
        assert request.url.path == spec.ui_path
        headers = {"Content-Type": "text/html; charset=utf-8", "Content-Length": "1048576"}
        if ui == "wrong_type":
            headers["Content-Type"] = "application/json"
        if ui == "redirect":
            headers["Location"] = "https://unapproved.example.test/"
        if ui == "encoded":
            headers["Content-Encoding"] = "gzip"
        return httpx.Response(
            {"failed": 500, "redirect": 302}.get(ui, 200), headers=headers, stream=HTML()
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual(transport=httpx.MockTransport(handle), **kwargs),
    )
    if operation == "observe":
        observed = selected.observe(spec)
        assert observed.active and observed.healthy == (ui == "html")
        assert requests == ["/__miy_release", "/healthz", spec.ui_path]
    else:
        containers = iter([None, {"State": {"Running": True}}, {"State": {"Running": False}}])
        monkeypatch.setattr(selected, "_container", lambda spec: next(containers))
        monkeypatch.setattr(selected, "_inspect", lambda *args: None)

        def command(*args, **kwargs):
            if args[:2] == ("image", "inspect"):
                return spec.image_id
            if args[0] == "exec":
                # Execute only the actual Core probe with in-memory HTTP transport.
                try:
                    exec(compile(args[-1], "<core-cold-ui-probe>", "exec"), {})
                except AssertionError:
                    return None
            return ""

        monkeypatch.setattr(selected, "_run", command)
        if ui == "html":
            selected.prepare(spec)
        else:
            with pytest.raises(RuntimeFailure, match="health_check_failed") as failure:
                selected.prepare(spec)
            assert not failure.value.uncertain
        assert requests == ["/healthz", spec.ui_path]
    assert closed == ["ui"]


def test_actual_descendant_is_killed_and_direct_child_is_reaped(monkeypatch, tmp_path):
    import subprocess
    import time
    from pathlib import Path
    from miy_api.domains.independent_apps import local_runtime

    owned = []
    actual = subprocess.Popen

    def spawn(*args, **kwargs):
        process = actual(*args, **kwargs)
        owned.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(local_runtime, "_DOCKER_SECONDS", 0.15)
    pid_file = tmp_path / "owned-child"
    program = (
        "import os,time,pathlib; pid=os.fork(); "
        "pathlib.Path("
        + repr(str(pid_file))
        + ").write_text(str(os.getpid())) if pid==0 else None; "
        "time.sleep(2) if pid==0 else None"
    )
    with pytest.raises(RuntimeFailure, match="docker_unavailable"):
        command_runtime()._run("-c", program)
    assert len(owned) == 1 and owned[0].returncode == 0
    pid = int(pid_file.read_text())
    stat = Path(f"/proc/{pid}/stat")
    deadline = time.monotonic() + 0.5
    while stat.exists() and stat.read_text().split()[2] != "Z" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not stat.exists() or stat.read_text().split()[2] == "Z"
