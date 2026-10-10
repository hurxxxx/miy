import asyncio
import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_controller_launch import SCHEMA, requirements
from test_controller_launch import native_fixture as native_fixture

from codex_console import controller_launch, remote_environments, toolchain_profiles
from codex_console import rpc as rpc_module
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.rpc import CodexRPC
from codex_console.runtime import Runtime


@pytest.fixture
def sdk_server(native_fixture, monkeypatch):
    binary, bwrap, source, home = native_fixture
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr(rpc_module, "schemas_are_compatible", lambda *args: True)
    monkeypatch.setattr(rpc_module, "remote_schemas_are_compatible", lambda *args: True)
    import codex_console.executor_probe as probe

    monkeypatch.setattr(
        probe, "preflight", AsyncMock(return_value={"capabilities": {"networkProxyLaunch": True}})
    )
    state = SimpleNamespace(
        spawns=[],
        messages=[],
        policy=requirements(),
        original_policy={"requirements": {"allowedLoginMethods": ["chatgpt"]}},
        baseline_messages=[],
        baseline_processes=[],
        config=None,
        schema=True,
        fail_spawn=False,
        fail_handshake=False,
        closed=False,
        fd=None,
        scratch=None,
    )
    environment = AppExecutionEnvironment(
        key="synthetic",
        source_root=source,
        exec_server_url="ws://127.0.0.1:19391",
        auth_bearer_token="synthetic-" + "x" * 32,
        toolchain_profile=toolchain_profiles.SDK_PROFILE,
    )
    config = {
        "features": remote_environments.SAFE_FEATURES,
        "mcp_servers": {},
        "notify": [],
        "allow_login_shell": False,
        "sandbox_mode": "read-only",
        "approval_policy": "never",
        "shell_environment_policy": {
            "inherit": "none",
            "set": toolchain_profiles.command_environment(environment),
        },
    }

    state.config = config

    async def make_rpc():
        def make_process(baseline=False):
            stream = asyncio.StreamReader()

            def written(raw):
                message = json.loads(raw)
                (state.baseline_messages if baseline else state.messages).append(message)
                if "id" not in message:
                    return
                method = message["method"]
                result = {}
                if method == "initialize" and state.fail_handshake and not baseline:
                    reply = {
                        "id": message["id"],
                        "error": {"code": -32603, "message": "synthetic PRIVATE failure"},
                    }
                elif method == "environment/info" and message["params"]["environmentId"] == "local":
                    reply = {
                        "id": message["id"],
                        "error": {"code": -32600, "message": "synthetic local missing"},
                    }
                else:
                    if method == "config/read":
                        result = {"config": config}
                    elif method == "configRequirements/read":
                        result = copy.deepcopy(state.original_policy if baseline else state.policy)
                    elif method == "environment/info":
                        result = {"cwd": source.as_uri()}
                    elif method in ("thread/start", "thread/resume"):
                        result = {"thread": {"id": "same-thread"}}
                    elif method == "turn/start":
                        result = {"turn": {"id": "same-turn"}}
                    reply = {"id": message["id"], "result": result}
                stream.feed_data((json.dumps(reply) + "\n").encode())

            process = SimpleNamespace(
                returncode=None,
                stdout=stream,
                stdin=SimpleNamespace(write=Mock(side_effect=written), drain=AsyncMock()),
                wait=AsyncMock(return_value=0),
            )
            process.terminate = Mock(side_effect=lambda: setattr(process, "returncode", 0))
            process.kill = Mock(side_effect=lambda: setattr(process, "returncode", -9))

            if baseline:
                state.baseline_processes.append(process)
            return process

        async def spawn(*argv, **kwargs):
            state.spawns.append((argv, kwargs))
            if argv[1:] == ("--version",):
                return SimpleNamespace(
                    returncode=0, communicate=AsyncMock(return_value=(b"codex-cli 0.160.1", b""))
                )
            if argv[1:3] == ("app-server", "generate-json-schema"):
                if state.schema:
                    schema_path = Path(argv[-1]) / "v2/ConfigRequirementsReadResponse.json"
                    schema_path.parent.mkdir()
                    schema_path.write_text(json.dumps(SCHEMA))
                return SimpleNamespace(returncode=0, wait=AsyncMock(return_value=0))
            if argv[0] == str(binary):
                assert argv[1:4] == ("app-server", "--listen", "stdio://")
                return make_process(baseline=True)
            assert argv[0] == str(bwrap)
            state.fd = kwargs["pass_fds"][0]
            assert (
                fcntl.fcntl(state.fd, controller_launch.F_GET_SEALS)
                & controller_launch.F_SEAL_WRITE
            )
            last_bind = len(argv) - 1 - argv[::-1].index("--bind")
            state.scratch = Path(argv[last_bind + 1])
            assert state.scratch.is_dir()
            if state.fail_spawn:
                raise OSError("synthetic spawn unavailable")
            return make_process()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        rpc = CodexRPC(str(binary), source, AsyncMock(), AsyncMock())
        rpc.remote_environment = environment
        rpc.startup_overrides = remote_environments.overrides({}, environment)
        return rpc

    return state, make_rpc, environment


