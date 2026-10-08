"""Core-owned loopback Docker executor. App manifests never become host commands.

State is reconciled from PostgreSQL intent, Docker identity and loaded ingress
configuration; a generated nginx file alone is never evidence of activation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from miy_api.core.app_origins import exact_origin
from miy_api.domains.independent_apps.data_store import DataStoreError, PostgresAppData
from miy_api.domains.independent_apps.delivery import Observation, RuntimeFailure, RuntimeSpec

_IMAGE = re.compile(r"sha256:[a-f0-9]{64}")
_LABEL = "miy.independent-installation"
_REQUEST = "miy.independent-deployment"


class DockerRuntime:
    def __init__(
        self,
        *,
        state_root: Path,
        ingress_image: str,
        platform_origin: str,
        platform_api_origin: str | None = None,
        data_store: PostgresAppData | None = None,
        docker_bin: str = "/usr/bin/docker",
    ):
        if not _IMAGE.fullmatch(ingress_image):
            raise ValueError("Select an immutable local core ingress image ID")
        self.platform_origin = exact_origin(platform_origin)
        self.platform_api_origin = exact_origin(platform_api_origin or platform_origin)
        self.ingress_image = ingress_image
        self.data_store = data_store
        # This directory is core-owned configuration, never an app repository.
        self.root = state_root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise ValueError("Executor state root must be private to the operator (0700)")
        self.docker_bin = docker_bin
        config = self.root / "docker-config"
        config.mkdir(exist_ok=True, mode=0o700)
        self.env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_CONFIG": str(config)}
        if self._run("image", "inspect", ingress_image, "--format", "{{.Id}}") != ingress_image:
            raise ValueError("Approved ingress image is unavailable locally")

    def _run(self, *args: str, missing_ok: bool = False) -> str | None:
        try:
            result = subprocess.run(
                [self.docker_bin, *args],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
                env=self.env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeFailure("docker_unavailable") from exc
        if result.returncode:
            # Only a successful daemon inventory may establish absence. A missing
            # object from `inspect` and a disconnected daemon are not equivalent.
            if missing_ok:
                return None
            raise RuntimeFailure("docker_command_failed")
        if len(result.stdout) > 1024 * 1024:
            raise RuntimeFailure("docker_response_limit")
        return result.stdout.strip()

    def _objects(self, kind: str) -> list[dict]:
        command = ("container", "ls", "--all") if kind == "container" else ("network", "ls")
        # An unfiltered, successful inventory proves absence. A failed inspect
        # cannot distinguish a missing object from a daemon/permission failure.
        output = self._run(*command, "--format", "{{json .}}")
        try:
            return [json.loads(line) for line in output.splitlines()]
        except (ValueError, AttributeError) as exc:
            raise RuntimeFailure("docker_response_invalid") from exc

    def _inspect(self, kind: str, name: str) -> dict | None:
        rows = self._objects(kind)
        key = "Names" if kind == "container" else "Name"
        if not any(row.get(key) == name for row in rows):
            return None
        raw = self._run(kind, "inspect", name)
        try:
            records = json.loads(raw)
            if len(records) != 1:
                raise ValueError()
            labels = (
                records[0].get("Config", {}).get("Labels", {})
                if kind == "container"
                else records[0].get("Labels", {})
            )
            if not (labels or {}).get(_LABEL):
                raise RuntimeFailure("foreign_runtime_name", uncertain=False)
            return records[0]
        except (ValueError, TypeError) as exc:
            raise RuntimeFailure("docker_response_invalid") from exc

    @staticmethod
    def names(spec: RuntimeSpec) -> tuple[str, str, str]:
        install, request = UUID(spec.installation_id).hex, UUID(spec.request_id).hex
        return f"miy-app-{request}", f"miy-app-net-{install}", f"miy-app-ingress-{install}"

    @staticmethod
    def port(spec: RuntimeSpec) -> int:
        parsed = urlsplit(exact_origin(spec.origin))
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or not parsed.port
            or parsed.port < 1024
        ):
            raise RuntimeFailure("local_origin_required", uncertain=False)
        if not _IMAGE.fullmatch(spec.image_id):
            raise RuntimeFailure("immutable_image_required", uncertain=False)
        return parsed.port

    def _fingerprint(self, spec: RuntimeSpec) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "spec": spec.__dict__,
                    "platform": self.platform_origin,
                    "platform_api": self.platform_api_origin,
                    "profile": 1,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def _container(self, spec: RuntimeSpec) -> dict | None:
        name, network, _ = self.names(spec)
        item = self._inspect("container", name)
        if item:
            labels, host = item["Config"].get("Labels", {}), item["HostConfig"]
            if (
                item["Image"] != spec.image_id
                or labels.get(_LABEL) != spec.installation_id
                or labels.get(_REQUEST) != spec.request_id
                or labels.get("miy.independent-profile") != self._fingerprint(spec)
                or not host.get("ReadonlyRootfs")
                or host.get("Privileged")
                or set(host.get("CapDrop", [])) != {"ALL"}
                or "no-new-privileges" not in host.get("SecurityOpt", [])
                or host.get("Memory") != 536870912
                or host.get("PidsLimit") != 256
                or host.get("NanoCpus") != 1000000000
                or host.get("Binds")
                or host.get("PortBindings")
                or item["Config"].get("User") != "1000:1000"
                or set(item["NetworkSettings"]["Networks"]) != {network}
                or any(mount.get("Type") != "tmpfs" for mount in item.get("Mounts", []))
            ):
                raise RuntimeFailure("runtime_identity_mismatch")
        return item

    def prepare(self, spec: RuntimeSpec) -> None:
        self.port(spec)
        name, network, _ = self.names(spec)
        if self._run("image", "inspect", spec.image_id, "--format", "{{.Id}}") != spec.image_id:
            raise RuntimeFailure("artifact_unavailable", uncertain=False)
        if spec.runtime_profile not in {"web-api-v1", "web-api-postgres-v1"}:
            raise RuntimeFailure("runtime_profile_unsupported", uncertain=False)
        if spec.runtime_profile == "web-api-postgres-v1":
            if self.data_store is None:
                raise RuntimeFailure("data_configuration_required", uncertain=False)
            try:
                # Only the core owns schema operations and credentials. Code
                # rollback repeats this forward-only versioned preparation.
                self.data_store.prepare(
                    installation_id=spec.installation_id,
                    app_id=spec.app_id,
                    environment=spec.environment,
                    artifact_digest=spec.image_id,
                    request_id=spec.request_id,
                )
            except DataStoreError as exc:
                raise RuntimeFailure(
                    exc.code, uncertain=exc.code == "data_provision_unavailable"
                ) from exc
        net = self._inspect("network", network)
        if net is None:
            self._run(
                "network",
                "create",
                "--internal",
                "--label",
                f"{_LABEL}={spec.installation_id}",
                network,
            )
        elif not net.get("Internal") or net.get("Labels", {}).get(_LABEL) != spec.installation_id:
            raise RuntimeFailure("network_identity_mismatch")
        if self._container(spec) is None:
            self._run(
                "create",
                "--name",
                name,
                "--label",
                f"{_LABEL}={spec.installation_id}",
                "--label",
                f"{_REQUEST}={spec.request_id}",
                "--label",
                f"miy.independent-profile={self._fingerprint(spec)}",
                "--network",
                network,
                "--network-alias",
                name,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "256",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--user",
                "1000:1000",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=64m",
                "--env",
                f"MIY_APP_ID={spec.app_id}",
                "--env",
                f"MIY_APP_INSTALLATION_ID={spec.installation_id}",
                "--env",
                f"MIY_APP_ORIGIN={spec.origin}",
                "--env",
                f"MIY_APP_PLATFORM_ORIGIN={self.platform_origin}",
                "--env",
                "MIY_APP_PLATFORM_API_ORIGIN=http://miy-platform-gateway:8081",
                spec.image_id,
            )
        container = self._container(spec)
        if not container["State"].get("Running"):
            self._run("start", name)
        # Probe inside the isolated app network before changing the live ingress.
        program = (
            "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000' + "
            + repr(spec.health_path)
            + ",timeout=2); assert r.status==200; assert len(r.read(65537))<=65536"
        )
        for _ in range(20):
            result = self._run(
                "exec", name, "/opt/miy/venvs/api/bin/python", "-c", program, missing_ok=True
            )
            if result is not None:
                return
            if not self._container(spec)["State"].get("Running"):
                break
            time.sleep(0.2)
        raise RuntimeFailure("health_check_failed", uncertain=False)

    def _configuration(self, spec: RuntimeSpec) -> str:
        app, _, _ = self.names(spec)
        upstream = urlsplit(self.platform_api_origin)
        host = upstream.hostname
        if not re.fullmatch(r"[a-zA-Z0-9.-]+", host or ""):
            raise RuntimeFailure("platform_upstream_invalid", uncertain=False)
        target = self.platform_api_origin
        if host in {"localhost", "127.0.0.1"}:
            port = (
                upstream.port
                if upstream.port is not None
                else (443 if upstream.scheme == "https" else 80)
            )
            target = f"{upstream.scheme}://host.docker.internal:{port}"
        marker = json.dumps(
            {"request_id": spec.request_id, "image_id": spec.image_id}, separators=(",", ":")
        )
        data_gateway = ""
        if spec.runtime_profile == "web-api-postgres-v1":
            data_gateway = f"""
  location ~ "^/api/v1/independent-apps/_data/[a-z][a-z0-9_-]{{0,63}}(/[a-f0-9-]{{36}})?$" {{
   client_max_body_size 20k;
   limit_except GET POST PUT DELETE {{ deny all; }}
   proxy_pass {target};
  }}
