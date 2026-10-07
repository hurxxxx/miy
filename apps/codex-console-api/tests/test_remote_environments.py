import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codex_console import remote_environments
from codex_console.config import AppExecutionEnvironment
from codex_console.errors import ConsoleError
from codex_console.protocol_contract import REMOTE_SCHEMA_NAMES, _fingerprint
from codex_console.rpc import REMOTE_CONTRACT


def environment(root, **changes):
    return AppExecutionEnvironment(
        **{
            "key": "test-app-v1",
            "source_root": root,
            "exec_server_url": "ws://127.0.0.1:19391",
            "auth_bearer_token": "synthetic-executor-token-" + "x" * 32,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "url",
    [
        "ws://example.test:19391",
        "http://127.0.0.1:19391",
        "ws://127.0.0.1:80",
        "ws://user@127.0.0.1:19391",
        "ws://127.0.0.1:19391/redirect",
        "ws://127.0.0.1:19391?token=x",
    ],
)
def test_executor_endpoint_cannot_be_app_supplied_network_access(tmp_path, url):
    with pytest.raises(ValidationError):
        environment(tmp_path, exec_server_url=url)


def test_source_snapshot_pins_executor_and_new_config_cannot_retarget_existing_task(tmp_path):
    selected = environment(tmp_path)
    settings = SimpleNamespace(app_execution_environments=[selected])
    snapshot = remote_environments.binding_snapshot(settings, tmp_path)
    assert set(snapshot) == {"remote_environment_key", "remote_environment_digest"}
    assert "token" not in json.dumps(snapshot)
    task = SimpleNamespace(
        context={"source_binding": {"repository_root": str(tmp_path), **snapshot}},
        root=str(tmp_path),
        worktree_owned=False,
        template_snapshot=None,
    )
    assert remote_environments.for_task(settings, task) is selected
    settings.app_execution_environments = [
        environment(tmp_path, exec_server_url="ws://127.0.0.1:19392")
    ]
    with pytest.raises(ConsoleError, match="app_executor_changed"):
        remote_environments.for_task(settings, task)
    settings.app_execution_environments = []
    with pytest.raises(ConsoleError, match="app_executor_unavailable"):
        remote_environments.for_task(settings, task)


def test_unmapped_app_has_no_local_fallback_and_core_task_keeps_native_host_execution(tmp_path):
    settings = SimpleNamespace(app_execution_environments=[])
    assert remote_environments.binding_snapshot(settings, tmp_path) == {}
    assert remote_environments.for_task(settings, SimpleNamespace(context={})) is None
    task = SimpleNamespace(context={"source_binding": {"repository_root": str(tmp_path)}})
    with pytest.raises(ConsoleError, match="app_executor_unavailable"):
        remote_environments.for_task(settings, task)


def test_toml_provider_cannot_reenable_host_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    remote_environments.require_provider_boundary()
    (tmp_path / "environments.toml").write_text("include_local = true\n")
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.require_provider_boundary()


def test_remote_config_disables_host_hooks_mcp_and_inherited_set_values():
    selected = remote_environments.overrides(
        {
            "mcp_servers": {"configured-server": {"command": "must-not-run"}},
            "shell_environment_policy": {"set": {"SYNTHETIC_TOKEN": "must-not-leave-host"}},
        }
    )
    assert selected["mcp_servers.configured-server.enabled"] is False
    assert selected["features.hooks"] is False
    assert selected["features.skip_host_skill_discovery"] is True
    assert selected["features.shell_snapshot"] is False
    assert selected["notify"] == []
    assert selected["shell_environment_policy.inherit"] == "none"
    assert selected["shell_environment_policy.set.SYNTHETIC_TOKEN"] == ""
    assert "must-not-leave-host" not in json.dumps(selected)


@pytest.mark.parametrize(
    "config",
    [
        {"model_provider": "custom"},
        {"mcp_servers": {"unsafe.key": {}}},
        {"shell_environment_policy": {"set": {"unsafe.key": "x"}}},
        {"agents": {"custom": {"config_file": "/host/role.toml"}}},
    ],
)
def test_remote_config_rejects_uncontrolled_host_extensions(config):
    with pytest.raises(ConsoleError):
        remote_environments.overrides(config)


def test_supplemental_remote_contract_is_distinct_and_complete():
    assert REMOTE_CONTRACT["codexVersion"] == remote_environments.REMOTE_VERSION
    assert set(REMOTE_CONTRACT["schemas"]) == set(REMOTE_SCHEMA_NAMES)
    assert REMOTE_CONTRACT["compatibilityHashes"] == {
        name: _fingerprint(schema) for name, schema in REMOTE_CONTRACT["schemas"].items()
    }
    assert Path(__file__).parent.parent.joinpath("src/codex_console/protocol.json").exists()
