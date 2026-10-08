"""Provisioning never emits runnable settings after denied or inconclusive checks."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_remote_environments import environment

from codex_console import executor_probe as probe


class Peer:
    def __init__(self, root, failure=None):
        self.root, self.failure = root, failure
        self.files = {}
        self.commands = {}
        self.cleaned = []
        self.socket = SimpleNamespace(send=self.notify)

    async def notify(self, message):
        pass

    async def call(self, method, params):
        if method == "initialize":
            return {
                "result": {
                    "environmentInfo": {
                        "executorVersion": "0.160.1",
                        "cwd": self.root.as_uri(),
                        "platformOs": "linux",
                    }
                }
            }
        if method == "process/start":
            writable = len(params["sandbox"]["permissions"]["file_system"]["entries"]) == 2
            if writable:
                self.files[next(iter(self.files))] = base64.b64encode(b"MIY_CHILD").decode()
            self.commands[params["processId"]] = 0 if writable else 1
            return {"result": {"sandboxType": "linuxSeccomp"}}
        if method == "process/read":
            return {
                "result": {
                    "nextSeq": 0,
                    "exited": True,
                    "exitCode": self.commands[params["processId"]],
                }
            }
        if method == "process/terminate":
            self.commands.pop(params["processId"])
            return {"result": {"running": False}}
        if method == "fs/remove":
            self.cleaned.append(params["path"])
            self.files.pop(params["path"], None)
            assert params["recursive"] is False
            if self.failure == "cleanup":
                return {"error": {"message": "synthetic peer detail"}}
            return {"result": {}}
        if method == "fs/readFile":
            if params["path"] not in self.files:
                return {"error": {"message": "fixture absent"}}
            return {"result": {"dataBase64": self.files[params["path"]]}}
        if method == "fs/getMetadata":
            return {"result": {"isDirectory": True, "isSymlink": False}}
        assert method == "fs/writeFile"
        permissions = params["sandbox"]["permissions"]
        writable = (
            permissions["type"] == "managed" and len(permissions["file_system"]["entries"]) == 2
        )
        if (
            self.failure == "readonly"
            or (writable and self.failure != "workspace")
            or ("/.git/" in params["path"] and self.failure == "metadata")
        ):
            self.files[params["path"]] = params["dataBase64"]
            return {"result": {}}
        return {"error": {"message": "synthetic denial"}}


@pytest.mark.parametrize(
    "failure,code",
    [
        ("readonly", "executor_readonly_write_allowed"),
        ("workspace", "executor_workspace_write_failed"),
        ("metadata", "executor_git_metadata_writable"),
        ("cleanup", "executor_cleanup_failed"),
    ],
)
def test_failed_policy_or_cleanup_leaves_no_configuration(tmp_path, failure, code):
    root = tmp_path / "app"
    root.mkdir()
    peer = Peer(root, failure)

    async def runner(environment):
        return await probe.check(peer, root, tmp_path / "synthetic-host-canary")

    output = tmp_path / "private-config.json"
    with pytest.raises(probe.ProbeFailure, match=code):
        asyncio.run(probe.prepare(environment(root), output, runner=runner))
    assert not output.exists()
    assert peer.files == {} and peer.commands == {}
    assert all(".miy-executor-probe-" in path for path in peer.cleaned)


def test_only_completed_policy_checks_emit_private_non_overwriting_configuration(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    peer = Peer(root)

    async def runner(environment):
        return await probe.check(peer, root, tmp_path / "synthetic-host-canary")

    output = tmp_path / "private-config.json"
    selected = environment(root)
    result = asyncio.run(probe.prepare(selected, output, runner=runner))
    assert result["workspace_write"] and result["read_only"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())[0]["auth_bearer_token"] == (
        selected.auth_bearer_token.get_secret_value()
    )
    assert "token" not in json.dumps(result)
    assert peer.files == {} and peer.commands == {}
    with pytest.raises(FileExistsError):
        asyncio.run(probe.prepare(selected, output, runner=runner))


def test_capability_configuration_cannot_be_written_inside_app_source(tmp_path):
    with pytest.raises(probe.ProbeFailure, match="executor_output_path_denied"):
        asyncio.run(probe.prepare(environment(tmp_path), tmp_path / "settings.json"))
    assert not list(tmp_path.iterdir())


def test_token_input_must_be_private_regular_file(tmp_path):
    token = tmp_path / "capability"
    token.write_text("synthetic-" + "a" * 40)
    token.chmod(0o644)
    with pytest.raises(probe.ProbeFailure, match="executor_token_file_denied"):
        probe.secret_file(token)
    token.chmod(0o600)
    assert probe.secret_file(token) == token.read_text()
    link = tmp_path / "link"
    link.symlink_to(token)
    with pytest.raises(OSError):
        probe.secret_file(link)


@pytest.mark.parametrize("version", ["0.160.1", "0.160.0", "0.160.2"])
def test_reconnect_preflight_reads_exact_version_without_filesystem_or_process_calls(
    tmp_path, monkeypatch, version
):
    socket = SimpleNamespace(
        send=AsyncMock(),
        recv=AsyncMock(
            return_value=json.dumps(
                {
                    "id": 1,
                    "result": {
                        "environmentInfo": {
                            "executorVersion": version,
                            "cwd": tmp_path.as_uri(),
                            "platformOs": "linux",
                        }
                    },
                }
            )
        ),
    )
    selected = environment(tmp_path)
    seen = []

    class Connection:
        async def __aenter__(self):
            return socket

        async def __aexit__(self, *_):
            pass

    def connect(url, **options):
        seen.append((url, options))
        return Connection()

    monkeypatch.setattr(probe, "connect", connect)
    if version == "0.160.1":
        asyncio.run(probe.preflight(selected))
    else:
        with pytest.raises(probe.ProbeFailure, match="executor_version_mismatch"):
            asyncio.run(probe.preflight(selected))
    assert all(
        json.loads(call.args[0])["method"] in {"initialize", "initialized"}
        for call in socket.send.call_args_list
    )
    assert seen[0][0] == selected.exec_server_url
    assert seen[0][1]["max_size"] == 65536 and seen[0][1]["proxy"] is None
    assert seen[0][1]["additional_headers"] == {
        "Authorization": "Bearer " + selected.auth_bearer_token.get_secret_value()
    }
