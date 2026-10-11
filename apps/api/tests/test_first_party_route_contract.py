from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from miy_api.first_party_route_contract import (
    generated_route_contract,
    native_route_contract,
)


def test_generated_ingress_contract_matches_actual_http_and_websocket_inventory():
    generated = generated_route_contract()
    assert generated == native_route_contract()
    routes = {(route["path"], route["owner"]) for route in generated["routes"]}
    assert any(
        path.startswith("/docs/collab/pages/") for path, owner in routes if owner == "official"
    )
    assert any(
        path.startswith("/whiteboard/collab/items/")
        for path, owner in routes
        if owner == "official"
    )
    assert any(path.startswith("/realtime/") for path, owner in routes if owner == "platform")


def test_public_projection_and_cli_need_no_app_settings_in_fresh_process(tmp_path):
    # Copy only public package source into a workspace without an ignored .env.
    # API conftest's synthetic settings and the caller's credentials cannot mask
    # an accidental import-time application dependency in this fresh process.
    package = Path(__file__).resolve().parents[1] / "src" / "miy_api"
    isolated_source = tmp_path / "repo" / "apps" / "api" / "src"
    shutil.copytree(
        package, isolated_source / "miy_api", ignore=shutil.ignore_patterns("__pycache__")
    )
    program = """
import contextlib, io, json, runpy, sys
from miy_api.first_party_routes import api_owner_inventory, nginx_owner_map, nginx_client_owner_map
inventory = api_owner_inventory(api_prefix='/tenant/api')
assert inventory['api_prefix'] == '/tenant/api'
assert inventory['official_patterns']
assert all(pattern.startswith('^/tenant/api/') for pattern in inventory['official_patterns'])
assert '(?P<' not in nginx_owner_map(api_prefix='/tenant/api')
assert '/apps/docs' in nginx_client_owner_map()
for flags in [('--json', '--api-prefix', '/tenant/api'), ('--nginx-map',), ('--client-map',)]:
    sys.argv = ['miy_api.first_party_routes', *flags]
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        runpy.run_module('miy_api.first_party_routes', run_name='__main__')
    if flags[0] == '--json':
        assert json.loads(output.getvalue()) == inventory
    else:
        assert 'default platform;' in output.getvalue()
assert 'miy_api.core.settings' not in sys.modules
assert 'miy_api.api_registry' not in sys.modules
assert not any(name.startswith('miy_api.domains.') for name in sys.modules)
print('settings-free native projections: PASS')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env={"PYTHONPATH": str(isolated_source), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "settings-free native projections: PASS"
