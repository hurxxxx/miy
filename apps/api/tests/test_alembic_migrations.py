from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from miy_api.core import db as db_module


def test_runtime_alembic_config_uses_workspace_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    api_root = tmp_path / "apps" / "api"
    api_root.mkdir(parents=True)
    ini_path = api_root / "alembic.ini"
    ini_path.write_text(
        "[alembic]\nscript_location = %(here)s/alembic\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db_module, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(
        db_module,
        "get_settings",
        lambda: SimpleNamespace(postgres_dsn="sqlite:///runtime-test.db"),
    )

    config = db_module._alembic_config()

    assert Path(config.config_file_name or "") == ini_path
    assert config.get_main_option("script_location") == str(api_root / "alembic")
    assert config.get_main_option("sqlalchemy.url") == "sqlite:///runtime-test.db"


def _migration_config(dsn: str | None = None) -> Config:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    if dsn:
        config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))
    return config


@pytest.mark.migration
def test_repository_starts_at_company_deployment_baseline() -> None:
    revisions = list(ScriptDirectory.from_config(_migration_config()).walk_revisions())
    assert [revision.revision for revision in revisions] == [
        "wb_actor_acl_20261009",
        "wb_actor_owner_20261009",
        "wb_source_writer_20261009",
        "file_effect_20261007",
        "file_source_partition_20261007",
        "file_projection_20261007",
        "file_extraction_20261007",
        "official_partition_20261007",
        "recording_managed_20261007",
        "docs_legacy_repair_20261007",
        "official_projection_20261007",
        "official_source_writer_20261007",
        "official_dm_writer_20261007",
        "registration_auth_20261007",
        "official_planner_writer_20261006",
        "official_widget_writer_20261006",
        "independent_bootstrap_20261006",
        "official_writer_roles_20261006",
        "official_writer_fence_20261006",
        "official_auth_binding_20261006",
        "independent_delegation_20261006",
        "independent_delivery_20261006",
        "independent_apps_20261006",
        "artifact_sequences_20261006",
        "miy_api_keys_20261001",
        "decision_defaults_20260927",
        "llm_cap_defaults_20260918",
        "llm_connections_20260918",
        "hermes_initial_snapshot_20260914",
        "hermes_file_versions_20260914",
        "hermes_runtime_20260912",
        "group_sources_20260912",
        "company_20260908",
    ]
    for newer, older in zip(revisions, revisions[1:]):
        assert newer.down_revision == older.revision
    assert revisions[-1].down_revision is None
    assert "clean deployment baseline" in revisions[-1].doc


