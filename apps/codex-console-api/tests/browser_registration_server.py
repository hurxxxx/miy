"""Opt-in browser fixture with real WB auth/storage and a synthetic loopback Core.

Run from apps/codex-console-api:
  python tests/browser_registration_server.py [--core-port 0]
The usual MIY_CODEX_CONSOLE_PORT/BASE_PATH select the WB listener. Existing
browser_server.py remains unchanged by default. Only this fixture exposes the
authenticated /__test__/registration-* controls; no product service installs them.
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import signal
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import browser_server
from fastapi import Request
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from codex_console import auth, registration, registration_source
from codex_console.config import Settings
from codex_console.errors import ConsoleError
from codex_console.models import now
from codex_console.remote_environments import REMOTE_VERSION

ACTOR = UUID("90d27016-9223-4e50-b2cb-2a43afef70f7")
PREFIX = "/api/v1/independent-apps/bootstrap-authorizations"


def instant():
    return datetime.now(UTC)


@contextmanager
def executor_metadata(environment):
    """Expose only real loopback initialize metadata for this synthetic executor."""
    bearer = ("Bearer " + environment.auth_bearer_token.get_secret_value()).encode()

    def authorize(connection, request):
        values = request.headers.get_all("Authorization")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), bearer):
            return connection.respond(401, "Unauthorized\n")

    def handler(socket):
        try:
            message = json.loads(socket.recv(timeout=5))
            if (
                not isinstance(message, dict)
                or message.get("method") != "initialize"
                or type(message.get("id")) is not int
            ):
                socket.close(1008, "Initialize only")
                return
            socket.send(
                json.dumps(
                    {
                        "id": message["id"],
                        "result": {
                            "environmentInfo": {
                                "executorVersion": REMOTE_VERSION,
                                "cwd": environment.source_root.as_uri(),
                                "platformOs": "linux",
                            }
                        },
                    }
                )
            )
            if json.loads(socket.recv(timeout=5)) != {"method": "initialized", "params": {}}:
                socket.close(1008, "Initialize only")
        except (ConnectionClosed, TimeoutError, ValueError, TypeError):
            socket.close(1008, "Invalid metadata request")

    with serve(
        handler,
        "127.0.0.1",
        0,
        process_request=authorize,
        compression=None,
        open_timeout=5,
        close_timeout=3,
        max_size=65536,
    ) as listener:
        worker = Thread(target=listener.serve_forever, daemon=True)
        worker.start()
        try:
            yield environment.model_copy(
                update={"exec_server_url": f"ws://127.0.0.1:{listener.socket.getsockname()[1]}"}
            )
        finally:
            listener.shutdown()
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("Synthetic executor listener cleanup failed")


class SyntheticCore:
    """Only synthetic public metadata and temporary test credentials, never a MIY DB."""

    def __init__(self):
        self.lock = Lock()
        self.audience = None
        self.issuer = None
        self.authorizations = {}
        self.receipts = {}
        self.exchange_count = 0
        self.receipt_count = 0
        self.callback_count = 0
        self.callback_origin = None
        self.callback_had_cookie = None
        self.drop_exchange_once = False

    def consent(self, query):
        values = parse_qs(query, strict_parsing=True, keep_blank_values=True, max_num_fields=9)
        required = {
            "v",
            "request_id",
            "operation_id",
            "audience",
            "code_challenge",
            "app_id",
            "development_origin",
            "runtime_profile",
            "requested_permissions",
        }
        if set(values) != required or any(len(value) != 1 for value in values.values()):
            raise ValueError()
        value = {key: items[0] for key, items in values.items()}
        if (
            value["v"] != "1"
            or value["audience"] != self.audience
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value["code_challenge"])
        ):
            raise ValueError()
        request_id, operation_id = str(UUID(value["request_id"])), str(UUID(value["operation_id"]))
        policy = registration.Policy(
            app_id=value["app_id"],
            origin=registration.Begin(origin=value["development_origin"]).origin,
            runtime_profile=value["runtime_profile"],
            requested_permissions=sorted(filter(None, value["requested_permissions"].split(","))),
        ).model_dump(mode="json")
        with self.lock:
            if request_id in self.authorizations:
                raise ValueError()
            record = {
                "schema_version": 1,
                "id": str(uuid4()),
                "request_id": request_id,
                "operation_id": operation_id,
                "actor_user_id": str(ACTOR),
                "audience": self.audience,
                "policy": policy,
                "expires_at": (instant() + timedelta(seconds=300)).isoformat(),
                "code": "miyrc_" + secrets.token_urlsafe(32),
                "code_challenge": value["code_challenge"],
                "code_deadline": instant() + timedelta(seconds=120),
                "exchanged": False,
            }
            self.authorizations[request_id] = record
        # A script-free form makes the browser supply its real Origin header.
        callback = self.audience + registration.CALLBACK
        body = (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>Synthetic MIY approval</title></head><body>"
            "<h1>Synthetic MIY registration approval</h1>"
            "<p>This disposable fixture approves one inactive personal app.</p>"
            f'<p data-testid="registration-app">{escape(policy["app_id"])}</p>'
            f'<form method="post" action="{escape(callback, quote=True)}">'
            f'<input type="hidden" name="request_id" value="{request_id}">'
            f'<input type="hidden" name="code" value="{record["code"]}">'
            '<button type="submit">Approve fixture registration</button></form></body></html>'
        )
        return body.encode()

    def exchange(self, body):
        with self.lock:
            if set(body) != {"schema_version", "request_id", "audience", "code", "code_verifier"}:
                raise ValueError()
            record = self.authorizations.get(body["request_id"])
            verifier = body["code_verifier"]
            if not isinstance(verifier, str) or not re.fullmatch(
                r"[A-Za-z0-9._~-]{43,128}", verifier
            ):
                raise ValueError()
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            if (
                not record
                or body["schema_version"] != 1
                or record["exchanged"]
                or body["audience"] != record["audience"]
                or body["code"] != record["code"]
                or record["code_deadline"] <= instant()
                or not hmac.compare_digest(challenge, record["code_challenge"])
            ):
                raise ValueError()
            record["exchanged"] = True
            record["token"] = "miyrg_" + secrets.token_urlsafe(32)
            self.exchange_count += 1
            drop, self.drop_exchange_once = self.drop_exchange_once, False
            result = {
                key: record[key]
                for key in (
                    "schema_version",
                    "id",
                    "request_id",
                    "operation_id",
                    "actor_user_id",
                    "audience",
                    "policy",
                    "expires_at",
                    "token",
                )
            }
            return result, drop

    def receipt(self, grant_id, authorization):
        with self.lock:
            row = next((row for row in self.authorizations.values() if row["id"] == grant_id), None)
            if (
                not row
                or not row.get("token")
                or authorization != "Bearer " + row["token"]
                or datetime.fromisoformat(row["expires_at"]) <= instant()
            ):
                return 401, {"code": "synthetic_registration_unauthenticated"}
            self.receipt_count += 1
            result = self.receipts.get(row["operation_id"])
            return (200, result) if result else (404, {"code": "synthetic_not_found"})


def handler_for(core):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Query metadata, authorization headers and form bodies are not logged.

        def send(self, status, value, *, html=False):
            body = value if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header(
                "Content-Type", "text/html; charset=utf-8" if html else "application/json"
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "origin")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; form-action " + core.audience + registration.CALLBACK,
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path == "/apps/authorize-registration":
                try:
                    return self.send(200, core.consent(target.query), html=True)
                except (ValueError, KeyError, TypeError):
                    return self.send(400, {"code": "synthetic_invalid_consent"})
            if target.path == "/api/v1/integrations/apps":
                return self.send(
                    200,
                    {
                        "schema_version": 1,
                        "registration_status_version": 1,
                        "items": [],
                        "total": 0,
                        "page": 1,
                        "page_size": 200,
                        "catalog_revision": "synthetic-registration-catalog-v1",
                        "generated_at": instant().isoformat(),
                    },
                )
            match = re.fullmatch(re.escape(PREFIX) + r"/([0-9a-f-]{36})/receipt", target.path)
            if match:
                status, response = core.receipt(match[1], self.headers.get("Authorization"))
                return self.send(status, response)
            return self.send(404, {"code": "synthetic_not_found"})

        def do_POST(self):
            if self.path != PREFIX + "/exchange":
                return self.send(404, {"code": "synthetic_not_found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError()
                result, drop = core.exchange(json.loads(self.rfile.read(length)))
            except (ValueError, KeyError, TypeError):
                return self.send(401, {"code": "synthetic_exchange_rejected"})
            if drop:
                self.close_connection = True
                return  # Model a consumed code whose response never reached WB.
            return self.send(200, result)

    return Handler


def install(app, settings, app_source, core):
    def owner(request):
        csrf = None if request.method == "GET" else request.headers.get("x-csrf-token", "")
        if not auth.authenticate(app.state.factory, request.cookies.get(auth.COOKIE), csrf):
            raise ConsoleError("unauthenticated", 401)

    @app.middleware("http")
    async def observe_callback(request, call_next):
        if (
            request.url.path == settings.base_path + registration.CALLBACK
            and request.method == "POST"
        ):
            with core.lock:
                core.callback_count += 1
                core.callback_origin = request.headers.get("origin")
                core.callback_had_cookie = auth.COOKIE in request.cookies
        return await call_next(request)

    @app.get("/__test__/registration-fixture")
    def information(request: Request):
        owner(request)
        with core.lock:
            return {
                "issuer": core.issuer,
                "actor_user_id": str(ACTOR),
                "app_id": "sample-app",
                "repository_root": str(app_source),
                "exchange_count": core.exchange_count,
                "receipt_count": core.receipt_count,
                "callback_count": core.callback_count,
                "callback_origin": core.callback_origin,
                "callback_had_cookie": core.callback_had_cookie,
            }

    @app.post("/__test__/registration-mode")
    async def mode(request: Request):
        owner(request)
        body = await request.json()
        if body not in ({"mode": "normal"}, {"mode": "drop_exchange_once"}):
            raise ConsoleError("invalid_input", 422)
        with core.lock:
            core.drop_exchange_once = body["mode"] == "drop_exchange_once"
        return {"ok": True}

    @app.post("/__test__/registration-history/{task_id}")
    async def historical(task_id: UUID, request: Request):
        """Synthetic response loss only; source/manifest/SQLite paths remain real."""
        owner(request)
        key = str(task_id)
        registration.session_gate(app.state.factory, key, request.cookies.get(auth.COOKIE))
        draft = await asyncio.to_thread(
            registration_source.snapshot, settings, app.state.factory, key
        )
        with app.state.factory.begin() as db:
            _, row = registration.require(
                db, key, session_hash=auth.digest(request.cookies[auth.COOKIE])
            )
            if not row.policy or row.request_body:
                raise ConsoleError("registration_request_conflict", 409)
            row.request_body = {
                "operation_id": row.operation_id,
                "definition": draft.definition,
                "source_revision": draft.source_revision,
                "origin": row.policy["origin"],
                "granted_permissions": [],
            }
            row.state, row.receipt, row.updated_at = "unknown", None, now()
            receipt = {
                "operation_id": row.operation_id,
                "app_id": draft.app_id,
                "installation_id": str(uuid4()),
                "definition_digest": draft.definition_digest,
                "source_revision": draft.source_revision,
                "created_at": instant().isoformat(),
            }
        with core.lock:
            core.receipts[receipt["operation_id"]] = receipt
        return {"state": "unknown", "receipt": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-port", type=int, default=0)
    arguments = parser.parse_args()
    core = SyntheticCore()
    server = ThreadingHTTPServer(("127.0.0.1", arguments.core_port), handler_for(core))
    core.issuer = f"http://localhost:{server.server_port}"
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    executors = ExitStack()

    def configure(settings):
        core.audience = settings.origin + settings.base_path
        environment = executors.enter_context(
            executor_metadata(settings.app_execution_environments[0])
        )
        return Settings(
            **(
                settings.model_dump()
                | {
                    "registration_authorization_enabled": True,
                    "miy_api_origin": core.issuer,
                    "miy_api_key": "synthetic-registration-metadata-only",
                    "sso_subjects": {core.issuer: ACTOR},
                    "app_execution_environments": [environment],
                }
            ),
            _env_file=None,
        )

    try:
        browser_server.main(
            configure=configure,
            install_fixture=lambda app, cfg, root: install(app, cfg, root, core),
        )
    finally:
        # The browser runner can signal both uv's process group and its child.
        # Finish this owned listener's cleanup even if a second SIGINT arrives.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            try:
                executors.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
        finally:
            signal.signal(signal.SIGINT, previous)


if __name__ == "__main__":
    main()