def thread_params(source, *, resume=False):
    value = {"cwd": str(source), "sandbox": "read-only", "approvalPolicy": "never"}
    if resume:
        value["threadId"] = "same-thread"
    return value


def turn_params(kind="readOnly"):
    value = {
        "threadId": "same-thread",
        "input": [{"type": "text", "text": "synthetic", "text_elements": []}],
        "sandboxPolicy": {"type": kind, "networkAccess": False},
    }
    if kind == "workspaceWrite":
        value["sandboxPolicy"].update(
            {"writableRoots": ["/synthetic"], "excludeSlashTmp": True, "excludeTmpdirEnvVar": True}
        )
    return value


@pytest.mark.parametrize("kind", ["readOnly", "workspaceWrite"])
def test_sdk_wraps_only_actual_spawn_and_rechecks_policy_before_each_thread_turn_resume(
    sdk_server, kind
):
    state, make_rpc, environment = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        assert len(state.spawns) == 6
        assert state.spawns[0][0][1:] == ("--version",)
        assert state.spawns[1][0][1:3] == ("app-server", "generate-json-schema")
        assert "pass_fds" not in state.spawns[0][1] and "pass_fds" not in state.spawns[1][1]
        assert state.spawns[5][1]["env"]["CODEX_EXEC_SERVER_URL"] == "none"
        with pytest.raises(OSError):
            os.fstat(state.fd)  # Parent copy closed immediately after spawn.
        assert state.scratch.is_dir()  # Mount source remains until controller exit.
        initial = [m["method"] for m in state.messages]
        assert initial.index("configRequirements/read") < initial.index("environment/add")
        for method, params in [
            ("thread/start", thread_params(environment.source_root)),
            ("turn/start", turn_params(kind)),
            (
                "turn/steer",
                {
                    "threadId": "same-thread",
                    "expectedTurnId": "same-turn",
                    "input": [{"type": "text", "text": "synthetic", "text_elements": []}],
                },
            ),
            ("thread/resume", thread_params(environment.source_root, resume=True)),
        ]:
            response = await rpc.call(method, params)
            messages = [m for m in state.messages if "id" in m]
            assert messages[-3]["method"] == "configRequirements/read"
            assert messages[-2]["method"] == "config/read"
            assert messages[-1]["method"] == method
            if method == "thread/resume":
                assert response["thread"]["id"] == "same-thread"
        await rpc.close()
        assert rpc.sdk_launch is None and not state.scratch.exists()
        # A cold connection repeats the exact fixed policy for original IDs.
        resumed = await make_rpc()
        await resumed.start()
        response = await resumed.call(
            "thread/resume", thread_params(environment.source_root, resume=True)
        )
        assert response["thread"]["id"] == "same-thread"
        await resumed.close()
        assert not state.scratch.exists()

    asyncio.run(run())


