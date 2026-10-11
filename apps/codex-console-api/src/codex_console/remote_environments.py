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
from .toolchain_profiles import binding_identity, command_environment, is_sdk_profile


def _require_sdk_policy(policy, environment):
    # Official v0.160.1 filters include_only after applying explicit set values.
    # Host profile evaluation must also stay off for this fixed command profile.
    if is_sdk_profile(environment) and (
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
    if source.get("workspace_id"):
        from . import workspace_environment

        environment = workspace_environment.environment_for(settings, source["managed_workspace"])
        if (
            task.workspace_id != source["workspace_id"]
            or str(environment.source_root) != source.get("executor_root")
            or Path(task.root) != environment.source_root
            or source.get("remote_environment_digest") != fingerprint(environment)
            or task.worktree_owned
        ):
            raise ConsoleError("app_executor_changed", 409)
        return environment
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


def for_restrictive_task(settings, task, environment):
    """Validate the original live controller's identity without readiness probes.

    Only its owner may decline an existing request or interrupt an existing turn.
    This does not select an executor, reconnect or admit any new execution.
    """
    source = (task.context or {}).get("source_binding") or {}
    if environment is None or not source:
        raise ConsoleError("app_executor_unavailable", 503)
    try:
        changed = (
            source.get("remote_environment_key") != environment.key
            or source.get("remote_environment_digest") != fingerprint(environment)
            or task.worktree_owned
        )
        if source.get("workspace_id"):
            managed = source["managed_workspace"]
            expected = Path(managed["worktree_path"]) / managed["app_directory"]
            changed |= (
                task.workspace_id != source["workspace_id"]
                or (task.context or {}).get("workspace_id") != source["workspace_id"]
                or managed["id"] != source["workspace_id"]
                or managed["app_id"] != source.get("app_id")
                or (task.context or {}).get("app_id") != source.get("app_id")
                or source.get("executor_root") != str(expected)
                or environment.source_root != expected
                or Path(task.root) != expected
                or expected.resolve() != expected
            )
        else:
            selected = next(
                (
                    item
                    for item in settings.app_execution_environments
                    if item.key == environment.key
                ),
                None,
            )
            changed |= (
                selected is None
                or fingerprint(selected) != fingerprint(environment)
                or source.get("repository_root") != str(environment.source_root)
                or not Path(task.root).is_relative_to(environment.source_root)
            )
        if changed:
            raise ConsoleError("app_executor_changed", 409)
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ConsoleError("app_executor_changed", 409) from None
    return environment


def implementation_permissions(settings, task):
    """Advertise current choices without making stale task history unreadable."""
    try:
        environment = for_task(settings, task)
        return ["ask"] if is_sdk_profile(environment) else ["ask", "yolo"]
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
    sdk = is_sdk_profile(environment)
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
    if is_sdk_profile(environment):
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
    if is_sdk_profile(environment) and (
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
