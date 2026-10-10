import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codex_console import remote_environments, toolchain_profiles
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


@pytest.mark.parametrize(
    "profile", [None, toolchain_profiles.NATIVE_PROFILE, toolchain_profiles.SDK_PROFILE]
)
def test_implementation_choices_follow_current_server_binding_and_preserve_native_behavior(
    tmp_path, profile
):
    selected = environment(tmp_path, **({"toolchain_profile": profile} if profile else {}))
    settings = SimpleNamespace(app_execution_environments=[selected])
    task = SimpleNamespace(
        context={
            "source_binding": {
                "repository_root": str(tmp_path),
                **remote_environments.binding_snapshot(settings, tmp_path),
            }
        },
        root=str(tmp_path),
        worktree_owned=False,
        template_snapshot=None,
    )
    assert remote_environments.implementation_permissions(settings, task) == (
        ["ask"] if profile == toolchain_profiles.SDK_PROFILE else ["ask", "yolo"]
    )
    assert remote_environments.implementation_permissions(
        settings, SimpleNamespace(context={})
    ) == ["ask", "yolo"]


@pytest.mark.parametrize("change", ["removed", "retargeted", "profile", "worktree"])
def test_changed_binding_advertises_no_execution_choices_without_changing_history(tmp_path, change):
    from codex_console.schemas import TaskDetail

    selected = environment(tmp_path)
    settings = SimpleNamespace(app_execution_environments=[selected])
    task = SimpleNamespace(
        context={
            "source_binding": {
                "repository_root": str(tmp_path),
                **remote_environments.binding_snapshot(settings, tmp_path),
            }
        },
        root=str(tmp_path),
        worktree_owned=False,
        template_snapshot=None,
    )
    if change == "removed":
        settings.app_execution_environments = []
    elif change == "retargeted":
        settings.app_execution_environments = [
            environment(tmp_path, exec_server_url="ws://127.0.0.1:19392")
        ]
    elif change == "profile":
        settings.app_execution_environments = [
            environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
        ]
    else:
        task.worktree_owned = True
    permissions = remote_environments.implementation_permissions(settings, task)
    assert permissions == []
    with pytest.raises(ConsoleError):
        remote_environments.for_task(settings, task)  # Actual execution still refuses.
    history = [
        {
            "id": "same-item",
            "type": "agentMessage",
            "text": "synthetic history",
            "turn_id": "same-turn",
        }
    ]
    detail = TaskDetail(
        id="same-task",
        title="synthetic",
        stage="plan",
        status="idle",
        thread_id="same-thread",
        turn_id=None,
        root=str(tmp_path),
        isolated=False,
        approved_revision=None,
        error_code=None,
        updated_at="2026-10-09T00:00:00Z",
        implementation_permissions=permissions,
        revisions=[],
        items=history,
        history_truncated=False,
        requests=[],
        event_id=1,
        attachments=[],
        attachment_limits={"file_bytes": 1, "task_bytes": 1, "files": 1, "selection": 1},
    )
    assert detail.model_dump()["items"] == history and detail.thread_id == "same-thread"


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


def remote_configuration(selected):
    return {
        "features": remote_environments.SAFE_FEATURES,
        "mcp_servers": {},
        "notify": [],
        "allow_login_shell": False,
        "sandbox_mode": "read-only",
        "approval_policy": "never",
        "shell_environment_policy": {
            "inherit": "none",
            "set": toolchain_profiles.command_environment(selected),
        },
    }


def test_selected_sdk_profile_flows_through_official_override_and_exact_verification(tmp_path):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    overrides = remote_environments.overrides(
        {"shell_environment_policy": {"set": {"SYNTHETIC_TOKEN": "host-private"}}}, selected
    )
    assert overrides["shell_environment_policy.inherit"] == "none"
    assert overrides["shell_environment_policy.set.SYNTHETIC_TOKEN"] == ""
    for name, value in toolchain_profiles.command_environment(selected).items():
        assert overrides["shell_environment_policy.set." + name] == value
    assert "host-private" not in json.dumps(overrides)
    configuration = remote_configuration(selected)
    configuration["shell_environment_policy"]["set"]["SYNTHETIC_TOKEN"] = ""
    remote_environments.verify_overrides(configuration, selected)
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.verify_overrides(configuration)