"""
        return f"""pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 128; }}
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
  location = /__miy_release {{ default_type application/json; return 200 '{marker}'; }}
  location / {{ proxy_pass http://{app}:8000; proxy_set_header Host $host; }}
 }}
 server {{
  listen 8081;
  client_max_body_size 8k;
  proxy_connect_timeout 3s;
  proxy_read_timeout 5s;
  proxy_ssl_server_name on;
  proxy_ssl_verify on;
  proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
  proxy_ssl_name {host};
  proxy_set_header Host {upstream.netloc};
  location = /api/v1/independent-apps/exchange {{ limit_except POST {{ deny all; }} proxy_pass {target}; }}
  location = /api/v1/independent-apps/session {{ limit_except GET {{ deny all; }} proxy_pass {target}; }}
  location = /api/v1/independent-apps/_files/selection-request {{
   if ($request_method != POST) {{ return 405; }}
   proxy_pass {target};
  }}
  location = /api/v1/independent-apps/_files/content {{
   if ($request_method != GET) {{ return 405; }}
   proxy_read_timeout 12s;
   proxy_buffering off;
   proxy_pass {target};
  }}
{data_gateway}
  location / {{ return 404; }}
 }}
}}
"""

    def _proxy(self, spec: RuntimeSpec) -> dict | None:
        _, network, proxy = self.names(spec)
        item = self._inspect("container", proxy)
        if item:
            host = item["HostConfig"]
            binds = [mount for mount in item.get("Mounts", []) if mount.get("Type") == "bind"]
            if (
                item["Image"] != self.ingress_image
                or item["Config"].get("Labels", {}).get(_LABEL) != spec.installation_id
                or len(binds) != 1
                or any(
                    mount.get("Type") not in {"bind", "tmpfs"} for mount in item.get("Mounts", [])
                )
                or binds[0].get("Source") != str(self.root / spec.installation_id)
                or binds[0].get("Destination") != "/etc/miy"
                or binds[0].get("RW")
                or not host.get("ReadonlyRootfs")
                or host.get("Privileged")
                or set(host.get("CapDrop", [])) != {"ALL"}
                or "no-new-privileges" not in host.get("SecurityOpt", [])
                or host.get("Memory") != 134217728
                or host.get("PidsLimit") != 64
                or host.get("NanoCpus") != 500000000
                or item["Config"].get("User") != "1000:1000"
                or set(item["NetworkSettings"]["Networks"]) != {"bridge", network}
                or host.get("PortBindings")
                != {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(self.port(spec))}]}
            ):
                raise RuntimeFailure("ingress_identity_mismatch")
        return item

    def activate(self, spec: RuntimeSpec) -> None:
        self.port(spec)
        self._container(spec)
        _, network, proxy = self.names(spec)
        directory = self.root / spec.installation_id
        directory.mkdir(exist_ok=True, mode=0o755)
        config = directory / "nginx.conf"
        temporary = directory / "nginx.conf.next"
        temporary.write_text(self._configuration(spec))
        temporary.chmod(0o644)
        os.replace(temporary, config)
        item = self._proxy(spec)
        if item is None:
            self._run(
                "create",
                "--name",
                proxy,
                "--label",
                f"{_LABEL}={spec.installation_id}",
                "--network",
                "bridge",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "128m",
                "--cpus",
                "0.5",
                "--user",
                "1000:1000",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=32m",
                "--publish",
                f"127.0.0.1:{self.port(spec)}:8080",
                "--mount",
                f"type=bind,src={directory},dst=/etc/miy,readonly",
                "--entrypoint",
                "nginx",
                self.ingress_image,
                "-c",
                "/etc/miy/nginx.conf",
                "-g",
                "daemon off;",
            )
            self._run("network", "connect", "--alias", "miy-platform-gateway", network, proxy)
            self._run("start", proxy)
        else:
            if not item["State"].get("Running"):
                self._run("start", proxy)
            else:
                self._run("exec", proxy, "nginx", "-c", "/etc/miy/nginx.conf", "-s", "reload")
        for _ in range(20):
            observation = self.observe(spec)
            if observation.active and observation.healthy:
                return
            time.sleep(0.2)
        raise RuntimeFailure("activation_not_confirmed")

    def observe(self, spec: RuntimeSpec) -> Observation:
        self.port(spec)
        container, proxy = self._container(spec), self._proxy(spec)
        image = container["Image"] if container else None
        active = healthy = False
        if proxy and proxy["State"].get("Running"):
            try:
                with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                    with client.stream("GET", spec.origin + "/__miy_release") as response:
                        data = b"".join(self._bounded(response, 1024))
                        active = response.status_code == 200 and json.loads(data) == {
                            "request_id": spec.request_id,
                            "image_id": spec.image_id,
                        }
                    if active:
                        with client.stream("GET", spec.origin + spec.health_path) as response:
                            list(self._bounded(response, 65536))
                            healthy = response.status_code == 200 and bool(
                                container and container["State"].get("Running")
                            )
            except (httpx.HTTPError, ValueError):
                pass
        return Observation(active, healthy, image, container is not None, proxy is None)

    @staticmethod
    def _bounded(response, limit):
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > limit:
                raise ValueError("Response too large")
            yield chunk

    def discard(self, spec: RuntimeSpec) -> None:
        # Never remove the active target, even after an API/daemon timeout.
        observation = self.observe(spec)
        if observation.active:
            raise RuntimeFailure("active_runtime_cleanup_refused")
        name, network, proxy = self.names(spec)
        if observation.candidate_exists:
            self._run("rm", "--force", name)
        others = self._run(
            "container",
            "ls",
            "--all",
            "--filter",
            f"label={_LABEL}={spec.installation_id}",
            "--format",
            "{{.Names}}",
        )
        if set(others.splitlines()) <= {proxy}:
            if self._proxy(spec):
                self._run("rm", "--force", proxy)
            net = self._inspect("network", network)
            if (
                net
                and net.get("Internal")
                and net.get("Labels", {}).get(_LABEL) == spec.installation_id
            ):
                self._run("network", "rm", network)

    def retire(self, spec: RuntimeSpec) -> None:
        observation = self.observe(spec)
        if observation.active:
            raise RuntimeFailure("active_runtime_retirement_refused")
        if observation.candidate_exists:
            name, _, _ = self.names(spec)
            # Stateless containers retain their immutable image and DB history.
            # App shutdown handlers cannot hold the executor's capacity forever.
            self._run("rm", "--force", name)
            if self._container(spec) is not None:
                raise RuntimeFailure("retirement_not_confirmed")
