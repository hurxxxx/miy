"""Official Hermes middleware for the pinned MCP transport gap.

Native MCP connections have profile-static HTTP headers. Never mutate those
shared connections: forward internal tools with the approval context's run ID
on a separate request. Hermes still owns discovery, schemas and approvals.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from uuid import uuid4

import httpx


def _error(message: str) -> str:
    return json.dumps({"error": message})


def runtime_transport():
    from hermes_cli.config import load_config
    from hermes_constants import get_hermes_home
    from tools.approval import get_current_session_key

    profile = get_hermes_home().name
    if not re.fullmatch(r"mty-[0-9a-f]{32}(?:-local)?", profile):
        raise ValueError("Managed interactive/workload profile required")
    namespace = hashlib.sha256(profile.encode()).hexdigest()[:20]
    server_name = f"mty-mcp-{namespace}-internal"
    run_id = get_current_session_key(default="")
    server = load_config().get("mcp_servers", {}).get(server_name)
    if not run_id.startswith("run_") or not isinstance(server, dict):
        raise ValueError("Trusted runtime context required")
    if not server.get("headers", {}).get("Authorization"):
        raise ValueError("Authenticated transport required")
    return server, run_id


def _rpc(server: dict, run_id: str, method: str, params: dict) -> dict:
    from tools.mcp_tool import _interpolate_env_vars

    # Management stores bearer tokens as profile-local ${VAR} references.
    # The pinned native resolver reads the current multiplexed secret scope.
    configured_headers = _interpolate_env_vars(server.get("headers", {}))
    authorization = configured_headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or "${" in authorization:
        raise ValueError("Resolved profile authentication required")
    headers = {
        **configured_headers,
        "X-Hermes-Run-Id": run_id,
        "Accept": "application/json",
    }
    # A run may reach its first tool before the dispatcher has committed the
    # native run ID. Only discovery can retry; never replay a mutating call.
    deadline = time.monotonic() + 10
    # This middleware owns its HTTP request; native MCP SDK timeouts do not
    # cover it. Allow the bounded one-hour workload plus dispatch/cleanup
    # overhead to finish, while keeping connection and control waits short.
    timeout = httpx.Timeout(30, read=3900 if method == "tools/call" else 30)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        while True:
            response = client.post(
                server["url"],
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": uuid4().hex,
                    "method": method,
                    "params": params,
                },
            )
            if (
                method in {"tools/list", "mty/context"}
                and response.status_code == 409
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
                continue
            response.raise_for_status()
            body = response.json()
            if "error" in body:
                raise ValueError("MTY rejected the tool request")
            return body["result"]


def execute_tool(*, tool_name: str, args: dict, next_call, **context):
    # Check every MTY internal prefix, including another profile's tool names.
    # Returning an error is deliberate: native middleware falls through when
    # a callback raises. A transport/policy failure must never invoke next_call.
    call_started = False
    try:
        from hermes_cli.config import load_config
        from hermes_constants import get_hermes_home
        from tools.approval import get_current_session_key, request_elicitation_consent
        from tools.mcp_tool import mcp_prefixed_tool_name

        profile = get_hermes_home().name
        if not re.fullmatch(r"mty-[0-9a-f]{32}(?:-local)?(?:-jobs)?", profile):
            return next_call()
        namespace = hashlib.sha256(profile.encode()).hexdigest()[:20]
        server_name = f"mty-mcp-{namespace}-internal"
        run_id = get_current_session_key(default="")
        if not run_id.startswith("run_"):
            return _error("Trusted Hermes run context is required")
        server = load_config().get("mcp_servers", {}).get(server_name)
        if not isinstance(server, dict) or not server.get("headers", {}).get("Authorization"):
            return _error("Authenticated MTY transport is unavailable")
        execution = _rpc(server, run_id, "mty/context", {})
        if tool_name == "mty_submit_result":
            return json.dumps(_rpc(server, run_id, "mty/submit", args), ensure_ascii=False)
        # Profile history includes app workloads. Native search has no trusted
        # MTY app/resource ACL filter, including its direct session-read mode.
        if tool_name == "session_search":
            return _error("Native history search has no MTY source-access policy")
        if tool_name in execution.get("native_tools", []):
            if not _rpc(server, run_id, "mty/native_admit", {"tool": tool_name}).get("accepted"):
                return _error("The workload tool limit was reached")
            return next_call()
        if not tool_name.startswith(mcp_prefixed_tool_name(server_name, "")):
            if not execution.get("allow_native_tools"):
                return _error("This workload may only submit its result")
            if tool_name.startswith("mcp__mty_mcp_") and not tool_name.startswith(
                f"mcp__mty_mcp_{namespace}_"
            ):
                return _error("Tool is not available in this execution profile")
            if not tool_name.startswith(f"mcp__mty_mcp_{namespace}_") and tool_name not in {
                "web_search",
                "web_extract",
                "terminal",
                "process",
                "read_file",
                "write_file",
                "patch",
                "search_files",
                "skills_list",
                "skill_view",
                "skill_manage",
                "todo",
                "memory",
                "execute_code",
                "delegate_task",
            }:
                return _error("Tool has no configured MTY execution policy")
            return next_call()
        listed = _rpc(server, run_id, "tools/list", {})
        matches = [
            tool
            for tool in listed.get("tools", [])
            if mcp_prefixed_tool_name(server_name, tool["name"]) == tool_name
        ]
        if len(matches) != 1:
            return _error("Tool is not available for this run")
        tool = matches[0]
        if not tool.get("annotations", {}).get("readOnlyHint", False):
            digest = hashlib.sha256(
                json.dumps(
                    args,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            consent = request_elicitation_consent(
                f"MCP tool '{tool['name']}' on UNTRUSTED server '{server_name}' wants to run.",
                f"Approve this call once. Arguments SHA-256: {digest}",
                surface=f"mcp-trust/{server_name}",
            )
            if consent != "accept":
                return _error("Tool approval was denied")
        call_started = True
        result = _rpc(server, run_id, "tools/call", {"name": tool["name"], "arguments": args})
        return json.dumps(result.get("structuredContent", result), ensure_ascii=False)
    except Exception as error:
        if call_started:
            return _error(
                "MTY did not confirm this tool's outcome. The server may still "
                "complete the call; do not repeat it. Verify the result before continuing."
            )
        return _error(
            f"MTY tool transport failed ({type(error).__name__}); execution was blocked"
        )


def register(ctx):
    from .sandbox import MTYSandbox

    ctx.register_terminal_environment_provider(MTYSandbox())
    ctx.register_middleware("tool_execution", execute_tool)
    ctx.register_tool(
        name="mty_submit_result",
        toolset="mty_runtime",
        schema={
            "name": "mty_submit_result",
            "description": "Submit the structured result required by this workload. Correct validation errors and resubmit before finishing.",
            "parameters": {
                "type": "object",
                "properties": {"result": {"type": "object"}},
                "required": ["result"],
                "additionalProperties": False,
            },
        },
        handler=lambda args, **kwargs: _error("Trusted workload context is required"),
    )
