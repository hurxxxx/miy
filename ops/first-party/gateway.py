"""Core-owned NGINX ingress for the fixed first-party API topology.

Only the four existing public runtime settings below are read. Router and client
ownership comes from the matching API wheel, never a second maintained route list.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import http.client
import ipaddress
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


PLATFORM = "127.0.0.1:18779"
OFFICIAL = "127.0.0.1:18780"
ENV_KEYS = (
    "MIY_APP_BIND_HOST",
    "MIY_APP_PORT",
    "MIY_API_PREFIX",
    "MIY_APP_FORWARDED_ALLOW_IPS",
)


@dataclass(frozen=True)
class GatewaySettings:
    host: str
    port: int
    api_prefix: str
    proxies: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> GatewaySettings:
        # Same host/port/exact proxy-IP support as prod-app-config.mjs.
        values = {key: os.environ.get(key, "").strip() for key in ENV_KEYS}
        host = values["MIY_APP_BIND_HOST"] or "127.0.0.1"
        raw_port = values["MIY_APP_PORT"] or "8000"
        prefix = values["MIY_API_PREFIX"] or "/api/v1"
        if host not in {"0.0.0.0", "127.0.0.1"}:
            raise ValueError("gateway_bind_host_invalid")
        if not re.fullmatch(r"[0-9]{1,5}", raw_port):
            raise ValueError("gateway_port_invalid")
        port = int(raw_port)
        if not 1 <= port <= 65535 or port in {18779, 18780}:
            raise ValueError("gateway_port_invalid")
        if not re.fullmatch(r"/[A-Za-z0-9/_-]+", prefix) or prefix.endswith("/"):
            raise ValueError("gateway_api_prefix_invalid")
        raw_proxies = values["MIY_APP_FORWARDED_ALLOW_IPS"] or "127.0.0.1"
        proxies = set()
        for value in filter(None, (item.strip() for item in raw_proxies.split(","))):
            if "%" in value:
                raise ValueError("gateway_proxy_ip_invalid")
            proxies.add(str(ipaddress.ip_address(value)))
        if not proxies:
            raise ValueError("gateway_proxy_ip_required")
        return cls(host, port, prefix, tuple(sorted(proxies)))


def render(settings: GatewaySettings, *, directory: Path) -> str:
    from miy_api.first_party_routes import nginx_client_owner_map, nginx_owner_map

    # Both generated projections come from this Core image. No settings, app,
    # database or auth/session startup is invoked by the router inventory.
    ownership = nginx_owner_map(api_prefix=settings.api_prefix) + nginx_client_owner_map()
    trusted = "\n".join(f"        {ip} 1;" for ip in settings.proxies)
    realip = "\n".join(f"    set_real_ip_from {ip};" for ip in settings.proxies)
    return f"""pid {directory}/nginx.pid;
error_log /dev/stderr warn;
worker_processes 1;
events {{ worker_connections 1024; }}
http {{
    access_log off;
    server_tokens off;
    client_body_temp_path {directory}/client-body;
    proxy_temp_path {directory}/proxy;
    fastcgi_temp_path {directory}/fastcgi;
    uwsgi_temp_path {directory}/uwsgi;
    scgi_temp_path {directory}/scgi;
{ownership}
    map "$miy_api_owner:$miy_ui_owner" $miy_backend {{
        default {PLATFORM};
        ~^official: {OFFICIAL};
        ~:official$ {OFFICIAL};
    }}
    geo $realip_remote_addr $miy_trusted_proxy {{
        default 0;
{trusted}
    }}
    map "$miy_trusted_proxy:$http_x_forwarded_proto" $miy_forwarded_proto {{
        default $scheme;
        "1:http" http;
        "1:https" https;
    }}
    map $http_upgrade $miy_upgrade_connection {{
        default upgrade;
        '' close;
    }}
{realip}
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
    server {{
        listen {settings.host}:{settings.port};
        server_name _;
        # Preserve the old direct-Uvicorn transport: app owners bound uploads.
        client_max_body_size 0;
        client_header_timeout 10s;
        client_body_timeout 60s;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $miy_forwarded_proto;
        proxy_set_header Forwarded "";
        proxy_set_header X-Forwarded-Host "";
        proxy_set_header X-Forwarded-Port "";
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $miy_upgrade_connection;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_connect_timeout 5s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_next_upstream off;
        location = /official-suite/healthz {{
            proxy_pass http://{OFFICIAL}/healthz;
        }}
        location = /official-suite/readyz {{
            proxy_pass http://{OFFICIAL}/readyz;
        }}
        location / {{
            proxy_pass http://$miy_backend;
        }}
    }}
}}
"""


def check(settings: GatewaySettings) -> None:
    for path in (
        "/healthz",
        "/readyz",
        "/official-suite/healthz",
        "/official-suite/readyz",
    ):
        connection = http.client.HTTPConnection("127.0.0.1", settings.port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("gateway_health_failed")
            response.read(4097)
        finally:
            connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Probe only fixed local health routes")
    mode.add_argument(
        "--print-config",
        action="store_true",
        help="Print the owned NGINX configuration without starting it",
    )
    args = parser.parse_args()
    settings = GatewaySettings.from_environment()
    if args.check:
        check(settings)
        return
    directory = Path(tempfile.mkdtemp(prefix="miy-first-party-gateway-", dir="/tmp"))
    directory.chmod(0o700)
    configuration = render(settings, directory=directory)
    if args.print_config:
        try:
            print(configuration, end="")
        finally:
            shutil.rmtree(directory)
        return
    path = directory / "nginx.conf"
    with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
        output.write(configuration)
    os.execv("/usr/sbin/nginx", ["nginx", "-c", str(path), "-g", "daemon off;"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError):
        print(
            "First-party gateway configuration or local health is unavailable.",
            file=sys.stderr,
        )
        sys.exit(1)
