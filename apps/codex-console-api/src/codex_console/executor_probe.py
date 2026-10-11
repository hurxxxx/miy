"""Bounded operator checks for the pinned, experimental native executor protocol.

This is a provisioning check, never an alternative execution backend. It emits no
configuration unless native read-only and workspace-write policies both work.
"""

import asyncio
import base64
import json
import os
import stat
import tempfile
import uuid
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from .remote_environments import REMOTE_VERSION

SOCKET_OPTIONS = {"proxy": None, "open_timeout": 5, "close_timeout": 3, "max_size": 65536}


class ProbeFailure(Exception):
    """Public codes contain neither peer responses nor credentials."""


class Peer:
    def __init__(self, socket):
        self.socket = socket
        self.sequence = 0

    async def call(self, method, params):
        self.sequence += 1
        await self.socket.send(
            json.dumps({"id": self.sequence, "method": method, "params": params})
        )
        async with asyncio.timeout(15):
            for _ in range(256):
                message = json.loads(await self.socket.recv())
                if (
                    type(message.get("id")) is int
                    and message["id"] == self.sequence
                    and "method" not in message
                ):
                    return message
        raise ProbeFailure("executor_protocol_invalid")


def sandbox(root, writable):
    entries = [{"path": {"type": "path", "path": "file:///"}, "access": "read"}]
    if writable:
        entries.append({"path": {"type": "path", "path": root.as_uri()}, "access": "write"})
    return {
        "permissions": {
            "type": "managed",
            "file_system": {"type": "restricted", "entries": entries},
            "network": "restricted",
        },
        "cwd": root.as_uri(),
        "workspaceRoots": [root.as_uri()],
        "windowsSandboxLevel": "disabled",
        "useLegacyLandlock": False,
    }


def required(response, code):
    if "result" not in response or "error" in response:
        raise ProbeFailure(code)
    return response["result"]


