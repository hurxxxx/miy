"""Opt-in local container smoke using existing, explicitly selected core image IDs.

This validates a synthetic app's UI/API and resource/network profile. It never
pulls images, deploys a real app, supplies a portal login, or changes live services.
"""

from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def command(*argv: str, cwd: Path | None = None) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} {argv[1]} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def cleanup_owned(*, containers=(), networks=(), images=(), work: Path | None = None) -> None:
    """Attempt every exact fixture target, even after one daemon cleanup fails."""
    failed = []
    for kind, prefix, targets in (
        ("container", ("docker", "rm", "-f"), containers),
        ("network", ("docker", "network", "rm"), networks),
        ("image", ("docker", "image", "rm"), images),
    ):
        for target in targets:
            try:
                command(*prefix, target)
            except (OSError, subprocess.SubprocessError, RuntimeError):
                failed.append(kind)
    if work is not None:
        try:
            shutil.rmtree(work)
        except OSError:
            failed.append("scratch")
    if failed:
        raise RuntimeError("Owned smoke cleanup requires inspection: " + ", ".join(failed))


def smoke(
    runtime_image: str,
    ingress_image: str,
    *,
    ready: threading.Barrier | None = None,
    stop: threading.Event | None = None,
    build_lock: threading.Lock | None = None,
) -> dict:
    for image in (runtime_image, ingress_image):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("Select a locally available immutable image ID")
        if command("docker", "image", "inspect", image, "--format", "{{.Id}}") != image:
            raise ValueError("Local image ID mismatch")
    (ROOT / ".runtime").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="independent-app-pilot-", dir=ROOT / ".runtime"))
    app, stage = work / "app", work / "image"
    stage.mkdir()
    name = work.name
    network, proxy = name + "-net", name + "-ingress"
    base_tag, app_tag = (
        "miy-independent-pilot-base:" + name,
        "miy-independent-pilot:" + name,
    )
    owned_containers: list[str] = []
    owned_tags: list[str] = []
    network_created = False
    try:
        with build_lock if build_lock is not None else contextlib.nullcontext():
            spec = importlib.util.spec_from_file_location(
                "app_environment", ROOT / "scripts/independent-app-env.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.scaffold(
                app,
                app_id="pilot-ui",
                name="Local UI pilot",
                repository="https://example.test/pilot-ui.git",
            )
            (app / "node_modules/@miy").mkdir(parents=True)
            for dependency in ("react", "react-dom", "vite"):
                (app / "node_modules" / dependency).symlink_to(
                    ROOT / "node_modules" / dependency, target_is_directory=True
                )
            (app / "node_modules/@miy/app-sdk").symlink_to(
                app / "vendor/miy-app-sdk", target_is_directory=True
            )
            command("node", str(ROOT / "node_modules/vite/bin/vite.js"), "build", cwd=app)
            command("node", "--test", "tests/contract.test.mjs", cwd=app)
            # Only these allowlisted build outputs enter the image. No checkout, .env,
            # auth file, package cache or Docker socket enters an app container.
            shutil.copyfile(app / "api.py", stage / "api.py")
            shutil.copyfile(app / "business.py", stage / "business.py")
            shutil.copytree(app / "dist", stage / "dist")
            command("docker", "image", "tag", runtime_image, base_tag)
            owned_tags.append(base_tag)
            (stage / "Dockerfile").write_text(
                f"FROM {base_tag}\nWORKDIR /workspace\nCOPY api.py business.py ./\nCOPY dist ./dist\n"
                'USER 1000:1000\nENTRYPOINT ["/opt/miy/venvs/api/bin/python", "-m", "uvicorn", "api:app", '
                '"--host", "0.0.0.0", "--port", "8000", "--no-access-log"]\n'
            )
            command(
                "docker",
                "build",
                "--network",
                "none",
                "--label",
                "miy.independent-pilot=1",
                "--tag",
                app_tag,
                str(stage),
            )
            owned_tags.append(app_tag)
            image_id = command("docker", "image", "inspect", app_tag, "--format", "{{.Id}}")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        command(
            "docker",
            "network",
            "create",
            "--internal",
            "--label",
            "miy.independent-pilot=1",
            network,
        )
        network_created = True
        limits = [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--cpus",
            "1",
            "--user",
            "1000:1000",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m",
        ]
        command(
            "docker",
            "create",
            "--pull=never",
            "--name",
            name,
            "--label",
            "miy.independent-pilot=1",
            "--network",
            network,
            *limits,
            "--env",
            "MIY_APP_ID=pilot-ui",
            "--env",
            "MIY_APP_INSTALLATION_ID=pilot-install",
            "--env",
            f"MIY_APP_ORIGIN=http://127.0.0.1:{port}",
            "--env",
            "MIY_APP_PLATFORM_ORIGIN=http://127.0.0.1:8001",
            image_id,
        )
        owned_containers.append(name)
        command("docker", "start", name)
        config = work / "nginx.conf"
        config.write_text(f"""pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 64; }}
http {{
  access_log off;
  client_body_temp_path /tmp/client;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  server {{
    listen 8080;
    client_max_body_size 1m;
    location / {{ proxy_pass http://{name}:8000; proxy_set_header Host $host; }}
  }}
}}
""")
        command(
            "docker",
            "create",
            "--pull=never",
            "--name",
            proxy,
            "--label",
            "miy.independent-pilot=1",
            "--network",
            "bridge",
            *limits,
            "--publish",
            f"127.0.0.1:{port}:8080",
            "--mount",
            f"type=bind,src={config},dst=/etc/nginx/miy.conf,readonly",
            "--entrypoint",
            "nginx",
            ingress_image,
            "-c",
            "/etc/nginx/miy.conf",
            "-g",
            "daemon off;",
        )
        owned_containers.append(proxy)
        command("docker", "network", "connect", network, proxy)
        command("docker", "start", proxy)
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=1
                ) as response:
                    assert json.load(response) == {"status": "ok"}
                break
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Independent ingress health check failed") from None
                time.sleep(0.2)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert b'<div id="root"></div>' in response.read()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as response:
            assert json.load(response)["app_id"] == "pilot-ui"
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/me", timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Unauthenticated app identity allowed")
        inspected = json.loads(command("docker", "inspect", name))[0]
        profile = inspected["HostConfig"]
        assert profile["ReadonlyRootfs"] and profile["Memory"] == 268435456
        assert profile["NanoCpus"] == 1000000000 and profile["PidsLimit"] == 64
        assert profile["CapDrop"] == ["ALL"] and profile["SecurityOpt"] == ["no-new-privileges"]
        assert not inspected["Mounts"]
        limits_json = command(
            "docker",
            "exec",
            name,
            "/opt/miy/venvs/api/bin/python",
            "-c",
            "from pathlib import Path; import json; assert not Path('/var/run/docker.sock').exists(); "
            "rows=Path('/proc/net/route').read_text().splitlines()[1:]; "
            "assert all(row.split()[1]!='00000000' for row in rows); "
            "print(json.dumps({key:Path('/sys/fs/cgroup/'+key).read_text().strip() "
            "for key in ('memory.max','cpu.max','pids.max')}))",
        )
        latency_ms: list[float] = []
        if ready is not None and stop is not None:
            ready.wait(timeout=180)
            # Availability under a real concurrent build, not a throughput claim.
            deadline = time.monotonic() + 360
            while not stop.is_set():
                started = time.monotonic()
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=2
                ) as response:
                    assert json.load(response) == {"status": "ok"}
                latency_ms.append((time.monotonic() - started) * 1000)
                if time.monotonic() > deadline:
                    raise RuntimeError("Concurrent build exceeded the preview probe deadline")
                stop.wait(0.1)
        return {
            "ui_build": "passed",
            "preview": "passed",
            "unauthenticated_identity": "denied",
            "app_host_mounts": 0,
            "app_default_route": False,
            "resource_limits": json.loads(limits_json),
            "concurrent_health_requests": len(latency_ms),
            "max_health_latency_ms": round(max(latency_ms, default=0), 2),
        }
    finally:
        cleanup_owned(
            containers=reversed(owned_containers),
            networks=[network] if network_created else [],
            images=reversed(owned_tags),
            work=work,
        )


