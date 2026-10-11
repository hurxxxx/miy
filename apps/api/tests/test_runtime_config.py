from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from miy_api.core import settings
from miy_api.core.runtime_config import (
    RuntimeConfigError,
    runtime_defaults,
)

POOL_KEY = "MIY_API_DB_POOL_SIZE"


@pytest.fixture
def config_root(tmp_path, monkeypatch):
    source_root = settings.WORKSPACE_ROOT
    shutil.copytree(source_root / "config", tmp_path / "config")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    return tmp_path


def update_config(root: Path, change) -> None:
    path = root / "config/runtime.json"
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


def test_profile_dotenv_environment_and_explicit_setting_priority(config_root, monkeypatch):
    update_config(config_root, lambda doc: doc["profiles"]["dev"].update({POOL_KEY: 3}))
    monkeypatch.setenv("MIY_ENV_PROFILE", "dev")
    monkeypatch.delenv(POOL_KEY, raising=False)
    env = config_root / ".env"
    env.write_text("# no override\n")
    assert settings.Settings(_env_file=env).db_pool_size == 3
    env.write_text(f"{POOL_KEY}=6\n")
    assert settings.Settings(_env_file=env).db_pool_size == 6
    monkeypatch.setenv(POOL_KEY, "7")
    assert settings.Settings(_env_file=env).db_pool_size == 7
    assert settings.Settings(_env_file=env, **{POOL_KEY: 8}).db_pool_size == 8
    assert settings.Settings(_env_file=env, db_pool_size=9).db_pool_size == 9
    monkeypatch.setenv(POOL_KEY, "0")
    with pytest.raises(ValidationError):
        settings.Settings(_env_file=env)


@pytest.mark.parametrize(
    "change",
    [
        lambda doc: doc["defaults"].update({"MIY_HERMES_API_KEY": "synthetic-secret"}),
        lambda doc: doc["defaults"].pop(POOL_KEY),
        lambda doc: doc.update(version=99),
    ],
)
def test_invalid_config_fails_without_exposing_values(config_root, change):
    update_config(config_root, change)
    with pytest.raises(RuntimeConfigError) as caught:
        runtime_defaults(config_root)
    assert "synthetic-secret" not in str(caught.value)
