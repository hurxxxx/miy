"""Runtime observation must distinguish absence, foreign objects and daemon loss."""

import json
from uuid import uuid4

import pytest

from miy_api.domains.independent_apps.data_store import DataStoreError
from miy_api.domains.independent_apps.delivery import RuntimeFailure, RuntimeSpec
from miy_api.domains.independent_apps.local_runtime import DockerRuntime
from miy_api.core.app_origins import exact_origin


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


def test_successful_unfiltered_inventory_is_the_only_absence_proof(monkeypatch):
    selected, calls = runtime(monkeypatch, [{"Names": "another-container"}])
    assert selected._inspect("container", "candidate") is None
    assert len(calls) == 1 and "--filter" not in calls[0][0]


def test_disappearing_daemon_does_not_turn_a_known_object_into_absence(monkeypatch):
    selected, calls = runtime(
        monkeypatch, [{"Names": "candidate"}], RuntimeFailure("docker_unavailable")
    )
    with pytest.raises(RuntimeFailure, match="docker_unavailable"):
        selected._inspect("container", "candidate")
    assert calls[-1] == (("container", "inspect", "candidate"), {})


def test_foreign_deterministic_name_is_never_adopted_or_deleted(monkeypatch):
    selected, calls = runtime(monkeypatch, [{"Names": "candidate"}], [{"Config": {"Labels": None}}])
    with pytest.raises(RuntimeFailure, match="foreign_runtime_name"):
        selected._inspect("container", "candidate")
    assert all("rm" not in args for args, _ in calls)


@pytest.mark.parametrize(
    "failure", [None, "data_cluster_public_connect", "data_provision_unavailable"]
)
def test_data_profile_requires_core_migration_before_any_daemon_mutation(monkeypatch, failure):
    selected = object.__new__(DockerRuntime)
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "data-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile="web-api-postgres-v1",
    )
    calls = []

    class Store:
        def prepare(self, **kwargs):
            calls.append(kwargs)
            raise DataStoreError(failure)

    selected.data_store = Store() if failure else None

    def command(*args):
        calls.append(args)
        assert args == ("image", "inspect", spec.image_id, "--format", "{{.Id}}")
        return spec.image_id

    monkeypatch.setattr(selected, "_run", command)
    with pytest.raises(RuntimeFailure) as result:
        selected.prepare(spec)
    assert result.value.code == (failure or "data_configuration_required")
    assert result.value.uncertain == (failure == "data_provision_unavailable")
    if failure:
        assert calls[-1] == {
            "installation_id": spec.installation_id,
            "app_id": spec.app_id,
            "environment": "development",
            "artifact_digest": spec.image_id,
            "request_id": spec.request_id,
        }


def test_data_gateway_is_bound_to_its_profile_and_cannot_proxy_other_platform_apis():
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = "https://platform.example.test"
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "data-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
    )
    assert "/_data/" not in selected._configuration(spec)
    from dataclasses import replace

    configuration = selected._configuration(replace(spec, runtime_profile="web-api-postgres-v1"))
    assert "/api/v1/independent-apps/_data/" in configuration
    assert "client_max_body_size 20k;" in configuration
    assert "location / { return 404; }" in configuration
    assert "limit_except GET POST PUT DELETE { deny all; }" in configuration


@pytest.mark.parametrize("profile", ["web-api-v1", "web-api-postgres-v1"])
def test_selected_file_gateway_exposes_only_the_two_app_authorized_paths(profile):
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = "https://platform.example.test"
    spec = RuntimeSpec(
        str(uuid4()),
        str(uuid4()),
        "file-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile=profile,
    )
    configuration = selected._configuration(spec)
    assert configuration.count("location = /api/v1/independent-apps/_files/") == 2
    assert (
        "location = /api/v1/independent-apps/_files/selection-request {\n   if ($request_method != POST) { return 405; }"
        in configuration
    )
    assert (
        "location = /api/v1/independent-apps/_files/content {\n   if ($request_method != GET) { return 405; }"
        in configuration
    )
    assert "/candidates" not in configuration and "/authorize-selection" not in configuration
    assert "proxy_buffering off;" in configuration and "proxy_read_timeout 12s;" in configuration
    assert (
        "proxy_read_timeout 5s;" in configuration and "location / { return 404; }" in configuration
    )


