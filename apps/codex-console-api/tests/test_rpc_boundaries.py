import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from codex_console.errors import ConsoleError
from codex_console.rpc import CodexRPC


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
