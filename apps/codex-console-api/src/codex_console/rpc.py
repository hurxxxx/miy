"""A transport adapter, not a second Codex auth/agent/session implementation.

The official stdio protocol needs request multiplexing and server-initiated request
responses. Codex owns execution and OAuth; this adapter never inspects credentials.
"""

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from . import remote_environments
from .errors import ConsoleError
from .models import uid
from .protocol_contract import (
    remote_schemas_are_compatible,
    schemas_are_compatible,
    supports_contract_version,
)

MAX_MESSAGE_BYTES = 4 * 1024 * 1024

CONTRACT = json.loads(Path(__file__).with_name("protocol.json").read_text())
REMOTE_CONTRACT = json.loads(Path(__file__).with_name("remote_protocol.generated.json").read_text())
METHOD_SCHEMAS = {
    "thread/list": "ThreadListParams",
    "thread/read": "ThreadReadParams",
    "skills/list": "SkillsListParams",
    "thread/start": "ThreadStartParams",
    "thread/resume": "ThreadResumeParams",
    "turn/start": "TurnStartParams",
    "turn/steer": "TurnSteerParams",
    "turn/interrupt": "TurnInterruptParams",
    "model/list": "ModelListParams",
}
logger = logging.getLogger(__name__)


class CodexRPC:
    def __init__(self, binary: str, cwd: Path, on_message, on_disconnect):
        self.binary, self.cwd = binary, cwd
        self.on_message, self.on_disconnect = on_message, on_disconnect
        self.generation = uid()
        self.process = None
        self.reader = None
        self.dispatcher = None
        self.sequence = 0
        self.pending = {}
        self.events = asyncio.Queue(maxsize=2048)
        self.write_lock = asyncio.Lock()
        self.closing = False
        self.failure_task = None
        self.remote_environment = None
        self.startup_overrides = {}
        self.dynamic_requests = set()

    @property
    def connected(self):
        return self.process is not None and self.process.returncode is None and not self.closing

    async def start(self):
        environment = {
            k: os.environ[k]
            for k in ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "SHELL", "CODEX_HOME")
            if k in os.environ
        }
        if self.remote_environment:
            remote_environments.require_provider_boundary()
            # The default provider must expose no local environment. The one
            # authenticated remote endpoint is added after the native handshake.
            environment["CODEX_EXEC_SERVER_URL"] = "none"
        version = await asyncio.create_subprocess_exec(
            self.binary,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
        )
        try:
            output, _ = await asyncio.wait_for(version.communicate(), 10)
        except TimeoutError:
            version.kill()
            await version.wait()
            raise ConsoleError("codex_unavailable", 503) from None
        if version.returncode or not supports_contract_version(
            output.decode(), CONTRACT["codexVersion"]
        ):
            raise ConsoleError("codex_version_mismatch", 503)
        if (
            self.remote_environment
            and output.decode().strip() != f"codex-cli {remote_environments.REMOTE_VERSION}"
        ):
            raise ConsoleError("app_executor_version_mismatch", 503)
        with tempfile.TemporaryDirectory(prefix="codex-console-schema-") as directory:
            schema = await asyncio.create_subprocess_exec(
                self.binary,
                "app-server",
                "generate-json-schema",
                "--experimental",
                "--out",
                directory,
                cwd=self.cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
            try:
                await asyncio.wait_for(schema.wait(), 30)
            except TimeoutError:
                schema.kill()
                await schema.wait()
                raise ConsoleError("codex_version_mismatch", 503) from None
            if schema.returncode or not schemas_are_compatible(CONTRACT, Path(directory)):
                raise ConsoleError("codex_version_mismatch", 503)
            if self.remote_environment and not remote_schemas_are_compatible(
                REMOTE_CONTRACT, Path(directory)
            ):
                raise ConsoleError("app_executor_version_mismatch", 503)
        if self.remote_environment:
            from .executor_probe import ProbeFailure, preflight

            try:
                await preflight(self.remote_environment)
            except ProbeFailure as exc:
                if str(exc) == "executor_version_mismatch":
                    raise ConsoleError("app_executor_version_mismatch", 503) from None
                if str(exc) == "executor_root_mismatch":
                    raise ConsoleError("app_executor_changed", 409) from None
                raise ConsoleError("app_executor_unavailable", 503) from None
            except Exception:
                raise ConsoleError("app_executor_unavailable", 503) from None
        arguments = []
        for name, value in self.startup_overrides.items():
            arguments.extend(["-c", name + "=" + json.dumps(value)])
        self.process = await asyncio.create_subprocess_exec(
            self.binary,
            "app-server",
            "--listen",
            "stdio://",
            "-c",
            'forced_login_method="chatgpt"',
            "--disable",
            "apps",
            "--disable",
            "plugins",
            *arguments,
            cwd=self.cwd,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_MESSAGE_BYTES,
        )
        self.reader = asyncio.create_task(self._read())
        self.dispatcher = asyncio.create_task(self._dispatch())
        await self.call(
            "initialize",
            {
                "clientInfo": {"name": "miy_codex_console", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.send({"method": "initialized", "params": {}})
        if self.remote_environment:
            selected = self.remote_environment
            config = await self.call("config/read", {"cwd": str(self.cwd), "includeLayers": False})
            remote_environments.verify_overrides(config["config"])
            await self.call(
                "environment/add",
                {
                    "environmentId": remote_environments.ENVIRONMENT_ID,
                    "execServerUrl": selected.exec_server_url,
                    "authBearerToken": selected.auth_bearer_token.get_secret_value(),
                    "connectTimeoutMs": 5000,
                },
            )
            info = await self.call(
                "environment/info", {"environmentId": remote_environments.ENVIRONMENT_ID}
            )
            if info.get("cwd") != selected.source_root.as_uri():
                raise ConsoleError("app_executor_changed", 409)
            try:
                await self.call("environment/info", {"environmentId": "local"})
            except ConsoleError as exc:
                if exc.code != "codex_request_failed":
                    raise
            else:
                raise ConsoleError("app_executor_configuration", 503)

    async def send(self, message):
        if not self.connected:
            raise ConsoleError("codex_unavailable", 503)
        async with self.write_lock:
            try:
                self.process.stdin.write((json.dumps(message) + "\n").encode())
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                raise ConsoleError("codex_disconnected", 503) from None

    async def call(self, method, params):
        schema = METHOD_SCHEMAS.get(method)
        if schema:
            Draft7Validator(CONTRACT["schemas"][schema]).validate(params)
        if self.remote_environment and method.startswith("environment/"):
            name = {
                "environment/add": "EnvironmentAddParams",
                "environment/info": "EnvironmentInfoParams",
                "environment/status": "EnvironmentStatusParams",
            }.get(method)
            if name is None:
                raise ConsoleError("app_executor_configuration", 503)
            Draft7Validator(REMOTE_CONTRACT["schemas"][name]).validate(params)
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            return await asyncio.wait_for(future, 30)
        except TimeoutError:
            raise ConsoleError("codex_request_uncertain", 503) from None
        finally:
            self.pending.pop(request_id, None)

    async def respond(self, request_id, result):
        if request_id in self.dynamic_requests:
            Draft7Validator(REMOTE_CONTRACT["schemas"]["DynamicToolCallResponse"]).validate(result)
        await self.send({"id": request_id, "result": result})
        self.dynamic_requests.discard(request_id)

    async def _read(self):
        reason = "codex_disconnected"
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise TypeError("Invalid protocol envelope")
                if "id" in message and type(message["id"]) not in (int, str):
                    raise TypeError("Invalid protocol request ID")
                if "method" in message:
                    if (
                        not isinstance(message["method"], str)
                        or not message["method"]
                        or "result" in message
                        or "error" in message
                    ):
                        raise TypeError("Invalid protocol method envelope")
                    if self.remote_environment and message["method"] == "item/tool/call":
                        if "id" not in message:
                            raise TypeError("Dynamic tools require a request identity")
                        Draft7Validator(
                            REMOTE_CONTRACT["schemas"]["DynamicToolCallParams"]
                        ).validate(message.get("params"))
                        if len(self.dynamic_requests) >= 2048:
                            raise TypeError("Too many dynamic tool requests")
                        self.dynamic_requests.add(message["id"])
                elif "id" not in message or ("result" in message) == ("error" in message):
                    raise TypeError("Invalid protocol response envelope")
                if "method" not in message and "id" in message:
                    future = self.pending.get(message["id"])
                    if future and not future.done():
                        if "error" in message:
                            # Upstream errors may contain prompts, commands or credentials.
                            future.set_exception(ConsoleError("codex_request_failed", 502))
                        else:
                            future.set_result(message.get("result", {}))
                else:
                    self.events.put_nowait(message)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            RecursionError,
            TypeError,
            ValidationError,
        ):
            reason = "codex_protocol_error"
        except ValueError:
            reason = "codex_output_limit"
        except asyncio.QueueFull:
            reason = "codex_event_overflow"
        except OSError:
            reason = "codex_disconnected"
        finally:
            await self._failed(reason)

    async def _dispatch(self):
        try:
            while True:
                message = await self.events.get()
                await self.on_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Fail closed if durable event handling fails. Never let an unobserved turn continue.
            # Log only the exception class; its text and event payload can contain secrets.
            await self._failed("codex_event_failed", type(exc).__name__)

    async def _failed(self, reason, exception_type=None):
        if self.closing:
            return
        self.closing = True
        logger.warning(
            "Codex transport stopped: reason=%s exception_type=%s returncode=%s",
            reason,
            exception_type,
            self.process.returncode if self.process else None,
        )
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConsoleError("codex_disconnected", 503))
        for task in (self.reader, self.dispatcher):
            if task and task is not asyncio.current_task():
                task.cancel()
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
        # Reconnecting may close/cancel this reader while the durable callback is
        # waiting for the runtime gate. Preserve that callback across transport teardown.
        self.failure_task = asyncio.create_task(self.on_disconnect(reason))
        await asyncio.shield(self.failure_task)

    async def close(self):
        self.closing = True
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self.reader, self.dispatcher):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