@pytest.mark.migration
def test_writer_fence_upgrade_and_schema_rollback_preserve_existing_sources(
    postgres_dsn: str,
) -> None:
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "official_auth_binding_20261006")
    engine = sa.create_engine(postgres_dsn)
    try:
        assert engine.url.database.startswith("miy_test_")
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                INSERT INTO users (id, login_id, email, full_name, password_hash, status,
                    login_blocked, must_change_password, theme_preference, locale,
                    time_zone, date_format, created_at, updated_at)
                VALUES ('writer-migration-user', 'writer-migration-user',
                    'writer@example.test', 'Writer fixture', 'fixture', 'active', false,
                    false, 'system', 'ko-KR', 'Asia/Seoul', 'korean', now(), now())
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO announcements
                    (id, author_id, scope, title, body, is_pinned, created_at, updated_at)
                VALUES ('writer-migration-source', 'writer-migration-user', 'company',
                    'Existing announcement', 'Preserved body', false, now(), now())
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO docs_collections
                    (id, scope, owner_id, name, sort_order, created_at, updated_at)
                VALUES ('writer-migration-collection', 'private', 'writer-migration-user',
                    'Existing collection', 0, now(), now());
                INSERT INTO docs_native_docs
                    (id, owner_id, collection_id, company_visible, ownership_kind, title,
                     doc_type, source_app, source_kind, generation_kind, rag_scope,
                     created_at, updated_at)
                VALUES ('writer-migration-doc', 'writer-migration-user',
                    'writer-migration-collection', false, 'personal', 'Existing document',
                    'general', 'docs', 'manual', 'human', 'official', now(), now());
                INSERT INTO docs_native_doc_pages
                    (id, doc_id, title, content_format, content_blocks, sort_order,
                     created_by_id, created_at, updated_at)
                VALUES ('writer-migration-page', 'writer-migration-doc', 'Existing page',
                    'block', '[]', 0, 'writer-migration-user', now(), now());
                INSERT INTO docs_collab_documents
                    (id, room_key, source_type, source_page_id, yjs_state,
                     snapshot_content_blocks, created_at, updated_at)
                VALUES ('writer-migration-collab', 'existing-room', 'native_doc_page',
                    'writer-migration-page', decode('0000', 'hex'), '[]', now(), now())
            """)
            )
        command.upgrade(config, "official_writer_fence_20261006")
        with engine.begin() as conn:
            assert conn.execute(
                sa.text("""
                SELECT writer_scope, title, body FROM announcements
                WHERE id = 'writer-migration-source'
            """)
            ).one() == ("official.suite", "Existing announcement", "Preserved body")
            assert conn.execute(
                sa.text("""
                SELECT active_owner, generation, artifact, state
                FROM official_runtime_ownership
            """)
            ).one() == ("legacy", 1, None, "active")
            # The existing service omits writer_scope and runtime assertion.
            conn.execute(sa.text("UPDATE announcements SET title = 'Legacy still writes'"))
            assert (
                conn.scalar(sa.text("SELECT writer_scope FROM docs_native_docs"))
                == "official.suite"
            )
            conn.execute(sa.text("UPDATE docs_native_docs SET title = 'Legacy Docs still writes'"))
            assert (
                conn.scalar(sa.text("SELECT yjs_state FROM docs_collab_documents")) == b"\x00\x00"
            )
        command.downgrade(config, "official_auth_binding_20261006")
        assert "writer_scope" not in {
            column["name"] for column in sa.inspect(engine).get_columns("announcements")
        }
        assert "writer_scope" not in {
            column["name"] for column in sa.inspect(engine).get_columns("docs_native_docs")
        }
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT title, body FROM announcements")).one() == (
                "Legacy still writes",
                "Preserved body",
            )
            assert (
                conn.scalar(sa.text("SELECT title FROM docs_native_docs"))
                == "Legacy Docs still writes"
            )
            assert (
                conn.scalar(sa.text("SELECT title FROM docs_native_doc_pages")) == "Existing page"
            )
            assert (
                conn.scalar(sa.text("SELECT yjs_state FROM docs_collab_documents")) == b"\x00\x00"
            )
            assert (
                conn.scalar(
                    sa.text("""
                SELECT count(*) FROM pg_trigger
                WHERE tgname = 'miy_official_source_writer' AND tgrelid = 'announcements'::regclass
            """)
                )
                == 0
            )
        command.upgrade(config, "official_writer_fence_20261006")
        with engine.connect() as conn:
            assert conn.scalar(sa.text("SELECT body FROM announcements")) == "Preserved body"
            assert (
                conn.scalar(sa.text("SELECT title FROM docs_native_docs"))
                == "Legacy Docs still writes"
            )
            assert (
                conn.scalar(sa.text("SELECT name FROM docs_collections")) == "Existing collection"
            )
            assert (
                conn.scalar(sa.text("SELECT yjs_state FROM docs_collab_documents")) == b"\x00\x00"
            )
            assert (
                conn.scalar(
                    sa.text("""
                SELECT count(*) FROM pg_trigger
                WHERE tgname = 'miy_official_source_writer' AND tgrelid = 'announcements'::regclass
            """)
                )
                == 1
            )
    finally:
        engine.dispose()


@pytest.mark.migration
def test_fresh_baseline_owns_company_identity_and_app_local_resources(postgres_dsn: str) -> None:
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "group_sources_20260912")
    engine = sa.create_engine(postgres_dsn)
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "users",
            "groups",
            "group_members",
            "app_access_policies",
            "app_user_grants",
            "app_group_grants",
            "company_app_controls",
            "pms_spaces",
            "pms_space_members",
            "pms_space_group_bindings",
            "docs_native_docs",
            "hermes_session_bindings",
        } <= tables
        assert "organization_units" not in tables
        assert not any("workspace" in table for table in tables)
        for table in tables:
            assert not any(
                column["name"] in {"workspace_id", "execution_workspace_id", "origin_workspace_id"}
                for column in inspector.get_columns(table)
            )
        assert any(
            foreign_key["referred_table"] == "pms_spaces"
            for foreign_key in inspector.get_foreign_keys("pms_space_members")
        )
        checks = {
            row["name"] for row in inspector.get_check_constraints("pms_space_group_bindings")
        }
        assert "ck_pms_space_group_role" in checks
        with engine.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
                == "group_sources_20260912"
            )
        command.downgrade(config, "base")
        assert sa.inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


def test_runtime_metadata_has_no_duplicate_index_declarations() -> None:
    from collections import Counter
    from miy_api.core.db import Base
    from miy_api.core.model_registry import import_all_models

    import_all_models()
    duplicated = {
        table.name: sorted(
            name
            for name, count in Counter(index.name for index in table.indexes).items()
            if count > 1
        )
        for table in Base.metadata.tables.values()
    }
    assert {table: names for table, names in duplicated.items() if names} == {}


@pytest.mark.migration
def test_group_downgrade_reserves_legacy_ids_before_mapping_new_groups(postgres_dsn: str) -> None:
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "group_sources_20260912")
    engine = sa.create_engine(postgres_dsn)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                INSERT INTO groups (id, source, name, description, active, slug, unit_type,
                    source_reference, created_at, updated_at)
                VALUES ('group-a', 'hr', 'Root', '', true, 'root', 'division', 'group-b', now(), now()),
                       ('group-b', 'hr', 'Child', '', true, 'child', 'department', NULL, now(), now()),
                       ('group-c', 'hr', 'Long reference', '', true, 'long', 'department',
                        'external-reference-longer-than-36-characters', now(), now())
            """)
            )
            conn.execute(sa.text("UPDATE groups SET parent_id='group-a' WHERE id='group-b'"))
            conn.execute(
                sa.text("""
                INSERT INTO users (id, login_id, email, full_name, password_hash, status,
                    login_blocked, must_change_password, theme_preference, locale,
                    time_zone, date_format, primary_organization_unit_id, created_at, updated_at)
                VALUES ('collision-user', 'collision-user', 'collision@example.test', 'User',
                    'fixture', 'active', false, false, 'system', 'ko-KR', 'Asia/Seoul', 'korean',
                    'group-b', now(), now())
            """)
            )
        command.downgrade(config, "company_20260908")
        with engine.connect() as conn:
            mapping = dict(
                conn.execute(sa.text("SELECT id, organization_unit_id FROM groups")).all()
            )
            assert mapping["group-a"] == "group-b"
            assert mapping["group-c"] == "group-c"
            assert len(set(mapping.values())) == 3
            assert (
                conn.scalar(sa.text("SELECT primary_organization_unit_id FROM users"))
                == mapping["group-b"]
            )
            assert (
                conn.scalar(
                    sa.text("SELECT parent_id FROM organization_units WHERE id = :id"),
                    {"id": mapping["group-b"]},
                )
                == mapping["group-a"]
            )
        command.upgrade(config, "group_sources_20260912")
        with engine.connect() as conn:
            assert (
                conn.scalar(sa.text("SELECT primary_organization_unit_id FROM users")) == "group-b"
            )
            assert (
                conn.scalar(sa.text("SELECT parent_id FROM groups WHERE id='group-b'")) == "group-a"
            )
    finally:
        engine.dispose()


