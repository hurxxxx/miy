"""Pinned native execution environments for independent application tasks.

Codex owns remote files, commands and child agents. This module selects and
validates the operator's environment; it never substitutes a local executor.
"""

import hashlib
import json
import os
import re
from pathlib import Path

from .errors import ConsoleError
from .toolchain_profiles import SDK_PROFILE, binding_identity, command_environment, selected_profile


def _require_sdk_policy(policy, environment):
    # Official v0.160.1 filters include_only after applying explicit set values.
    # Host profile evaluation must also stay off for this fixed command profile.
    if selected_profile(environment) == SDK_PROFILE and (
        policy.get("include_only")
        or policy.get("filters")
        or policy.get("experimental_use_profile")
    ):
        raise ConsoleError("app_executor_configuration", 503)


REMOTE_VERSION = "0.160.1"
ENVIRONMENT_ID = "miy-app"
SAFE_FEATURES = {
    "apps": False,
    "plugins": False,
    "hooks": False,
    "shell_snapshot": False,
    "shell_snapshot_v2": False,
    "skip_host_skill_discovery": True,
    "skill_mcp_dependency_install": False,
    "deferred_executor": True,
    "executor_capability_discovery": True,
}


def fingerprint(environment):
    public = {
        "key": environment.key,
        "source_root": str(environment.source_root),
        "exec_server_url": environment.exec_server_url,
        "profile": 1,
    }
    toolchain = binding_identity(environment)
    if toolchain is not None:
        public["toolchain"] = toolchain
    return hashlib.sha256(
        json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def binding_snapshot(settings, source_root):
    environment = next(
        (
            item
            for item in settings.app_execution_environments
            if item.source_root == Path(source_root)
        ),
        None,
    )
    if environment is None:
        return {}
    return {
        "remote_environment_key": environment.key,
        "remote_environment_digest": fingerprint(environment),
    }


def for_task(settings, task):
    source = (task.context or {}).get("source_binding")
    if not source:
        return None
    environment = next(
        (
            item
            for item in settings.app_execution_environments
            if item.key == source.get("remote_environment_key")
        ),
        None,
    )
    if environment is None:
        raise ConsoleError("app_executor_unavailable", 503)
    if (
        str(environment.source_root) != source["repository_root"]
        or source.get("remote_environment_digest") != fingerprint(environment)
        or not Path(task.root).is_relative_to(environment.source_root)
    ):
        raise ConsoleError("app_executor_changed", 409)
    if task.worktree_owned or (task.template_snapshot or {}).get("definition", {}).get("isolate"):
        # An endpoint mounts one explicitly provisioned checkout. A host worktree
        # cannot silently become another container's execution environment.
        raise ConsoleError("app_executor_worktree_unsupported", 422)
    return environment


def implementation_permissions(settings, task):
    """Advertise current choices without making stale task history unreadable."""
    try:
        environment = for_task(settings, task)
        return ["ask"] if selected_profile(environment) == SDK_PROFILE else ["ask", "yolo"]
    except (ConsoleError, KeyError, TypeError, AttributeError):
        return []


def require_provider_boundary():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    # The official TOML provider takes precedence over CODEX_EXEC_SERVER_URL.
    # Never silently accept a provider that might expose a local executor.
    if (home / "environments.toml").exists():
        raise ConsoleError("app_executor_configuration", 503)


def overrides(config, environment=None):
    if (config.get("model_provider") or "openai") != "openai":
        raise ConsoleError("subscription_provider_required")
    sdk = selected_profile(environment) == SDK_PROFILE
    names = {} if sdk else config.get("mcp_servers") or {}
    if not isinstance(names, dict) or any(
        not re.fullmatch(r"[A-Za-z0-9_-]+", key) for key in names
    ):
        raise ConsoleError("app_executor_configuration", 503)
    # Custom host role files may change providers or expose host-owned context.
    # Standard native child agents remain available in the same remote environment.
    if any(
        isinstance(value, dict) and value.get("config_file")
        for value in (config.get("agents") or {}).values()
    ):
        raise ConsoleError("app_executor_configuration", 503)
    result = {f"mcp_servers.{name}.enabled": False for name in names}
    policy = config.get("shell_environment_policy") or {}
    if not isinstance(policy, dict):
        raise ConsoleError("app_executor_configuration", 503)
    _require_sdk_policy(policy, environment)
    extra = policy.get("set") or {}
    if not isinstance(extra, dict) or any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in extra
    ):
        raise ConsoleError("app_executor_configuration", 503)
    result.update({f"shell_environment_policy.set.{key}": "" for key in extra})
    result.update({f"features.{key}": value for key, value in SAFE_FEATURES.items()})
    result.update(
        {
            "forced_login_method": "chatgpt",
            "notify": [],
            "allow_login_shell": False,
            "shell_environment_policy.inherit": "none",
        }
    )
    if selected_profile(environment) == SDK_PROFILE:
        result["sandbox_mode"] = "read-only"
        result["approval_policy"] = "never"
        result["shell_environment_policy.experimental_use_profile"] = False
        result["shell_environment_policy.ignore_default_excludes"] = False
    result.update(
        {
            f"shell_environment_policy.set.{key}": value
            for key, value in command_environment(environment).items()
        }
    )
    return result


def selectors(task):
    return [
        {"environmentId": ENVIRONMENT_ID, "cwd": task.root, "runtimeWorkspaceRoots": [task.root]}
    ]


def verify_overrides(config, environment=None):
    features = config.get("features") or {}
    policy = config.get("shell_environment_policy") or {}
    if not isinstance(policy, dict):
        raise ConsoleError("app_executor_configuration", 503)
    _require_sdk_policy(policy, environment)
    variables = policy.get("set") or {}
    if not isinstance(variables, dict):
        raise ConsoleError("app_executor_configuration", 503)
    expected = command_environment(environment)
    mcp_servers = config.get("mcp_servers")
    if selected_profile(environment) == SDK_PROFILE and (
        mcp_servers is not None
        and (type(mcp_servers) is not dict or mcp_servers)
        or config.get("sandbox_mode") != "read-only"
        or config.get("approval_policy") != "never"
    ):
        raise ConsoleError("app_executor_configuration", 503)
    if (
        any(features.get(key) is not value for key, value in SAFE_FEATURES.items())
        or any(
            value.get("enabled") is not False
            for value in (config.get("mcp_servers") or {}).values()
        )
        or config.get("notify")
        or config.get("allow_login_shell") is not False
        or policy.get("inherit") != "none"
        or any(variables.get(key) != value for key, value in expected.items())
        or any(value for key, value in variables.items() if key not in expected)
    ):
        raise ConsoleError("app_executor_configuration", 503)