@pytest.mark.parametrize(
    "checkpoint", ["startup", "thread/start", "thread/resume", "turn/start", "turn/steer"]
)
def test_effective_cloud_expansion_refuses_before_target_and_closes_controller(
    sdk_server, checkpoint
):
    state, make_rpc, environment = sdk_server

    async def run():
        rpc = await make_rpc()
        if checkpoint != "startup":
            await rpc.start()
            if checkpoint == "turn/steer":
                await rpc.call("turn/start", turn_params())
        state.policy["requirements"]["network"]["domains"] = {"example.com": "allow"}
        before = len(state.messages)
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            if checkpoint == "startup":
                await rpc.start()
            else:
                params = (
                    thread_params(environment.source_root, resume=True)
                    if checkpoint.startswith("thread/")
                    else turn_params()
                    if checkpoint == "turn/start"
                    else {"threadId": "same-thread", "expectedTurnId": "same-turn", "input": []}
                )
                await rpc.call(checkpoint, params)
        assert not rpc.connected and rpc.sdk_launch is None
        assert not state.scratch.exists()
        assert not any(m.get("method") == checkpoint for m in state.messages[before:])
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["missing_schema", "spawn", "handshake"])
def test_sdk_start_failure_has_no_native_fallback_or_resource_leak(sdk_server, kind):
    state, make_rpc, _ = sdk_server
    state.schema = kind != "missing_schema"
    state.fail_spawn = kind == "spawn"
    state.fail_handshake = kind == "handshake"

    async def run():
        rpc = await make_rpc()
        with pytest.raises((ConsoleError, OSError)):
            await rpc.start()
        if state.fd is not None:
            with pytest.raises(OSError):
                os.fstat(state.fd)
            assert not state.scratch.exists()
        assert not rpc.connected and rpc.sdk_launch is None
        assert not any(m.get("method") == "thread/start" for m in state.messages)
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("field", controller_launch.ADMIN)
@pytest.mark.parametrize(
    "checkpoint", ["startup", "thread/start", "thread/resume", "turn/start", "turn/steer"]
)
def test_missing_effective_admin_field_refuses_before_each_target_and_retires_same_controller(
    sdk_server, field, checkpoint
):
    state, make_rpc, environment = sdk_server

    async def run():
        rpc = await make_rpc()
        if checkpoint != "startup":
            await rpc.start()
            if checkpoint == "turn/steer":
                await rpc.call("turn/start", turn_params())
        state.policy["requirements"].pop(field)
        process = rpc.process
        generation = rpc.generation
        before = len(state.messages)
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            if checkpoint == "startup":
                await rpc.start()
            else:
                params = (
                    thread_params(environment.source_root, resume=checkpoint == "thread/resume")
                    if checkpoint.startswith("thread/")
                    else turn_params()
                    if checkpoint == "turn/start"
                    else {"threadId": "same-thread", "expectedTurnId": "same-turn", "input": []}
                )
                await rpc.call(checkpoint, params)
        assert not rpc.connected and rpc.sdk_launch is None and not state.scratch.exists()
        if checkpoint != "startup":
            assert (
                rpc.process is process
                and rpc.generation == generation
                and process.returncode is not None
            )
        assert not any(m.get("method") == checkpoint for m in state.messages[before:])
        if checkpoint == "startup":
            assert not any(
                m.get("method") in ("thread/start", "thread/resume", "turn/start", "turn/steer")
                for m in state.messages
            )
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", ["disabled", "network", "ungranted_steer", "different_thread", "named_profile"]
)
def test_sdk_cannot_expand_profile_or_steer_an_unbound_thread(sdk_server, kind):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        if kind == "different_thread":
            await rpc.call("turn/start", turn_params())
        if kind in ("disabled", "network", "named_profile"):
            params = turn_params("dangerFullAccess" if kind == "disabled" else "readOnly")
            if kind == "network":
                params["sandboxPolicy"]["networkAccess"] = True
            elif kind == "named_profile":
                params["permissions"] = "app-selected-profile"
            method = "turn/start"
        else:
            params = {"threadId": "different-thread", "expectedTurnId": "same-turn", "input": []}
            method = "turn/steer"
        before = len(state.messages)
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            await rpc.call(method, params)
        assert not rpc.connected and not state.scratch.exists()
        assert not any(m.get("method") == method for m in state.messages[before:])
        await rpc.close()

    asyncio.run(run())