@pytest.mark.parametrize("kind", ["inherited", "wrong-path", "host-extra", "missing-pythonpath"])
def test_sdk_override_tampering_refuses(tmp_path, kind):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    configuration = remote_configuration(selected)
    policy = configuration["shell_environment_policy"]
    if kind == "inherited":
        policy["inherit"] = "all"
    elif kind == "wrong-path":
        policy["set"]["PATH"] = "/synthetic-host/bin"
    elif kind == "host-extra":
        policy["set"]["SYNTHETIC_SECRET"] = "must-not-transfer"
    else:
        del policy["set"]["PYTHONPATH"]
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.verify_overrides(configuration, selected)


def test_toolchain_change_retargets_no_existing_task_and_default_digest_is_unchanged(tmp_path):
    selected = environment(tmp_path)
    public = {
        "key": selected.key,
        "source_root": str(tmp_path),
        "exec_server_url": selected.exec_server_url,
        "profile": 1,
    }
    import hashlib

    assert (
        remote_environments.fingerprint(selected)
        == hashlib.sha256(
            json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    snapshot = remote_environments.binding_snapshot(
        SimpleNamespace(app_execution_environments=[selected]), tmp_path
    )
    task = SimpleNamespace(
        context={"source_binding": {"repository_root": str(tmp_path), **snapshot}},
        root=str(tmp_path),
        worktree_owned=False,
        template_snapshot=None,
    )
    changed = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    assert remote_environments.fingerprint(changed) != remote_environments.fingerprint(selected)
    with pytest.raises(ConsoleError, match="app_executor_changed"):
        remote_environments.for_task(SimpleNamespace(app_execution_environments=[changed]), task)


def test_app_cannot_supply_arbitrary_toolchain_or_environment_fields(tmp_path):
    with pytest.raises(ValidationError):
        environment(tmp_path, toolchain_profile="custom")
    with pytest.raises(ValidationError):
        environment(
            tmp_path,
            toolchain_profile=toolchain_profiles.SDK_PROFILE,
            environment={"PATH": "/host"},
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("include_only", ["PATH"]),
        ("filters", {"PATH": "include"}),
        ("experimental_use_profile", True),
    ],
)
def test_sdk_profile_refuses_host_filters_or_profile_evaluation(tmp_path, field, value):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    config = remote_configuration(selected)
    config["shell_environment_policy"][field] = value
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.overrides(config, selected)
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.verify_overrides(config, selected)


def test_sdk_host_mcp_names_and_transports_never_enter_startup_overrides(tmp_path):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    overrides = remote_environments.overrides(
        {
            "mcp_servers": {
                "arbitrary.name": {"command": "synthetic-must-not-run"},
                "유니코드/서버": {"url": "https://synthetic.invalid/private"},
            }
        },
        selected,
    )
    assert not any(key.startswith("mcp_servers") for key in overrides)
    assert "synthetic-must-not-run" not in json.dumps(overrides)
    assert "synthetic.invalid" not in json.dumps(overrides)
    assert overrides["sandbox_mode"] == "read-only" and overrides["approval_policy"] == "never"
    native = remote_environments.overrides({"mcp_servers": {"server": {"command": "synthetic"}}})
    assert native["mcp_servers.server.enabled"] is False and "sandbox_mode" not in native


@pytest.mark.parametrize(
    "value", [{"configured": {"enabled": True}}, {"configured": {"enabled": False}}, [], False, ""]
)
def test_sdk_raw_mcp_inventory_refuses_including_disabled_entries_and_wrong_types(tmp_path, value):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    config = remote_configuration(selected)
    config["mcp_servers"] = value
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.verify_overrides(config, selected)


@pytest.mark.parametrize(
    "field,value", [("sandbox_mode", "workspace-write"), ("approval_policy", "on-request")]
)
def test_sdk_bootstrap_configuration_cannot_silently_inherit_host_defaults(tmp_path, field, value):
    selected = environment(tmp_path, toolchain_profile=toolchain_profiles.SDK_PROFILE)
    config = remote_configuration(selected)
    config[field] = value
    with pytest.raises(ConsoleError, match="app_executor_configuration"):
        remote_environments.verify_overrides(config, selected)
