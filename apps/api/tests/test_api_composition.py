from __future__ import annotations

import pytest

from miy_api import app as app_module
from miy_api.api_registry import router_specs


def test_unknown_composition_cannot_fall_back_to_legacy() -> None:
    with pytest.raises(ValueError, match="Unsupported API composition"):
        app_module.create_app(composition="future-profile", initialize_runtime=False)
    with pytest.raises(ValueError, match="Unsupported API composition"):
        router_specs("future-profile")