def test_sdk_durable_disconnect_callback_failure_still_releases_owned_resources(sdk_server):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        callback = AsyncMock(side_effect=RuntimeError("synthetic durable refusal"))
        rpc.on_disconnect = callback
        with pytest.raises(RuntimeError, match="synthetic durable refusal"):
            await rpc._failed("codex_protocol_error")
        callback.assert_awaited_once_with("codex_protocol_error")
        assert rpc.sdk_launch is None and not state.scratch.exists()
        assert not rpc.connected
        await rpc.close()

    asyncio.run(run())


def test_sdk_reader_disconnect_and_concurrent_close_preserve_pending_durable_callback(sdk_server):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        original_process, original_generation = rpc.process, rpc.generation
        entered, release = asyncio.Event(), asyncio.Event()
        durable = []

        async def disconnected(reason):
            entered.set()
            await release.wait()
            durable.append((reason, rpc.generation))

        rpc.on_disconnect = disconnected
        rpc.process.stdout.feed_eof()  # Enter _failed through the real transport reader.
        await asyncio.wait_for(entered.wait(), 1)
        callback = rpc.failure_task
        try:
            await asyncio.wait_for(rpc.close(), 1)
            assert rpc.reader.done() and rpc.dispatcher.done()
            assert rpc.sdk_stop_task.done() and rpc.sdk_launch is None
            assert not state.scratch.exists()
            assert callback is rpc.failure_task and not callback.done()
            assert not callback.cancelled() and not durable
            assert rpc.process is original_process and rpc.generation == original_generation
            assert len(state.spawns) == 6
        finally:
            release.set()
            await asyncio.wait_for(asyncio.shield(callback), 1)
        assert durable == [("codex_disconnected", original_generation)]
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "info",
    [
        None,
        {},
        {"capabilities": None},
        {"capabilities": {}},
        {"capabilities": {"networkProxyLaunch": False}},
        {"capabilities": {"networkProxyLaunch": 1}},
    ],
)
def test_sdk_requires_exact_declared_proxy_launch_capability_before_spawn(
    sdk_server, monkeypatch, info
):
    import codex_console.executor_probe as probe

    state, make_rpc, _ = sdk_server
    handshake = AsyncMock(return_value=info)
    monkeypatch.setattr(probe, "preflight", handshake)

    async def run():
        rpc = await make_rpc()
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            await rpc.start()
        handshake.assert_awaited_once_with(rpc.remote_environment)
        assert len(state.spawns) == 2
        assert state.fd is None and rpc.process is None and rpc.sdk_launch is None
        assert not state.messages
        await rpc.close()

    asyncio.run(run())