@pytest.mark.parametrize("profile", ["web-api-v1", "web-api-postgres-v1"])
@pytest.mark.parametrize(
    ("origin", "target"),
    [
        ("http://localhost", "http://host.docker.internal:80"),
        ("http://127.0.0.1", "http://host.docker.internal:80"),
        ("https://localhost", "https://host.docker.internal:443"),
        ("https://127.0.0.1", "https://host.docker.internal:443"),
        ("http://localhost:443", "http://host.docker.internal:443"),
        ("http://127.0.0.1:443", "http://host.docker.internal:443"),
        ("http://localhost:19391", "http://host.docker.internal:19391"),
        ("http://127.0.0.1:19391", "http://host.docker.internal:19391"),
        ("https://localhost:80", "https://host.docker.internal:80"),
        ("https://127.0.0.1:80", "https://host.docker.internal:80"),
        ("https://localhost:9443", "https://host.docker.internal:9443"),
        ("https://127.0.0.1:9443", "https://host.docker.internal:9443"),
        ("https://platform.example.test", "https://platform.example.test"),
        ("https://platform.example.test:9443", "https://platform.example.test:9443"),
    ],
)
def test_generated_gateway_preserves_upstream_scheme_and_selected_port(profile, origin, target):
    selected = object.__new__(DockerRuntime)
    selected.platform_api_origin = exact_origin(origin)
    spec = RuntimeSpec(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "port-fixture",
        "sha256:" + "a" * 64,
        "http://127.0.0.1:19391",
        "/healthz",
        runtime_profile=profile,
    )
    configuration = selected._configuration(spec)
    assert configuration.count(f"proxy_pass {target};") == (
        5 if profile == "web-api-postgres-v1" else 4
    )
    assert (
        f"location = /api/v1/independent-apps/exchange {{ limit_except POST {{ deny all; }} "
        f"proxy_pass {target}; }}" in configuration
    )
    assert (
        f"location = /api/v1/independent-apps/session {{ limit_except GET {{ deny all; }} "
        f"proxy_pass {target}; }}" in configuration
    )
    assert "proxy_ssl_verify on;" in configuration
    assert "proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;" in configuration
    assert "proxy_ssl_name " + origin.split("://", 1)[1].split(":", 1)[0] + ";" in configuration
    assert f"proxy_set_header Host {origin.split('://', 1)[1]};" in configuration
    assert "location / { return 404; }" in configuration


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


def test_command_kills_stdout_flood_before_producer_completes(tmp_path):
    marker = tmp_path / "completed"
    program = (
        "import os,time,pathlib; "
        "[os.write(1,b'x'*65536) for _ in range(64)]; "
        "time.sleep(.1); pathlib.Path(" + repr(str(marker)) + ").touch()"
    )
    with pytest.raises(RuntimeFailure, match="docker_response_limit"):
        command_runtime()._run("-c", program, missing_ok=True)
    assert not marker.exists()


def test_command_caps_raw_bytes_and_sanitizes_invalid_utf8():
    selected = command_runtime()
    with pytest.raises(RuntimeFailure, match="docker_response_limit"):
        selected._run("-c", "import os; os.write(1,'é'.encode()*1048576)")
    with pytest.raises(RuntimeFailure, match="docker_response_invalid"):
        selected._run("-c", "import os; os.write(1,b'\\xff')")