def memory_boundary(runtime_image: str) -> dict:
    """A disposable process must be stopped at its cgroup boundary."""
    name = "miy-independent-limit-" + uuid4().hex
    created = False
    try:
        command(
            "docker",
            "create",
            "--pull=never",
            "--name",
            name,
            "--network",
            "none",
            "--label",
            "miy.independent-pilot=1",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "64m",
            "--memory-swap",
            "64m",
            "--pids-limit",
            "32",
            "--cpus",
            "0.5",
            "--user",
            "1000:1000",
            "--entrypoint",
            "/opt/miy/venvs/api/bin/python",
            runtime_image,
            "-c",
            "payload = bytearray(128 * 1024 * 1024)",
        )
        created = True
        command("docker", "start", name)
        exit_code = command("docker", "wait", name)
        state = json.loads(command("docker", "inspect", "--format", "{{json .State}}", name))
        if exit_code != "137" or not state["OOMKilled"]:
            raise AssertionError("Memory overrun was not contained by the cgroup")
        return {"limit_bytes": 67108864, "allocation_bytes": 134217728, "oom_killed": True}
    finally:
        if created:
            cleanup_owned(containers=[name])


def capacity(runtime_image: str, ingress_image: str) -> dict:
    """Observe four isolated previews during one real offline build on this host."""
    from miy_api.domains.independent_apps.builds import build_app

    (ROOT / ".runtime").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="independent-capacity-", dir=ROOT / ".runtime"))
    ready, stop, build_lock = threading.Barrier(5), threading.Event(), threading.Lock()
    artifact = None

    def preview():
        try:
            return smoke(
                runtime_image, ingress_image, ready=ready, stop=stop, build_lock=build_lock
            )
        except BaseException:
            ready.abort()
            stop.set()
            raise

    try:
        source = work / "build-app"
        command(
            "python3",
            str(ROOT / "scripts/independent-app-env.py"),
            "scaffold",
            str(source),
            "--app-id",
            "capacity-app",
            "--name",
            "Capacity fixture",
            "--repository",
            "https://example.test/capacity-app.git",
        )
        for args in (
            ("init", "-b", "pilot"),
            ("config", "user.email", "capacity@test.invalid"),
            ("config", "user.name", "Capacity Test"),
            ("remote", "add", "origin", "https://example.test/capacity-app.git"),
            ("add", "."),
            ("commit", "-m", "synthetic capacity fixture"),
        ):
            command(
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(source),
                *args,
            )
        revision = command(
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(source),
            "rev-parse",
            "HEAD",
        )
        with ThreadPoolExecutor(max_workers=4) as executor:
            previews = [executor.submit(preview) for _ in range(4)]
            try:
                ready.wait(timeout=180)
                started = time.monotonic()
                evidence = build_app(
                    source=source,
                    revision=revision,
                    expected_definition=json.loads((source / "app.manifest.json").read_text()),
                    toolchain_image=runtime_image,
                    work_root=work,
                )
                artifact = evidence.artifact_digest
                elapsed = time.monotonic() - started
                exceeded = memory_boundary(runtime_image)
            finally:
                stop.set()
                ready.abort()
            observed = [future.result(timeout=30) for future in previews]
        if not all(row["concurrent_health_requests"] > 0 for row in observed):
            raise AssertionError("Concurrent preview observation was incomplete")
        return {
            "preview_count": 4,
            "concurrent_build_count": 1,
            "build_seconds": round(elapsed, 2),
            "build_evidence": asdict(evidence),
            "previews": observed,
            "memory_overrun": exceeded,
            "scope": "synthetic availability and resource limits on this Linux Docker host",
        }
    finally:
        stop.set()
        ready.abort()
        cleanup_owned(images=[artifact] if artifact is not None else [], work=work)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-image",
        required=True,
        help="Existing MIY validation runtime image ID",
    )
    parser.add_argument("--ingress-image", required=True, help="Existing approved nginx image ID")
    parser.add_argument(
        "--instances",
        type=int,
        choices=(1, 4),
        default=1,
        help="Four previews include one concurrent trusted offline build (requires API environment)",
    )
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("This local smoke requires a Linux Docker host")
    run = capacity if args.instances == 4 else smoke
    print(json.dumps(run(args.runtime_image, args.ingress_image), indent=2))


if __name__ == "__main__":
    main()