async def command(peer, root, policy, script, *arguments):
    process_id = "miy-probe-" + uuid.uuid4().hex
    try:
        started = required(
            await peer.call(
                "process/start",
                {
                    "processId": process_id,
                    "argv": ["/bin/sh", "-c", script, "miy-probe", *arguments],
                    "cwd": root.as_uri(),
                    "env": {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
                    "envPolicy": {
                        "inherit": "none",
                        "ignoreDefaultExcludes": False,
                        "exclude": [],
                        "set": {},
                        "includeOnly": [],
                    },
                    "tty": False,
                    "sandbox": policy,
                },
            ),
            "executor_command_failed",
        )
        if started.get("sandboxType") != "linuxSeccomp":
            raise ProbeFailure("executor_policy_unenforced")
        sequence = 0
        for _ in range(5):
            result = required(
                await peer.call(
                    "process/read",
                    {
                        "processId": process_id,
                        "afterSeq": sequence,
                        "maxBytes": 1024,
                        "waitMs": 1000,
                    },
                ),
                "executor_command_failed",
            )
            sequence = result["nextSeq"]
            if result.get("exited"):
                return result.get("exitCode")
        raise ProbeFailure("executor_command_timeout")
    finally:
        required(
            await peer.call("process/terminate", {"processId": process_id}),
            "executor_cleanup_failed",
        )


async def initialize(peer, root):
    initialized = required(
        await peer.call("initialize", {"clientName": "miy-executor-provisioning"}),
        "executor_initialize_failed",
    )
    info = initialized.get("environmentInfo") or {}
    if info.get("executorVersion") != REMOTE_VERSION:
        raise ProbeFailure("executor_version_mismatch")
    if info.get("cwd") != root.as_uri() or info.get("platformOs") != "linux":
        raise ProbeFailure("executor_root_mismatch")
    await peer.socket.send(json.dumps({"method": "initialized", "params": {}}))
    return info


async def preflight(environment):
    """Read-only metadata check on every product transport connection.

    App-server's EnvironmentInfoResponse omits executorVersion. Reuse the same
    pinned official initialize request used by provisioning; never send fs/exec here.
    """
    async with asyncio.timeout(10):
        async with connect(
            environment.exec_server_url,
            additional_headers={
                "Authorization": "Bearer " + environment.auth_bearer_token.get_secret_value()
            },
            **SOCKET_OPTIONS,
        ) as socket:
            return await initialize(Peer(socket), environment.source_root)


async def check(peer, root, canary):
    await initialize(peer, root)
    fixture = root / (".miy-executor-probe-" + uuid.uuid4().hex)
    metadata_fixture = root / ".git" / fixture.name
    readonly, writable = sandbox(root, False), sandbox(root, True)
    unconfined = {**writable, "permissions": {"type": "disabled"}}
    encoded = base64.b64encode(b"MIY_EXECUTOR_SYNTHETIC_PROBE").decode()
    try:
        # No recursive cleanup is ever sent. Every path is a new, random fixture.
        attempted = await peer.call(
            "fs/writeFile",
            {
                "path": fixture.as_uri(),
                "dataBase64": encoded,
                "followSymlinks": False,
                "sandbox": readonly,
            },
        )
        if "error" not in attempted:
            raise ProbeFailure("executor_readonly_write_allowed")
        required(
            await peer.call(
                "fs/writeFile",
                {
                    "path": fixture.as_uri(),
                    "dataBase64": encoded,
                    "followSymlinks": False,
                    "sandbox": writable,
                },
            ),
            "executor_workspace_write_failed",
        )
        content = required(
            await peer.call("fs/readFile", {"path": fixture.as_uri(), "sandbox": readonly}),
            "executor_read_failed",
        )
        if content.get("dataBase64") != encoded:
            raise ProbeFailure("executor_read_mismatch")
        if await command(peer, root, readonly, 'printf forbidden > "$1"', str(fixture)) == 0:
            raise ProbeFailure("executor_readonly_command_allowed")
        after_readonly = required(
            await peer.call("fs/readFile", {"path": fixture.as_uri(), "sandbox": readonly}),
            "executor_read_failed",
        )
        if after_readonly.get("dataBase64") != encoded:
            raise ProbeFailure("executor_readonly_command_changed_file")
        # A native child process must retain the workspace policy.
        if (
            await command(
                peer,
                root,
                writable,
                '/bin/sh -c \'printf MIY_CHILD > "$1"\' miy-child "$1"',
                str(fixture),
            )
            != 0
        ):
            raise ProbeFailure("executor_workspace_command_failed")
        content = required(
            await peer.call("fs/readFile", {"path": fixture.as_uri(), "sandbox": readonly}),
            "executor_child_read_failed",
        )
        if content.get("dataBase64") != base64.b64encode(b"MIY_CHILD").decode():
            raise ProbeFailure("executor_child_write_failed")
        # Outer confinement must protect metadata even for an explicitly approved yolo turn.
        git_directory = required(
            await peer.call(
                "fs/getMetadata",
                {"path": (root / ".git").as_uri(), "followSymlinks": False, "sandbox": unconfined},
            ),
            "executor_git_metadata_missing",
        )
        if not git_directory.get("isDirectory") or git_directory.get("isSymlink"):
            raise ProbeFailure("executor_git_metadata_invalid")
        metadata = await peer.call(
            "fs/writeFile",
            {
                "path": metadata_fixture.as_uri(),
                "dataBase64": encoded,
                "followSymlinks": False,
                "sandbox": unconfined,
            },
        )
        if "error" not in metadata:
            raise ProbeFailure("executor_git_metadata_writable")
        host_file = await peer.call(
            "fs/readFile",
            {
                "path": canary.as_uri(),
                "sandbox": unconfined,
            },
        )
        if "error" not in host_file:
            raise ProbeFailure("executor_host_files_visible")
        return {
            "version": REMOTE_VERSION,
            "read_only": True,
            "workspace_write": True,
            "child_process": True,
            "git_metadata_read_only": True,
            "host_canary_absent": True,
        }
    finally:
        failures = []
        for path in (fixture, metadata_fixture):
            try:
                required(
                    await peer.call(
                        "fs/remove",
                        {
                            "path": path.as_uri(),
                            "force": True,
                            "recursive": False,
                            "followSymlinks": False,
                            "sandbox": unconfined,
                        },
                    ),
                    "executor_cleanup_failed",
                )
            except Exception:
                failures.append(path)
        if failures:
            raise ProbeFailure("executor_cleanup_failed")


async def probe(environment):
    url = environment.exec_server_url
    # Pinned native capability-token auth or a confined operator proxy must
    # reject unauthenticated connections before exposing the executor.
    try:
        async with connect(url, **SOCKET_OPTIONS):
            raise ProbeFailure("executor_unauthenticated")
    except InvalidStatus as error:
        if error.response.status_code not in {401, 403}:
            raise ProbeFailure("executor_auth_check_failed") from None
    with tempfile.TemporaryDirectory(prefix="miy-executor-host-canary-") as temporary:
        canary = Path(temporary) / "synthetic.txt"
        canary.write_text("synthetic host-only fixture")
        async with connect(
            url,
            additional_headers={
                "Authorization": "Bearer " + environment.auth_bearer_token.get_secret_value()
            },
            **SOCKET_OPTIONS,
        ) as socket:
            return await check(Peer(socket), environment.source_root, canary)


def secret_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ProbeFailure("executor_token_file_denied")
        value = stream.read(514).strip()
    if not 32 <= len(value) <= 512 or "\n" in value or "\r" in value:
        raise ProbeFailure("executor_token_file_denied")
    return value


async def prepare(environment, output, *, runner=probe):
    output = Path(output)
    parent = output.parent.stat()
    if (
        not output.is_absolute()
        or output.resolve() != output
        or output.is_relative_to(environment.source_root)
        or parent.st_uid != os.getuid()
        or parent.st_mode & 0o077
    ):
        raise ProbeFailure("executor_output_path_denied")
    result = await runner(environment)
    value = environment.model_dump(mode="json")
    value["auth_bearer_token"] = environment.auth_bearer_token.get_secret_value()
    # Never print the configuration or overwrite an existing operator artifact.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps([value], separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise
    return result
