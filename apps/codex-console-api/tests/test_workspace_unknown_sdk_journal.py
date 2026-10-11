"""The real operator journal is reconciled without repeating a native start."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_console import workspace_environment as environment
from codex_console.errors import ConsoleError

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "managed_sdk_journal_fixture", ROOT / "scripts/tests/test_workbench_environment.py"
)
fixture_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_module)


@pytest.fixture
def sdk_journal(monkeypatch):
    fixture = fixture_module.ManagedEnvironmentTests()
    fixture.setUp()
    calls, requests = [], []
    snapshot = {**fixture.snapshot, "preview": {"state": "unconfigured"}}
    settings = SimpleNamespace(miy_api_origin=None, app_delivery_grants=[])

    def actual_manage(cfg, selected, action):
        calls.append(action)
        try:
            return fixture.action(action, environment._public(selected))
        except fixture_module.helper.Refused as error:
            raise ConsoleError(str(error), 409) from None

    async def core_read(cfg, selected, suffix, body=None, **kwargs):
        assert suffix == "/context" and body is None
        requests.append(suffix)
        return None

    monkeypatch.setattr(environment, "_helper", actual_manage)
    monkeypatch.setattr(environment, "_call", core_read)
    try:
        yield fixture, settings, snapshot, calls, requests
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize("kind,has_core", [("create", False), ("resume", False), ("resume", True)])
def test_unknown_start_journal_reconciles_existing_execution_without_restart(
    sdk_journal, monkeypatch, kind, has_core
):
    fixture, settings, snapshot, calls, requests = sdk_journal
    fixture.native.fail_ready = True
    with pytest.raises(fixture_module.helper.Refused, match="workspace_operation_unknown"):
        fixture.action("prepare")
    journal_path = fixture.private("journal.json")
    original_descriptor = fixture.private("descriptor.json").read_bytes()
    assert fixture_module.helper.read_json(journal_path)["state"] == "unknown"
    fixture.native.fail_ready = False
    assert fixture.action("status") == {"state": "unknown"}
    original_commands = fixture.native.commands.copy()
    if has_core:
        snapshot["preview"] = {
            "state": "stopped",
            "installation_id": "disposable-core-installation",
            "portal_url": "https://portal.invalid/existing-installation",
            "runtime_revision": "c" * 40,
        }

        async def core_read(cfg, selected, suffix, body=None, **kwargs):
            assert suffix == "/context" and body is None
            requests.append(suffix)
            return {"state": "ready", "source_handoff_complete": False}

        monkeypatch.setattr(environment, "_call", core_read)
    result = asyncio.run(
        environment.observe(settings, snapshot, "same-intent", kind, snapshot["source_revision"])
    )
    assert result is not None
    assert result["state"] == "ready" and result["environment"]["state"] == "ready"
    assert result["preview"]["state"] == ("configured" if has_core else "unconfigured")
    assert result["preview"]["runtime_revision"] == ("c" * 40 if has_core else None)
    assert result["preview"]["runtime_revision"] != snapshot["source_revision"]
    assert calls == ["status", "describe"] and requests == ["/context"]
    assert fixture_module.helper.read_json(journal_path)["state"] == "ready"
    assert fixture.action("status") == {"state": "ready"}
    assert fixture.private("descriptor.json").read_bytes() == original_descriptor
    assert fixture.native.commands == original_commands
    assert sum(command[0] == "start" for command in original_commands) == 1


@pytest.mark.parametrize(
    "missing", ["native_readiness", "owned_unit_bytes", "source_binding", "core_prepare_result"]
)
def test_unknown_create_journal_does_not_override_missing_native_or_core_proof(
    sdk_journal, missing
):
    fixture, settings, snapshot, calls, requests = sdk_journal
    fixture.native.fail_ready = True
    with pytest.raises(fixture_module.helper.Refused, match="workspace_operation_unknown"):
        fixture.action("prepare")
    journal_path = fixture.private("journal.json")
    original_journal = journal_path.read_bytes()
    original_commands = fixture.native.commands.copy()
    if missing != "native_readiness":
        fixture.native.fail_ready = False
    if missing == "owned_unit_bytes":
        unit = next(fixture.config["unit_root"].iterdir())
        unit.write_bytes(unit.read_bytes() + b"# changed owned bytes\n")
    elif missing == "source_binding":
        snapshot["branch"] = "feature/other"
    elif missing == "core_prepare_result":
        snapshot["operation_receipt"] = {"core": {"stage": "/prepare", "acknowledged": False}}
    if missing == "core_prepare_result":
        assert (
            asyncio.run(
                environment.observe(
                    settings, snapshot, "same-intent", "create", snapshot["source_revision"]
                )
            )
            is None
        )
        assert calls == []
    else:
        with pytest.raises(ConsoleError):
            asyncio.run(
                environment.observe(
                    settings, snapshot, "same-intent", "create", snapshot["source_revision"]
                )
            )
        assert calls == (["status", "describe"] if missing == "native_readiness" else ["status"])
    assert requests == ["/context"] and fixture.native.commands == original_commands
    assert journal_path.read_bytes() == original_journal
    assert fixture_module.helper.read_json(journal_path)["state"] == "unknown"


@pytest.mark.parametrize("native_action", ["stop", "cleanup"])
def test_existing_stopped_or_cleaned_sdk_is_not_reclassified_ready_by_create_observation(
    sdk_journal, native_action
):
    fixture, settings, snapshot, calls, requests = sdk_journal
    fixture.action("prepare")
    fixture.action(native_action)
    original_commands = fixture.native.commands.copy()
    original_journal = fixture.private("journal.json").read_bytes()
    assert (
        asyncio.run(
            environment.observe(
                settings, snapshot, "same-intent", "create", snapshot["source_revision"]
            )
        )
        is None
    )
    assert calls == ["status"] and requests == ["/context"]
    assert fixture.native.commands == original_commands
    assert fixture.private("journal.json").read_bytes() == original_journal
