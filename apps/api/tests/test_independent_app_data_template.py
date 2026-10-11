from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def notes_app(monkeypatch):
    installation = str(uuid4())
    for key, value in {
        "MIY_APP_ID": "private-notes",
        "MIY_APP_INSTALLATION_ID": installation,
        "MIY_APP_ORIGIN": "https://notes.test",
        "MIY_APP_PLATFORM_ORIGIN": "https://platform.test",
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        "business", ROOT / "templates/independent-app-data/business.py"
    )
    business = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(business)
    monkeypatch.setitem(sys.modules, "business", business)
    spec = importlib.util.spec_from_file_location(
        "notes_app", ROOT / "templates/independent-app/api.py"
    )
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api, installation
