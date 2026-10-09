"""Pin explicitly selected historical migration cases in disposable worlds.

The ordinary migrated template and unselected cases still use repository head.
The original yielding world owns its clone and role cleanup. Selected cases use
normal guarded downgrade and unchanged ancestor scripts, never stamps or skips.
"""

from pathlib import Path
from shutil import copyfile

from alembic import command
from alembic.script import ScriptDirectory

import test_alembic_migrations as migration_tests
from test_official_writer_roles import sa_dsn


def migration_revision_world(
    current_head_world,
    request,
    tmp_path,
    monkeypatch,
    *,
    expected_revision,
    config_alias_module=None,
):
    revision = getattr(request, "param", None)
    if revision is None:
        return current_head_world
    assert revision == expected_revision
    original_config = migration_tests._migration_config
    config = original_config(sa_dsn(current_head_world.dsn))
    ancestors = list(ScriptDirectory.from_config(config).walk_revisions(base="base", head=revision))
    command.downgrade(config, revision)
    versions = tmp_path / "migration_contract_versions"
    versions.mkdir()
    for ancestor in ancestors:
        source = Path(ancestor.path)
        copyfile(source, versions / source.name)

    def revision_config(dsn=None):
        scoped = original_config(dsn)
        scoped.set_main_option("version_locations", str(versions))
        return scoped

    monkeypatch.setattr(migration_tests, "_migration_config", revision_config)
    if config_alias_module is not None:
        # A module-level `from ... import _migration_config` retains its original
        # object, unlike per-test imports. Restore this alias with the same case.
        monkeypatch.setattr(f"{config_alias_module}._migration_config", revision_config)
    return current_head_world
