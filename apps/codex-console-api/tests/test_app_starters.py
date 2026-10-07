import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from codex_console import app_starters
from codex_console.errors import ConsoleError

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "starter_generator", ROOT / "scripts/generate-app-starters.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def fixture_root(tmp_path):
    for name in ("templates/independent-app", "templates/independent-app-data", "packages/app-sdk"):
        shutil.copytree(
            ROOT / name,
            tmp_path / name,
            ignore=shutil.ignore_patterns("node_modules", "dist", "__pycache__", ".pytest_cache"),
        )
    return tmp_path


def test_packaged_bundle_matches_canonical_source_exactly():
    expected = generator.generate(ROOT)
    assert app_starters.bundle() == expected
    first = expected["templates"]["basic"]["files"]
    second = expected["templates"]["private-notes"]["files"]
    assert first["business.py"] == (ROOT / "templates/independent-app/business.py").read_text()
    assert (
        second["business.py"] == (ROOT / "templates/independent-app-data/business.py").read_text()
    )
    assert (
        first["vendor/miy-app-sdk/src/index.mjs"]
        == (ROOT / "packages/app-sdk/src/index.mjs").read_text()
    )
    assert "AGENTS.md" in first and "AGENTS.md.template" not in first
    contract = json.loads(
        (
            ROOT / "apps/codex-console-api/src/codex_console/independent_app_schema.generated.json"
        ).read_text()
    )
    for item in expected["templates"].values():
        Draft202012Validator(contract).validate(json.loads(item["files"]["app.manifest.json"]))


def test_bundle_runs_without_a_platform_checkout(tmp_path):
    package = ROOT / "apps/codex-console-api/src/codex_console"
    shutil.copytree(
        package, tmp_path / "codex_console", ignore=shutil.ignore_patterns("__pycache__")
    )
    command = """from codex_console.app_starters import bundle, render
value=bundle()
for key in value['templates']:
 files=render(key, app_id='isolated-app', title='Independent artifact',
              repository='https://example.test/independent.git',
              expected_digest=value['bundle_digest'])
 assert 'app.manifest.json' in files and 'vendor/miy-app-sdk/src/index.mjs' in files
print('Both packaged starters available without platform source')
"""
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Both packaged starters available without platform source"


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "hard-link", "secret"])
def test_generator_rejects_unsafe_canonical_inputs(tmp_path, kind):
    root = fixture_root(tmp_path / "repo")
    source = root / "templates/independent-app"
    other = tmp_path / "outside.txt"
    other.write_text("Synthetic public fixture")
    if kind == "file-link":
        (source / "linked.txt").symlink_to(other)
    elif kind == "directory-link":
        (source / "linked").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "hard-link":
        os.link(other, source / "linked.txt")
    else:
        (source / ".env").write_text("Do not include")
    with pytest.raises((ValueError, OSError)):
        generator.generate(root)


def test_old_bundle_digest_cannot_silently_select_new_template():
    with pytest.raises(ConsoleError, match="app_setup_bundle_changed"):
        app_starters.render(
            "basic",
            app_id="sample-app",
            title="App",
            repository="https://example.test/app.git",
            expected_digest="sha256:" + "0" * 64,
        )


@pytest.mark.parametrize("app_id", ["a", "7-demo", "a" * 65])
def test_invalid_canonical_identifier_is_a_typed_preparation_rejection(app_id):
    with pytest.raises(ConsoleError, match="app_setup_invalid"):
        app_starters.render(
            "basic",
            app_id=app_id,
            title="App",
            repository="https://example.test/app.git",
            expected_digest=app_starters.bundle()["bundle_digest"],
        )
