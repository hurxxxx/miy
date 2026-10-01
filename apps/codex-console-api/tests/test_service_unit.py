from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("service", ["codex-console", "codex-console-templates"])
def test_console_service_preserves_host_privileges_for_native_yolo_turns(service):
    unit = (ROOT / f"ops/codex-console/{service}.service").read_text()
    directives = {
        line.strip()
        for line in unit.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "NoNewPrivileges=false" in directives
    assert "NoNewPrivileges=true" not in directives
