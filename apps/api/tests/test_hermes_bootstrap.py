from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4


def _load_bootstrap(monkeypatch, config: dict[str, Any]):
    saved: list[dict[str, Any]] = []

    hermes_cli = ModuleType("hermes_cli")
    hermes_cli.__path__ = []  # type: ignore[attr-defined]
    config_module = ModuleType("hermes_cli.config")
    config_module.load_config = lambda: deepcopy(config)  # type: ignore[attr-defined]
    config_module.save_config = lambda value: saved.append(deepcopy(value))  # type: ignore[attr-defined]
    config_module.save_env_value = lambda _name, _value: None  # type: ignore[attr-defined]
    profiles_module = ModuleType("hermes_cli.profiles")
    profiles_module.list_profiles = lambda: []  # type: ignore[attr-defined]
    constants_module = ModuleType("hermes_constants")
    constants_module.get_hermes_home = lambda: Path("/tmp/hermes-test")  # type: ignore[attr-defined]
    constants_module.set_hermes_home_override = lambda _path: object()  # type: ignore[attr-defined]
    constants_module.reset_hermes_home_override = lambda _token: None  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config_module)
    monkeypatch.setitem(sys.modules, "hermes_cli.profiles", profiles_module)
    monkeypatch.setitem(sys.modules, "hermes_constants", constants_module)

    source = Path(__file__).resolve().parents[3] / "ops/hermes/bootstrap.py"
    module_name = f"miy_hermes_bootstrap_test_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, saved


def test_runtime_reconciliation_keeps_native_context_and_preserves_model_approvals(monkeypatch):
    config = {
        "plugins": {"enabled": ["miy_runtime"], "isolation": "host"},
        "model": {"provider": "custom:admitted", "model": "fixture"},
        "approvals": {"unattended_mode": "deny", "mode": "manual"},
    }
    module, saved = _load_bootstrap(monkeypatch, config)
    assert module._reconcile_runtime_config("miy-" + "a" * 32)
    assert saved[0]["plugins"]["isolation"] == "in_process"
    assert saved[0]["model"] == config["model"]
    assert saved[0]["approvals"] == config["approvals"]
