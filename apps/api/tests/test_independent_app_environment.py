from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "independent_app_env", ROOT / "scripts/independent-app-env.py"
)
env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(env)
IMAGE = "registry.test/core/app@sha256:" + "a" * 64
