from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "miy_env_migrate", Path(__file__).resolve().parents[1] / "miy-env-migrate.py"
)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_keys_change_without_changing_credentials_resource_paths_or_line_endings():
    original = (
        '# MTY settings\r\nexport MTY_POSTGRES_DSN="postgresql://mty@localhost/mty_dev"\r\n'
        'VITE_MTY_DESKTOP_INSTALLER_URL_WIN=https://example.test/MTY.exe\r\n'
        'MTY_API_MTY_DESKTOP_UPDATE_DIRS="/data/mty"\r\nOTHER=MTY_SECRET\r\n'
    )
    updated, count = migration.rename_keys(original)
    assert count == 3
    assert updated == original.replace("export MTY_", "export MIY_").replace(
        "VITE_MTY_", "VITE_MIY_"
    ).replace("MTY_API_MTY_DESKTOP_UPDATE_DIRS=", "MIY_API_MIY_DESKTOP_UPDATE_DIRS=")
    assert migration.rename_keys(updated) == (updated, 0)


@pytest.mark.parametrize("text", [
    "MTY_A=one\nMIY_A=two\n", "MTY_A=one\nMTY_A=two\n",
    "MTY_A=one\nOTHER=${MTY_A}\n", 'OTHER="line\nMTY_A=secret\nend"\n',
])
def test_collisions_references_and_multiline_secret_changes_are_refused(text):
    with pytest.raises(ValueError):
        migration.rename_keys(text)


def test_apply_makes_private_backup_and_preview_leaves_file_intact(tmp_path):
    path = tmp_path / ".env"
    original = "MTY_SECRET=unchanged\n"
    path.write_text(original)
    path.chmod(0o600)
    assert migration.migrate(path, apply=False) == 1
    assert path.read_text() == original
    assert migration.migrate(path, apply=True) == 1
    assert path.read_text() == "MIY_SECRET=unchanged\n"
    backup, = tmp_path.glob(".env.backup-miy-*")
    assert backup.read_text() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


def test_symlink_and_public_permissions_are_refused(tmp_path):
    path = tmp_path / ".env"
    path.write_text("MTY_SECRET=unchanged\n")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        migration.migrate(path, apply=True)
    path.chmod(0o600)
    link = tmp_path / "linked.env"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        migration.migrate(link, apply=True)