def test_sdk_close_cancellation_preserves_single_owned_cleanup(sdk_server):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        started, release = asyncio.Event(), asyncio.Event()

        async def wait():
            started.set()
            await release.wait()
            rpc.process.returncode = 0
            return 0

        rpc.process.terminate = Mock()
        rpc.process.wait = wait
        closing = asyncio.create_task(rpc.close())
        await started.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        owned = rpc.sdk_stop_task
        assert not owned.cancelled() and state.scratch.exists()
        again = asyncio.create_task(rpc.close())
        await asyncio.sleep(0)
        again.cancel()
        with pytest.raises(asyncio.CancelledError):
            await again
        assert rpc.sdk_stop_task is owned and not owned.cancelled()
        release.set()
        await owned
        assert rpc.reader.done() and rpc.dispatcher.done()
        assert rpc.sdk_launch is None and not state.scratch.exists()
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("unknown", [False, True])
def test_sdk_kill_timeout_preserves_unknown_process_context(sdk_server, unknown):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        await rpc.start()
        process = rpc.process
        process.terminate = Mock()
        process.kill = Mock()
        process.wait = AsyncMock(side_effect=[TimeoutError(), TimeoutError() if unknown else 0])
        if unknown:
            with pytest.raises(ConsoleError, match="app_executor_unavailable"):
                await rpc.close()
            assert rpc.sdk_cleanup_uncertain is True
            assert rpc.process is process and rpc.sdk_launch is not None
            assert state.scratch.exists()
            # Synthetic externally verified termination, not a product retry.
            process.returncode = -9
            rpc._release_sdk_launch()
            rpc.sdk_stop_task = None
        else:
            await rpc.close()
            assert rpc.sdk_cleanup_uncertain is False
        process.kill.assert_called_once()
        assert not state.scratch.exists()
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["handshake", "effective_requirements"])
def test_runtime_owns_failed_sdk_start_without_retrying_unknown_process(
    sdk_server, monkeypatch, failure
):
    state, make_rpc, environment = sdk_server
    state.fail_handshake = failure == "handshake"
    if failure == "effective_requirements":
        state.policy["requirements"]["network"]["domains"] = {"example.com": "allow"}

    async def run():
        rpc = await make_rpc()
        spawn = asyncio.create_subprocess_exec

        async def unknown_spawn(*argv, **kwargs):
            process = await spawn(*argv, **kwargs)
            if "pass_fds" in kwargs:
                process.terminate = Mock()
                process.kill = Mock()
                process.wait = AsyncMock(side_effect=[TimeoutError(), TimeoutError()])
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", unknown_spawn)
        monkeypatch.setattr(remote_environments, "for_task", lambda *_: environment)
        factory = Mock(return_value=contextlib.nullcontext(None))
        control = SimpleNamespace(
            authenticated_rpc=AsyncMock(
                return_value=SimpleNamespace(call=AsyncMock(return_value={"config": {}}))
            )
        )
        runtime = Runtime(
            SimpleNamespace(workspace=environment.source_root, binary=rpc.binary),
            factory,
            Mock(return_value=rpc),
            remote_task_id="synthetic-original-task",
            control_runtime=control,
        )
        # Only the existing Task/source lookup is synthetic; real Runtime.connect,
        # RPC startup, effective-policy checks and cleanup ownership execute.
        runtime.invalidate_observations = Mock()
        runtime.require_task = Mock(return_value=SimpleNamespace(root=str(environment.source_root)))
        runtime.require_allowed_task = Mock()
        runtime.on_disconnect = AsyncMock()
        original_generation = rpc.generation
        try:
            with pytest.raises(ConsoleError, match="app_executor_unavailable"):
                await runtime.connect()
            assert runtime.rpc is rpc and rpc.sdk_cleanup_uncertain is True
            original_process, original_context = rpc.process, rpc.sdk_launch
            assert original_context is not None and state.scratch.exists()
            assert rpc.generation == original_generation and not rpc.connected
            with pytest.raises(OSError):
                os.fstat(state.fd)
            assert len(state.spawns) == 6
            with pytest.raises(ConsoleError, match="app_executor_unavailable"):
                await runtime.connect()
            with pytest.raises(ConsoleError, match="app_executor_unavailable"):
                await runtime.close()
            assert runtime.rpc is rpc and rpc.process is original_process
            assert rpc.sdk_launch is original_context and state.scratch.exists()
            assert rpc.generation == original_generation and len(state.spawns) == 6
            runtime.rpc_factory.assert_called_once()
            assert not any(m.get("method") == "thread/start" for m in state.messages)
            runtime.on_disconnect.assert_awaited_once()
        finally:
            # Fixture-only externally verified termination; no product retry or
            # replacement controller is used to clean an unknown process.
            if rpc.process is not None:
                rpc.process.returncode = -9
            rpc._release_sdk_launch()
            rpc.sdk_stop_task = None
            await rpc.close()
        assert not state.scratch.exists()

    asyncio.run(run())


