import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from codex_console.errors import ConsoleError
from codex_console.protocol_contract import COMPATIBILITY_SCHEMA_NAMES, build_contract
from codex_console.rpc import CodexRPC


@pytest.mark.parametrize(
    ("version", "drift", "accepted"),
    [
        ("0.159.2", None, True),
        ("0.160.0", None, True),
        ("0.159.1", None, False),
        ("0.160.0-alpha.1", None, False),
        ("0.160.0", "nested-permission", False),
        ("0.160.0", "missing-permission", False),
        ("0.160.0", "invalid-json", False),
        ("0.160.0", "generation-failed", False),
    ],
)
def test_start_requires_stable_version_and_exact_contract_before_handshake(
    tmp_path, monkeypatch, version, drift, accepted
):
    import codex_console.rpc as rpc_module

    schema = {
        "type": "object",
        "properties": {"permissions": {"$ref": "#/definitions/Permissions"}},
        "definitions": {"Permissions": {"type": "object", "additionalProperties": False}},
    }
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    for name in COMPATIBILITY_SCHEMA_NAMES:
        (baseline / f"{name}.json").write_text(json.dumps(schema))
    monkeypatch.setattr(rpc_module, "CONTRACT", build_contract("0.159.2", baseline))

    async def run():
        calls = []
        stream = asyncio.StreamReader()
        stream.feed_data(b'{"id":1,"result":{"userAgent":"test"}}\n')
        process = SimpleNamespace(
            returncode=None,
            stdout=stream,
            stdin=SimpleNamespace(write=Mock(), drain=AsyncMock()),
            wait=AsyncMock(return_value=0),
        )
        process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))

        async def spawn(*args, **kwargs):
            calls.append(args)
            if args[1:] == ("--version",):
                return SimpleNamespace(
                    returncode=0,
                    communicate=AsyncMock(return_value=(f"codex-cli {version}".encode(), b"")),
                )
            if args[1:3] == ("app-server", "generate-json-schema"):
                target = Path(args[-1])
                for name in COMPATIBILITY_SCHEMA_NAMES:
                    (target / f"{name}.json").write_text(json.dumps(schema))
                permission = target / "PermissionsRequestApprovalResponse.json"
                if drift == "nested-permission":
                    changed = json.loads(permission.read_text())
                    changed["definitions"]["Permissions"]["additionalProperties"] = True
                    permission.write_text(json.dumps(changed))
                elif drift == "missing-permission":
                    permission.unlink()
                elif drift == "invalid-json":
                    permission.write_text("{")
                return SimpleNamespace(
                    returncode=1 if drift == "generation-failed" else 0,
                    wait=AsyncMock(return_value=0),
                )
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        rpc = CodexRPC("test-codex", tmp_path, AsyncMock(), AsyncMock())
        try:
            if accepted:
                await rpc.start()
                assert rpc.connected
                assert "--experimental" in calls[1]
                assert calls[2][1:] == (
                    "app-server", "--listen", "stdio://", "-c",
                    'forced_login_method="chatgpt"', "--disable", "apps", "--disable", "plugins",
                )
                messages = [json.loads(call.args[0]) for call in process.stdin.write.call_args_list]
                assert messages[0]["method"] == "initialize"
                assert messages[0]["params"]["capabilities"] == {"experimentalApi": True}
                assert messages[1] == {"method": "initialized", "params": {}}
            else:
                with pytest.raises(ConsoleError, match="codex_version_mismatch"):
                    await rpc.start()
                assert rpc.process is None
                assert all("--listen" not in args for args in calls)
                process.stdin.write.assert_not_called()
        finally:
            await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "line",
    [
        b"[]",
        b"{}",
        b'{"id":1}',
        b'{"id":[],"result":{}}',
        b'{"id":true,"result":{}}',
        b'{"id":1.0,"result":{}}',
        b'{"id":1,"result":{},"error":{"code":-1,"message":"PRIVATE"}}',
        b'{"method":null}',
        b'{"method":42,"params":{}}',
        b'{"method":"event","id":null,"params":{}}',
        b'{"method":"event","result":{}}',
        b'{"id":1,"result":"\xff"}',
        b'{"id":1,"result":' + b"[" * 20000 + b"]" * 20000 + b"}",
    ],
    ids=[
        "array",
        "empty",
        "no-result",
        "list-id",
        "boolean-id",
        "float-id",
        "ambiguous-response",
        "null-method",
        "numeric-method",
        "null-id",
        "mixed-envelope",
        "invalid-utf8",
        "excessive-nesting",
    ],
)
def test_invalid_native_envelope_fails_closed_without_acknowledging_request(line, caplog):
    async def run():
        reasons = []

        async def disconnected(reason):
            reasons.append(reason)

        rpc = CodexRPC("unused", Path("/"), None, disconnected)
        stream = asyncio.StreamReader()
        stream.feed_data(line + b"\n")
        stream.feed_eof()
        rpc.process = SimpleNamespace(returncode=None, stdout=stream, terminate=Mock())
        pending = asyncio.get_running_loop().create_future()
        rpc.pending[1] = pending
        try:
            await rpc._read()
        finally:
            # Retrieve a failed future even when the reader itself unexpectedly raises.
            if pending.done() and not pending.cancelled():
                pending.exception()
        assert reasons == ["codex_protocol_error"]
        assert not rpc.connected
        assert rpc.events.empty()
        rpc.process.terminate.assert_called_once()
        with pytest.raises(ConsoleError, match="codex_disconnected"):
            await pending

    asyncio.run(run())
    assert "PRIVATE" not in caplog.text


def test_valid_envelopes_preserve_native_ids_null_results_and_unknown_notifications():
    async def run():
        async def disconnected(reason):
            assert reason == "codex_disconnected"

        rpc = CodexRPC("unused", Path("/"), None, disconnected)
        stream = asyncio.StreamReader()
        messages = [
            {"id": 1, "result": None},
            {"id": "native-id", "method": "future/approval", "params": {}},
            {"method": "future/notification", "params": {}},
            {"id": 999, "result": {}},  # A response to an expired call is harmless.
        ]
        stream.feed_data(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
        stream.feed_eof()
        rpc.process = SimpleNamespace(returncode=None, stdout=stream, terminate=Mock())
        rpc.pending[1] = asyncio.get_running_loop().create_future()
        await rpc._read()
        assert await rpc.pending[1] is None
        assert [rpc.events.get_nowait(), rpc.events.get_nowait()] == messages[1:3]

    asyncio.run(run())


def test_event_queue_overflow_disconnects_and_fails_pending_calls():
    async def run():
        reasons = []

        async def disconnected(reason):
            reasons.append(reason)

        rpc = CodexRPC("unused", Path("/"), None, disconnected)
        rpc.events = asyncio.Queue(maxsize=1)
        stream = asyncio.StreamReader()
        stream.feed_data(b'{"method":"event"}\n' * 2)
        rpc.process = SimpleNamespace(returncode=None, stdout=stream, terminate=Mock())
        rpc.pending[1] = asyncio.get_running_loop().create_future()
        await rpc._read()
        assert reasons == ["codex_event_overflow"]
        with pytest.raises(ConsoleError):
            await rpc.pending[1]

    asyncio.run(run())
