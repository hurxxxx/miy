"""Pinned native executor discovery/dispatch check; no inference or business writes."""

import hashlib
import io
import json
import logging
import os
import socket
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, "/opt/hermes/plugins")
import hermes_constants
import miy_runtime
from agent.tool_executor import execute_tool_calls_sequential
from hermes_cli import config, plugins
from run_agent import AIAgent
from tools.approval_context import set_current_session_key
from tools.mcp_tool_schema import mcp_prefixed_tool_name
from tools.registry import registry

logging.disable(logging.CRITICAL)
manager = plugins.PluginManager()
manager._discovered = True
context = plugins.PluginContext(plugins.PluginManifest(name="miy_runtime"), manager)
context.register_middleware("tool_execution", miy_runtime.execute_tool)
profile = "miy-" + uuid4().hex
server_name = "miy-mcp-" + hashlib.sha256(profile.encode()).hexdigest()[:20] + "-internal"
server = {"url": "http://synthetic.invalid", "headers": {"Authorization": "Bearer synthetic"}}
toolset = "mcp-" + server_name
external_server = server_name.removesuffix("internal") + "b" * 20 + "-external"
foreign_server = "miy-mcp-" + "c" * 20 + "-" + "d" * 20 + "-external"
names = {key: mcp_prefixed_tool_name(server_name, key) for key in ("app.read", "app.write", "app.archive")}
scopes = {"run_read": ["app.read"], "run_empty": [], "run_all": ["app.read", "app.write"]}
dispatched = []


def rpc(configured, run_id, method, params):
    assert configured == server
    if run_id not in scopes:
        raise ValueError("Unadmitted run")
    if method == "miy/context":
        return {"allow_native_tools": True}
    if method == "tools/list":
        return {"tools": [{"name": name, "annotations": {"readOnlyHint": True}}
                          for name in scopes[run_id]]}
    assert method == "tools/call" and params["name"] in scopes[run_id]
    dispatched.append((run_id, params["name"]))
    return {"structuredContent": {"ok": True}}


def register(name):
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    if name == "app.write":
        parameters = {"type": "object", "properties": {"value": {"type": "string"}},
                      "required": ["value"], "additionalProperties": False}
    registry.register(
        name=names[name], toolset=toolset,
        schema={"name": names[name], "description": "Synthetic app tool " + name,
                "parameters": parameters},
        handler=lambda args, **kwargs: (_ for _ in ()).throw(AssertionError("Unscoped dispatch")),
    )


def call(agent, run_id, name, args):
    set_current_session_key(run_id)
    messages = []
    message = SimpleNamespace(tool_calls=[SimpleNamespace(
        id="call_" + uuid4().hex,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )])
    execute_tool_calls_sequential(agent, message, messages, "synthetic", finalize=False)
    results = [item for item in messages if item.get("role") == "tool"]
    assert len(results) == 1, "Native executor did not return one tool result"
    content = results[0]["content"]
    # Native execution wraps external results as untrusted data. Keep that
    # production protection; extract only the synthetic result for assertions.
    if content.startswith("<untrusted_tool_result "):
        content = content.split("\n\n", 1)[1].rsplit("\n</untrusted_tool_result>", 1)[0]
    # Hermes may append a native tool-use reminder after the JSON result.
    return json.JSONDecoder().raw_decode(content)[0]


with (
    tempfile.TemporaryDirectory() as home,
    patch.dict(os.environ, {"HERMES_HOME": str(Path(home) / profile)}),
    patch.object(config, "load_config", lambda *a, **kw: {
        "mcp_servers": {server_name: server, external_server: server, foreign_server: server},
        "platform_toolsets": {"api_server": [toolset, "mcp-" + external_server, "mcp-" + foreign_server]},
    }),
    patch.object(hermes_constants, "get_hermes_home", lambda: Path(home) / profile),
    patch.object(miy_runtime, "_rpc", rpc),
    patch.object(plugins, "get_plugin_manager", lambda: manager),
    patch.object(socket.socket, "connect", side_effect=AssertionError("Network access forbidden")),
    redirect_stdout(io.StringIO()),
    redirect_stderr(io.StringIO()),
):
    register("app.read")
    register("app.write")
    agent = AIAgent(
        base_url="http://127.0.0.1:1/v1", api_key="synthetic", provider="custom:synthetic",
        model="synthetic", enabled_toolsets=[toolset], session_id="synthetic",
        quiet_mode=True, skip_context_files=True, skip_memory=True,
        skip_background_review=True, max_iterations=1, platform="api_server",
    )
    for run_id, expected in scopes.items():
        result = call(agent, run_id, "tool_describe", {"names": list(names.values())})
        assert set(result["tools"]) == {names[name] for name in expected}, result
    found = call(agent, "run_read", "tool_search", {"queries": ["Synthetic app tool"]})
    assert set(found["tools"]) == {names["app.read"]}, found
    assert call(agent, "run_read", "tool_call", {"name": names["app.read"], "arguments": {}}) == {"ok": True}
    assert "error" in call(agent, "run_empty", "tool_call", {"name": names["app.read"], "arguments": {}})
    assert dispatched == [("run_read", "app.read")]
    invalid = call(agent, "run_all", "tool_call", {"name": names["app.write"], "arguments": {}})
    assert invalid["parameters"]["required"] == ["value"], invalid
    hidden = call(agent, "run_read", "tool_call", {"name": names["app.write"], "arguments": {}})
    assert "error" in hidden and "parameters" not in hidden, hidden
    malformed = call(agent, "run_all", "tool_call", {"arguments": {}})
    assert "error" in malformed, malformed
    assert dispatched == [("run_read", "app.read")], "Rejected bridges must not execute"
    assert call(agent, "run_all", "tool_call", {"name": names["app.write"], "arguments": {"value": "synthetic"}}) == {"ok": True}
    assert dispatched[-1] == ("run_all", "app.write")
    scopes["run_read"] = []
    assert call(agent, "run_read", "tool_describe", {"names": [names["app.read"]]})["tools"] == {}
    scopes["run_all"] = ["app.read", "app.archive"]
    stale = call(agent, "run_all", "tool_search", {"queries": ["app"]})
    assert stale["code"] == "miy.tools.catalog_refresh_required", stale
    assert stale["missing_tools"] == [names["app.archive"]]
    # Native re-registration models the new process after the standard restart.
    registry.deregister(names["app.write"])
    register("app.archive")
    fresh = call(agent, "run_all", "tool_describe", {"names": [names["app.archive"]]})
    assert set(fresh["tools"]) == {names["app.archive"]}, fresh
    assert "error" in call(agent, "run_unknown", "tool_search", {"queries": ["app"]})
    long_names = {}
    for configured in (external_server, foreign_server):
        wire_name = mcp_prefixed_tool_name(configured, "external.read_with_a_long_name")
        assert len(wire_name) == 64
        long_names[configured] = wire_name
        registry.register(
            name=wire_name, toolset="mcp-" + configured,
            schema={"name": wire_name, "description": "External read",
                    "parameters": {"type": "object", "properties": {}}},
            handler=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Discovery must not dispatch")),
        )
    described = call(agent, "run_all", "tool_describe", {"names": list(long_names.values())})
    assert set(described["tools"]) == {long_names[external_server]}, described

print("PASS: native agent executor scope, revocation, validation/correction, dispatch, catalog refresh and long external MCP name isolation; no inference")