@pytest.mark.migration
def test_group_unification_preserves_ids_assignments_grants_and_rollback(postgres_dsn: str) -> None:
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "company_20260908")
    engine = sa.create_engine(postgres_dsn)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                INSERT INTO users (id, login_id, email, full_name, password_hash, status,
                    login_blocked, must_change_password, theme_preference, locale,
                    time_zone, date_format, created_at, updated_at)
                VALUES ('migration-user', 'migration-user', 'migration@example.test',
                    'Migration User', 'fixture', 'active', false, false, 'system', 'ko-KR',
                    'Asia/Seoul', 'korean', now(), now())
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO organization_units
                    (id, name, slug, unit_type, parent_id, active, head_user_id, created_at, updated_at)
                VALUES ('old-root', 'Root', 'root', 'division', NULL, true, 'migration-user', now(), now()),
                       ('old-child', 'Child', 'child', 'department', 'old-root', false, NULL, now(), now()),
                       ('old-orphan', 'Orphan', 'orphan', 'department', NULL, true, NULL, now(), now())
            """)
            )
            conn.execute(
                sa.text("""
                INSERT INTO groups (id, kind, organization_unit_id, name, description, active, created_at, updated_at)
                VALUES ('stable-root', 'organization', 'old-root', '', 'Retain description', true, now(), now()),
                       ('stable-child', 'organization', 'old-child', '', '', true, now(), now()),
                       ('stable-manual', 'manual', NULL, 'TF', 'TF description', true, now(), now())
            """)
            )
            conn.execute(
                sa.text(
                    "UPDATE users SET primary_organization_unit_id='old-child' WHERE id='migration-user'"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO group_members VALUES ('stable-manual', 'migration-user', now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO company_app_controls (app_id, enabled, created_at, updated_at) VALUES ('community', true, now(), now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO app_access_policies (app_id, audience) VALUES ('community', 'selected')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO app_group_grants (app_id, group_id) VALUES ('community', 'stable-root')"
                )
            )
        command.upgrade(config, "group_sources_20260912")
        with engine.connect() as conn:
            groups = {
                row["id"]: row for row in conn.execute(sa.text("SELECT * FROM groups")).mappings()
            }
            assert groups["stable-root"]["source"] == "hr"
            assert groups["stable-root"]["name"] == "Root"
            assert groups["stable-root"]["head_user_id"] == "migration-user"
            assert groups["stable-root"]["description"] == "Retain description"
            assert groups["stable-root"]["source_reference"] == "old-root"
            assert groups["stable-child"]["parent_id"] == "stable-root"
            assert not groups["stable-child"]["active"]
            assert groups["stable-manual"]["source"] == "local"
            assert len(groups) == 4
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT primary_organization_unit_id FROM users WHERE id='migration-user'"
                    )
                )
                == "stable-child"
            )
            assert (
                conn.scalar(
                    sa.text("SELECT group_id FROM app_group_grants WHERE app_id='community'")
                )
                == "stable-root"
            )
            assert (
                conn.scalar(
                    sa.text("SELECT group_id FROM group_members WHERE user_id='migration-user'")
                )
                == "stable-manual"
            )
            assert "organization_units" not in sa.inspect(conn).get_table_names()
        command.downgrade(config, "company_20260908")
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT primary_organization_unit_id FROM users WHERE id='migration-user'"
                    )
                )
                == "old-child"
            )
            assert (
                conn.scalar(
                    sa.text("SELECT parent_id FROM organization_units WHERE id='old-child'")
                )
                == "old-root"
            )
            assert (
                conn.scalar(
                    sa.text("SELECT group_id FROM app_group_grants WHERE app_id='community'")
                )
                == "stable-root"
            )
        command.upgrade(config, "group_sources_20260912")
        with engine.connect() as conn:
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT primary_organization_unit_id FROM users WHERE id='migration-user'"
                    )
                )
                == "stable-child"
            )
    finally:
        engine.dispose()


@pytest.mark.migration
def test_decision_defaults_preserve_generation_and_downgrade(postgres_dsn: str) -> None:
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "llm_cap_defaults_20260918")
    engine = sa.create_engine(postgres_dsn)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "UPDATE ai_model_policy_defaults SET max_output_tokens=4096, version=3 WHERE app_id='' AND route_mode='local'"
                )
            )
            before = conn.execute(
                sa.text(
                    "SELECT app_id, route_mode, provider_id, model_id, max_output_tokens, version FROM ai_model_policy_defaults ORDER BY app_id, route_mode"
                )
            ).all()
        command.upgrade(config, "head")
        with engine.begin() as conn:
            assert (
                conn.execute(
                    sa.text(
                        "SELECT app_id, route_mode, provider_id, model_id, max_output_tokens, version FROM ai_model_policy_defaults WHERE model_family='generation' ORDER BY app_id, route_mode"
                    )
                ).all()
                == before
            )
            assert (
                conn.scalar(
                    sa.text(
                        "SELECT count(*) FROM ai_model_policy_defaults WHERE model_family='decision'"
                    )
                )
                == 0
            )
            conn.execute(
                sa.text(
                    "INSERT INTO ai_model_policy_defaults (model_family, app_id, route_mode, version, updated_at) VALUES ('decision', '', 'local', 1, CURRENT_TIMESTAMP)"
                )
            )
        command.downgrade(config, "llm_cap_defaults_20260918")
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.text(
                        "SELECT app_id, route_mode, provider_id, model_id, max_output_tokens, version FROM ai_model_policy_defaults ORDER BY app_id, route_mode"
                    )
                ).all()
                == before
            )
    finally:
        engine.dispose()


@pytest.mark.migration
def test_miy_api_key_migration_preserves_legacy_rows_and_guards_rollback(postgres_dsn):
    config = _migration_config(postgres_dsn)
    command.upgrade(config, "decision_defaults_20260927")
    engine = sa.create_engine(postgres_dsn)
    try:

        def insert_key(ident, prefix):
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "INSERT INTO platform_api_keys "
                        "(id, token_hash, secret_ciphertext, key_prefix, name, scopes, status, created_at) "
                        "VALUES (:id, :hash, 'test-ciphertext', :prefix, 'Migration test', "
                        "'[]', 'active', CURRENT_TIMESTAMP)"
                    ),
                    {"id": ident, "hash": ident * 32, "prefix": prefix + "A" * 11},
                )

        insert_key("a", "mty_pk_")
        command.upgrade(config, "head")
        insert_key("b", "miy_pk_")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT count(*) FROM platform_api_keys")) == 2
            assert (
                connection.scalar(
                    sa.text("SELECT secret_ciphertext FROM platform_api_keys WHERE id='a'")
                )
                == "test-ciphertext"
            )
        with pytest.raises(RuntimeError, match="Remove miy platform API keys"):
            command.downgrade(config, "decision_defaults_20260927")
        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM platform_api_keys WHERE id='b'"))
        command.downgrade(config, "decision_defaults_20260927")
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT count(*) FROM platform_api_keys")) == 1
    finally:
        engine.dispose()