@pytest.mark.parametrize(
    "original",
    [
        {"network": {}},
        {"unknownAdmin": False},
        {"allowedSandboxModes": ["read-only"]},
        {"allowedApprovalPolicies": ["never"]},
        {"allowLoginShell": 0},
        {"featureRequirements": {"apps": False}},
    ],
)
def test_original_administration_refuses_before_overlay_and_joins_baseline(sdk_server, original):
    state, make_rpc, _ = sdk_server
    state.original_policy = {"requirements": original}

    async def run():
        rpc = await make_rpc()
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            await rpc.start()
        assert rpc.process is None and rpc.sdk_launch is None and state.fd is None
        assert rpc.sdk_baseline is None and rpc.sdk_baseline_stop_task.done()
        assert not state.messages
        assert [m["method"] for m in state.baseline_messages] == [
            "initialize",
            "initialized",
            "configRequirements/read",
        ]
        assert len(state.baseline_processes) == 1
        baseline = state.baseline_processes[0]
        baseline.terminate.assert_called_once()
        baseline.wait.assert_awaited_once()
        assert baseline.returncode == 0
        assert not any("pass_fds" in options for _, options in state.spawns)
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "checkpoint", ["startup", "thread/start", "thread/resume", "turn/start", "turn/steer"]
)
def test_sdk_raw_mcp_reload_refuses_before_admission_or_target_without_discovery(
    sdk_server, checkpoint
):
    state, make_rpc, environment = sdk_server

    async def run():
        rpc = await make_rpc()
        if checkpoint != "startup":
            await rpc.start()
            if checkpoint == "turn/steer":
                await rpc.call("turn/start", turn_params())
        state.config["mcp_servers"] = {"synthetic-current": {"enabled": False}}
        before = len(state.messages)
        with pytest.raises(ConsoleError, match="app_executor_configuration"):
            if checkpoint == "startup":
                await rpc.start()
            else:
                params = (
                    thread_params(environment.source_root, resume=True)
                    if checkpoint.startswith("thread/")
                    else turn_params()
                    if checkpoint == "turn/start"
                    else {"threadId": "same-thread", "expectedTurnId": "same-turn", "input": []}
                )
                await rpc.call(checkpoint, params)
        target = "environment/add" if checkpoint == "startup" else checkpoint
        assert not any(m["method"] == target for m in state.messages[before:])
        assert not any(m["method"].startswith("mcp") for m in state.messages)
        assert not rpc.connected and rpc.sdk_launch is None and not state.scratch.exists()
        await rpc.close()

    asyncio.run(run())


