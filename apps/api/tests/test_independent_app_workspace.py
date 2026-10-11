import importlib.util
from pathlib import Path


def helper():
    path = Path(__file__).resolve().parents[3] / "scripts/prepare-independent-app-workspace.py"
    loader = importlib.util.spec_from_file_location("app_workspace", path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module