def test_command_exact_limit_and_stderr_flood_are_bounded(monkeypatch):
    import subprocess

    actual = subprocess.Popen
    observed = []

    def spawn(*args, **kwargs):
        observed.append(kwargs)
        return actual(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    result = command_runtime()._run(
        "-c", "import os; os.write(2,b'e'*4194304); os.write(1,b'x'*1048576)"
    )
    assert len(result) == 1048576
    assert observed[0]["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    "program",
    [
        "import time; time.sleep(.6)",
        "import os,time; os.close(1); time.sleep(.6)",
        "import os,time; pid=os.fork(); time.sleep(.6) if pid==0 else None",
    ],
)
def test_command_one_deadline_covers_quiet_eof_and_descendant_pipe(monkeypatch, program):
    from miy_api.domains.independent_apps import local_runtime
    import time

    monkeypatch.setattr(local_runtime, "_DOCKER_SECONDS", 0.08, raising=False)
    start = time.monotonic()
    with pytest.raises(RuntimeFailure, match="docker_unavailable") as result:
        command_runtime()._run("-c", program, missing_ok=True)
    assert result.value.uncertain and time.monotonic() - start < 0.45


@pytest.mark.parametrize("operation", ["observe", "discard", "retire"])
def test_unreachable_release_never_proves_inactive_or_permits_remove(monkeypatch, operation):
    import httpx

    selected, spec = observation_runtime(monkeypatch)
    calls = []
    monkeypatch.setattr(selected, "_run", lambda *args, **kw: calls.append(args) or "")

    def fail(*args, **kwargs):
        raise httpx.ReadTimeout("synthetic private error")

    monkeypatch.setattr(httpx.Client, "stream", fail)
    monkeypatch.setattr(httpx.AsyncClient, "send", fail)
    with pytest.raises(RuntimeFailure, match="runtime_observation_unavailable") as result:
        getattr(selected, operation)(spec)
    assert result.value.uncertain and not calls


@pytest.mark.parametrize("phase", ["marker", "headers", "health"])
def test_actual_loopback_trickle_has_total_deadline_and_closes_peer(monkeypatch, phase):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from miy_api.domains.independent_apps import local_runtime

    disconnected = threading.Event()
    marker = json.dumps(
        {"request_id": "00000000-0000-4000-8000-000000000001", "image_id": "sha256:" + "a" * 64}
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = marker if self.path == "/__miy_release" else b"h" * 100
            if phase == "headers" and self.path == "/__miy_release":
                try:
                    header = (
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\n\r\n"
                    )
                    for byte in header:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.01)
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    disconnected.set()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                if (phase == "marker") == (self.path == "/__miy_release"):
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        time.sleep(0.01)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(local_runtime, "_OBSERVATION_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(local_runtime, "_OBSERVATION_CLEANUP_SECONDS", 0.04, raising=False)
    selected, spec = observation_runtime(
        monkeypatch, origin=f"http://127.0.0.1:{server.server_port}"
    )
    start = time.monotonic()
    try:
        if phase in {"marker", "headers"}:
            with pytest.raises(RuntimeFailure, match="runtime_observation_unavailable"):
                selected.observe(spec)
        else:
            observed = selected.observe(spec)
            assert observed.active and not observed.healthy
        assert time.monotonic() - start < 0.45
        assert disconnected.wait(0.3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_running_event_loop_refuses_before_docker_or_http(monkeypatch):
    import asyncio

    selected, spec = observation_runtime(monkeypatch)
    monkeypatch.setattr(
        selected, "_container", lambda spec: pytest.fail("Docker read before context refusal")
    )

    async def call():
        with pytest.raises(RuntimeFailure, match="runtime_observation_context_required"):
            selected.observe(spec)

    asyncio.run(call())


@pytest.mark.parametrize("kind", ["app", "ingress"])
@pytest.mark.parametrize(
    "log_config",
    [
        None,
        {"Type": "json-file", "Config": {}},
        {"Type": "none", "Config": {"max-size": "1m"}},
        {"Type": "none", "Config": {}},
    ],
)
def test_existing_app_and_ingress_require_exact_disabled_logging(
    monkeypatch, tmp_path, kind, log_config
):
    selected, spec = observation_runtime(monkeypatch)
    selected.root = tmp_path
    selected.ingress_image = "sha256:" + "b" * 64
    selected.platform_origin = selected.platform_api_origin = "https://platform.example.test"
    _, network, _ = selected.names(spec)
    host = {
        "ReadonlyRootfs": True,
        "Privileged": False,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "LogConfig": log_config,
    }
    item = {
        "Config": {
            "User": "1000:1000",
            "Labels": {"miy.independent-installation": spec.installation_id},
        },
        "HostConfig": host,
        "NetworkSettings": {},
        "Mounts": [],
    }
    if kind == "app":
        host.update(Memory=536870912, PidsLimit=256, NanoCpus=1000000000)
        item["Image"] = spec.image_id
        item["Config"]["Labels"].update(
            {
                "miy.independent-deployment": spec.request_id,
                "miy.independent-profile": selected._fingerprint(spec),
            }
        )
        item["NetworkSettings"]["Networks"] = {network: {}}
        check = DockerRuntime._container
    else:
        host.update(
            Memory=134217728,
            PidsLimit=64,
            NanoCpus=500000000,
            PortBindings={"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "19391"}]},
        )
        item["Image"] = selected.ingress_image
        item["NetworkSettings"]["Networks"] = {network: {}, "bridge": {}}
        item["Mounts"] = [
            {
                "Type": "bind",
                "Source": str(tmp_path / spec.installation_id),
                "Destination": "/etc/miy",
                "RW": False,
            }
        ]
        check = DockerRuntime._proxy
    calls = []
    monkeypatch.setattr(selected, "_inspect", lambda *args: item)
    monkeypatch.setattr(selected, "_run", lambda *args, **kwargs: calls.append(args))
    if log_config == {"Type": "none", "Config": {}}:
        assert check(selected, spec) is item
    else:
        with pytest.raises(RuntimeFailure, match="identity_mismatch"):
            check(selected, spec)
    assert calls == []


def test_both_owned_container_creates_explicitly_disable_docker_logs(monkeypatch, tmp_path):
    selected, spec = observation_runtime(monkeypatch)
    selected.root = tmp_path
    selected.ingress_image = "sha256:" + "b" * 64
    selected.platform_origin = selected.platform_api_origin = "https://platform.example.test"
    selected.data_store = None
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        return spec.image_id if args[:2] == ("image", "inspect") else ""

    containers = iter([None, {"State": {"Running": True}}])
    monkeypatch.setattr(selected, "_run", command)
    monkeypatch.setattr(selected, "_container", lambda spec: next(containers))
    monkeypatch.setattr(selected, "_inspect", lambda *args: None)
    selected.prepare(spec)
    monkeypatch.setattr(selected, "_container", lambda spec: {"State": {"Running": True}})
    monkeypatch.setattr(selected, "_proxy", lambda spec: None)
    from miy_api.domains.independent_apps.delivery import Observation

    monkeypatch.setattr(
        selected, "observe", lambda spec: Observation(True, True, spec.image_id, True)
    )
    selected.activate(spec)
    creates = [args for args in calls if args[0] == "create"]
    assert len(creates) == 2
    assert all(args[args.index("--log-driver") + 1] == "none" for args in creates)


@pytest.mark.parametrize("fault", ["non200", "malformed", "oversize", "encoded"])
def test_pinned_async_httpx_incomplete_marker_refuses_cleanup(monkeypatch, fault):
    import httpx

    selected, spec = observation_runtime(monkeypatch)
    calls = []
    actual = httpx.AsyncClient

    async def handle(request):
        if fault == "non200":
            return httpx.Response(503, content=b"unavailable")
        if fault == "malformed":
            return httpx.Response(200, content=b"{}")
        if fault == "oversize":
            return httpx.Response(200, content=b"x" * 1025)
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=b"not-decoded")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(selected, "_run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeFailure, match="runtime_observation_unavailable"):
        selected.discard(spec)
    assert calls == []


@pytest.mark.parametrize("cleanup", ["hang", "interrupt"])
@pytest.mark.parametrize("marker", ["active", "different", "invalid"])
def test_owned_http_cleanup_bound_preserves_exact_marker_or_original_refusal(
    monkeypatch, cleanup, marker
):
    import asyncio
    import httpx
    import time
    from miy_api.domains.independent_apps import local_runtime

    selected, spec = observation_runtime(monkeypatch)
    actual = httpx.AsyncClient
    payload = {"request_id": spec.request_id, "image_id": spec.image_id}
    if marker == "different":
        payload["request_id"] = "00000000-0000-4000-8000-000000000003"
    elif marker == "invalid":
        payload = {}
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(payload).encode()

        async def aclose(self):
            closed.append("response")
            if cleanup == "hang":
                await asyncio.Event().wait()
            else:
                raise KeyboardInterrupt("synthetic cleanup interruption")

    class Client(actual):
        async def aclose(self):
            closed.append("client")
            if cleanup == "hang":
                await asyncio.Event().wait()
            else:
                raise KeyboardInterrupt("synthetic cleanup interruption")

    requests = []

    async def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/healthz":
            raise httpx.ReadTimeout("synthetic health failure")
        return httpx.Response(200, stream=Stream())

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: Client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(local_runtime, "_OBSERVATION_SECONDS", 0.12)
    monkeypatch.setattr(local_runtime, "_OBSERVATION_CLEANUP_SECONDS", 0.03)
    start = time.monotonic()
    if marker == "invalid":
        with pytest.raises(RuntimeFailure, match="runtime_observation_unavailable"):
            selected.observe(spec)
    else:
        observed = selected.observe(spec)
        assert observed.active == (marker == "active") and not observed.healthy
    assert time.monotonic() - start < 0.35
    assert closed == ["response", "client"]
    assert len(requests) == (2 if marker == "active" else 1)


def test_command_cleanup_interrupt_preserves_timeout_control(monkeypatch):
    import subprocess
    from miy_api.domains.independent_apps import local_runtime

    actual = subprocess.Popen
    owned = []

    def spawn(*args, **kwargs):
        process = actual(*args, **kwargs)
        owned.append((process, process.wait))

        def wait(*args, **kwargs):
            raise KeyboardInterrupt("synthetic reap interruption")

        process.wait = wait
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(local_runtime, "_DOCKER_SECONDS", 0.05)
    try:
        with pytest.raises(RuntimeFailure, match="docker_unavailable"):
            command_runtime()._run("-c", "import time; time.sleep(.5)")
    finally:
        for process, wait in owned:
            process.wait = wait
            wait(timeout=1)
    assert all(process.returncode is not None for process, _ in owned)


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


def test_acknowledged_healthy_runtime_survives_cleanup_interrupt(monkeypatch):
    import httpx

    selected, spec = observation_runtime(monkeypatch)
    actual = httpx.AsyncClient

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps({"request_id": spec.request_id, "image_id": spec.image_id}).encode()

        async def aclose(self):
            raise KeyboardInterrupt("synthetic owned response close")

    async def handle(request):
        if request.url.path == "/__miy_release":
            return httpx.Response(200, stream=Stream())
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual(transport=httpx.MockTransport(handle), **kwargs),
    )
    observed = selected.observe(spec)
    assert observed.active and observed.healthy
