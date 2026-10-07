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


def require_provider_boundary():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    # The official TOML provider takes precedence over CODEX_EXEC_SERVER_URL.
    # Never silently accept a provider that might expose a local executor.
    if (home / "environments.toml").exists():
        raise ConsoleError("app_executor_configuration", 503)


def overrides(config):
    if (config.get("model_provider") or "openai") != "openai":
        raise ConsoleError("subscription_provider_required")
    names = config.get("mcp_servers") or {}
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
            "shell_environment_policy.set.PATH": "/usr/local/bin:/usr/bin:/bin",
            "shell_environment_policy.set.HOME": "/tmp",
        }
    )
    return result


def selectors(task):
    return [
        {"environmentId": ENVIRONMENT_ID, "cwd": task.root, "runtimeWorkspaceRoots": [task.root]}
    ]


def verify_overrides(config):
    features = config.get("features") or {}
    policy = config.get("shell_environment_policy") or {}
    variables = policy.get("set") or {}
    if (
        any(features.get(key) is not value for key, value in SAFE_FEATURES.items())
        or any(
            value.get("enabled") is not False
            for value in (config.get("mcp_servers") or {}).values()
        )
        or config.get("notify")
        or config.get("allow_login_shell") is not False
        or policy.get("inherit") != "none"
        or variables.get("PATH") != "/usr/local/bin:/usr/bin:/bin"
        or variables.get("HOME") != "/tmp"
        or any(value for key, value in variables.items() if key not in {"PATH", "HOME"})
    ):
        raise ConsoleError("app_executor_configuration", 503)
