import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from codex_console import remote_environments
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.protocol_contract import (
    COMPATIBILITY_SCHEMA_NAMES,
    REMOTE_SCHEMA_NAMES,
    build_contract,
    build_remote_contract,
)
from codex_console.rpc import CodexRPC


@pytest.mark.parametrize(
    ("version", "local_exposed", "preflight_error", "accepted"),
    [
        ("0.160.1", False, None, True),
        ("0.160.0", False, None, False),
        ("0.160.2", False, None, False),
        ("0.160.1", True, None, False),
        ("0.160.1", False, "version", False),
        ("0.160.1", False, "connection", False),
    ],
)
def test_remote_rpc_requires_exact_version_disables_host_and_checks_executor_identity(
    tmp_path, monkeypatch, version, local_exposed, preflight_error, accepted
):
    import codex_console.executor_probe as executor_probe
    import codex_console.rpc as module

    failure = (
        executor_probe.ProbeFailure("executor_version_mismatch")
        if preflight_error == "version"
        else OSError("synthetic peer unavailable")
        if preflight_error
        else None
    )
    checked = AsyncMock(side_effect=failure)
    monkeypatch.setattr(executor_probe, "preflight", checked)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "host-auth-home"))
    schema = {"type": "object", "properties": {}, "definitions": {}}
    baseline = tmp_path / "schema"
    baseline.mkdir()
    names = set(COMPATIBILITY_SCHEMA_NAMES) | set(REMOTE_SCHEMA_NAMES)
    for name in names:
        (baseline / (name + ".json")).write_text(json.dumps(schema))
    monkeypatch.setattr(module, "CONTRACT", build_contract("0.159.2", baseline))
    monkeypatch.setattr(module, "REMOTE_CONTRACT", build_remote_contract("0.160.1", baseline))
    config = {
        "features": remote_environments.SAFE_FEATURES,
        "mcp_servers": {},
        "notify": [],
        "allow_login_shell": False,
        "shell_environment_policy": {
            "inherit": "none",
            "set": {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
        },
    }

    async def run():
        spawns = []
        stream = asyncio.StreamReader()
        replies = (
            {"id": 1, "result": {}},
            {"id": 2, "result": {"config": config}},
            {"id": 3, "result": {}},
            {"id": 4, "result": {"cwd": tmp_path.as_uri()}},
            {
                "id": 5,
                **(
                    {"result": {"cwd": "file:///"}}
                    if local_exposed
                    else {"error": {"code": -32603, "message": "unknown local environment"}}
                ),
            },
        )

        def written(raw):
            message = json.loads(raw)
            if "id" in message:
                stream.feed_data((json.dumps(replies[message["id"] - 1]) + "\n").encode())

        process = SimpleNamespace(
            returncode=None,
            stdout=stream,
            stdin=SimpleNamespace(write=Mock(side_effect=written), drain=AsyncMock()),
            wait=AsyncMock(return_value=0),
        )
        process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))

        async def spawn(*args, **kwargs):
            spawns.append((args, kwargs))
            if args[1:] == ("--version",):
                return SimpleNamespace(
                    returncode=0,
                    communicate=AsyncMock(return_value=(f"codex-cli {version}".encode(), b"")),
                )
            if args[1:3] == ("app-server", "generate-json-schema"):
                from pathlib import Path

                for name in names:
                    (Path(args[-1]) / (name + ".json")).write_text(json.dumps(schema))
                return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        rpc = CodexRPC("synthetic-codex", tmp_path, AsyncMock(), AsyncMock())
        rpc.remote_environment = AppExecutionEnvironment(
            key="test-app",
            source_root=tmp_path,
            exec_server_url="ws://127.0.0.1:19391",
            auth_bearer_token="synthetic-token-" + "x" * 32,
        )
        rpc.startup_overrides = remote_environments.overrides({})
        try:
            if not accepted:
                code = (
                    "app_executor_configuration"
                    if local_exposed
                    else "app_executor_unavailable"
                    if preflight_error == "connection"
                    else "app_executor_version_mismatch"
                )
                with pytest.raises(ConsoleError, match=code):
                    await rpc.start()
                if preflight_error:
                    assert len(spawns) == 2  # No native app-server after failed preflight.
                return
            await rpc.start()
            checked.assert_awaited_once_with(rpc.remote_environment)
            args, kwargs = spawns[-1]
            assert kwargs["env"]["CODEX_EXEC_SERVER_URL"] == "none"
            assert "features.hooks=false" in args
            assert "features.skip_host_skill_discovery=true" in args
            messages = [json.loads(call.args[0]) for call in process.stdin.write.call_args_list]
            added = next(m for m in messages if m.get("method") == "environment/add")
            assert added["params"]["environmentId"] == remote_environments.ENVIRONMENT_ID
            assert (
                added["params"]["authBearerToken"]
                == rpc.remote_environment.auth_bearer_token.get_secret_value()
            )
            assert not any(m.get("method") == "thread/start" for m in messages)
        finally:
            await rpc.close()

    asyncio.run(run())