def test_sdk_original_baseline_cleanup_survives_repeated_caller_cancellation(
    sdk_server, monkeypatch
):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        spawn = asyncio.create_subprocess_exec
        entered, release = asyncio.Event(), asyncio.Event()

        async def owned_spawn(*argv, **kwargs):
            process = await spawn(*argv, **kwargs)
            if argv[1:4] == ("app-server", "--listen", "stdio://"):
                process.terminate = Mock()

                async def wait():
                    entered.set()
                    await release.wait()
                    process.returncode = 0
                    return 0

                process.wait = wait
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", owned_spawn)
        starting = asyncio.create_task(rpc.start())
        await asyncio.wait_for(entered.wait(), 1)
        baseline, generation = rpc.sdk_baseline, rpc.sdk_baseline.generation
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        cleanup = rpc.sdk_baseline_stop_task
        assert not cleanup.done() and not cleanup.cancelled()
        closing = asyncio.create_task(rpc.close())
        await asyncio.sleep(0)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert rpc.sdk_baseline is baseline and baseline.generation == generation
        assert rpc.sdk_baseline_stop_task is cleanup and not cleanup.cancelled()
        assert state.fd is None and rpc.process is None and not state.messages
        release.set()
        await asyncio.wait_for(asyncio.shield(cleanup), 1)
        assert rpc.sdk_baseline is None and baseline.reader.done() and baseline.dispatcher.done()
        assert baseline.process.returncode == 0 and len(state.baseline_processes) == 1
        await rpc.close()

    asyncio.run(run())


def test_sdk_original_baseline_unknown_exit_retains_same_owner_and_never_retries(
    sdk_server, monkeypatch
):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        spawn = asyncio.create_subprocess_exec

        async def unknown_spawn(*argv, **kwargs):
            process = await spawn(*argv, **kwargs)
            if argv[1:4] == ("app-server", "--listen", "stdio://"):
                process.terminate = Mock()
                process.kill = Mock()
                process.wait = AsyncMock(side_effect=TimeoutError())
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", unknown_spawn)
        with pytest.raises(ConsoleError, match="app_executor_unavailable"):
            await rpc.start()
        baseline, cleanup, generation = rpc.sdk_baseline, rpc.sdk_baseline_stop_task, rpc.generation
        count = len(state.spawns)
        assert rpc.sdk_cleanup_uncertain and baseline.process.returncode is None
        assert rpc.sdk_launch is None and rpc.process is None and state.fd is None
        for _ in range(2):
            with pytest.raises(ConsoleError, match="app_executor_unavailable"):
                await rpc.close()
        assert rpc.sdk_baseline is baseline and rpc.sdk_baseline_stop_task is cleanup
        assert rpc.generation == generation and len(state.spawns) == count
        baseline.process.kill.assert_called_once()
        # Fixture-only externally established exit; no product adoption or retry.
        baseline.process.returncode = -9
        await baseline.close()
        rpc.sdk_baseline = None
        rpc.sdk_baseline_stop_task = None
        await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["version", "schema"])
def test_sdk_baseline_owns_utility_child_during_pre_server_cancellation(
    sdk_server, monkeypatch, stage
):
    state, make_rpc, _ = sdk_server

    async def run():
        rpc = await make_rpc()
        spawn = asyncio.create_subprocess_exec
        entered, release = asyncio.Event(), asyncio.Event()
        utilities = []

        async def observed_spawn(*argv, **kwargs):
            process = await spawn(*argv, **kwargs)
            selected = (
                stage == "version"
                and len(state.spawns) == 3
                or stage == "schema"
                and len(state.spawns) == 4
            )
            if selected:
                process.returncode = None

                def terminate():
                    process.returncode = 0
                    release.set()

                async def wait():
                    entered.set()
                    await release.wait()
                    return 0

                process.terminate, process.kill = Mock(side_effect=terminate), Mock()
                process.wait = wait
                if stage == "version":

                    async def communicate():
                        entered.set()
                        await release.wait()
                        return b"codex-cli 0.160.1", b""

                    process.communicate = communicate
                utilities.append(process)
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observed_spawn)
        starting = asyncio.create_task(rpc.start())
        await asyncio.wait_for(entered.wait(), 1)
        baseline = rpc.sdk_baseline
        assert baseline.process is utilities[0]
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert rpc.sdk_baseline is None and rpc.sdk_baseline_stop_task.done()
        utilities[0].terminate.assert_called_once()
        assert utilities[0].returncode == 0 and state.fd is None and not state.messages
        assert not state.baseline_processes
        await rpc.close()

    asyncio.run(run())
