"""Actual fixed Files Core column/profile/partition SHARE in owned PostgreSQL."""

from types import SimpleNamespace

from sqlalchemy.orm import Session
import pytest

from _migration_revision_fixtures import migration_revision_world
from miy_api.domains.official_apps.file_extraction_roles import prepare_file_extraction_principal
from miy_api.domains.official_apps.file_projection_core_roles import (
    file_projection_partition_contract,
    install_file_projection_partition_guard,
    prepare_file_projection_core,
)
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_file_extraction_authority import seeded_request as seeded_request
from test_official_writer_roles import (
    world as current_head_world,  # noqa: F401
    role_template as role_template,
)
from test_official_writer_roles import move as move, denied as denied
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    return migration_revision_world(
        current_head_world,
        request,
        tmp_path,
        monkeypatch,
        expected_revision="file_effect_20261007",
    )


@pytest.fixture
def file_core_prepared(world, extraction_prepared):
    drain = move(
        world,
        extraction_prepared.identity,
        "active",
        state="draining",
        artifact=extraction_prepared.identity.artifact,
    )
    owner = world.role(login=False)
    with Session(world.engine) as db:
        install_file_projection_partition_guard(db, world.actor, guard_owner=owner, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "e" * 64)
    with Session(world.engine) as db:
        result = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
        )
        assert result.profile_prepared
        source_oid = result.principal.role_oid
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    core = world.role()
    with Session(world.engine) as db:
        result = prepare_file_projection_core(
            db, world.actor, role_name=core, expected=identity, expected_state="active"
        )
        assert result.profile_prepared
        db.commit()
    return SimpleNamespace(
        source=source,
        core=core,
        owner=owner,
        identity=identity,
        partition=extraction_prepared.partition,
        source_oid=source_oid,
    )


def lock(conn, partition):
    return str(
        conn.execute(
            "SELECT public.miy_lock_file_projection_partition(%s::uuid)", (partition,)
        ).fetchone()[0]
    )


def test_actual_column_only_core_lock_and_source_denials(world, file_core_prepared):
    before = snapshot(world, file_core_prepared.core)
    with Session(world.engine) as db:
        result = prepare_file_projection_core(
            db,
            world.actor,
            role_name=file_core_prepared.core,
            expected=file_core_prepared.identity,
            expected_state="active",
        )
        assert result.profile_prepared
        db.commit()
    assert snapshot(world, file_core_prepared.core) == before
    values = seeded_request(world, file_core_prepared)
    with Session(world.engine) as db:
        file_projection_partition_contract(db)
    with world.connect(file_core_prepared.core) as conn:
        assert lock(conn, file_core_prepared.partition) == file_core_prepared.partition
        assert (
            conn.execute(
                "SELECT id,retrieval_partition_id,corpus_id,deleted_at,extraction_status,extraction_content_checksum FROM file_manager_files WHERE id=%s",
                (values["file_id"],),
            ).fetchone()[0]
            == values["file_id"]
        )
        for query in (
            "SELECT storage_key FROM file_manager_files",
            "SELECT extraction_text FROM file_manager_files",
            "SELECT * FROM file_manager_files",
            "SELECT source_uri FROM file_manager_file_source_metadata",
            "SELECT token_hash FROM auth_sessions",
            "SELECT * FROM file_extraction_requests",
            "SELECT id FROM file_manager_files FOR SHARE",
            "SELECT id FROM file_manager_corpora FOR SHARE",
            "SELECT file_id FROM file_manager_file_source_metadata FOR SHARE",
            "UPDATE file_manager_files SET extraction_status=extraction_status WHERE false",
            "DELETE FROM file_manager_files WHERE false",
            "INSERT INTO file_manager_files SELECT * FROM file_manager_files WHERE false",
            "TRUNCATE file_manager_files",
            "SELECT id FROM retrieval_partitions FOR SHARE",
        ):
            denied(conn, query)
        import psycopg

        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                with conn.cursor().copy("COPY file_manager_files(id) FROM STDIN"):
                    pass
        assert error.value.sqlstate == "42501"
        assert (
            conn.execute(
                "SELECT id,retrieval_partition_id,access_scope_kind FROM file_manager_corpora"
            ).fetchall()
            == []
        )
        assert (
            conn.execute(
                "SELECT file_id,corpus_id,content_checksum FROM file_manager_file_source_metadata"
            ).fetchall()
            == []
        )
    with world.connect(file_core_prepared.source) as conn:
        denied(conn, "SELECT public.miy_lock_file_projection_partition(NULL)")
        conn.execute("SET LOCAL miy.writer_generation='999'")
        denied(conn, "SELECT public.miy_lock_file_projection_partition(NULL)")


def snapshot(world, name):
    from test_file_projection_roles import grants

    with world.connect() as conn:
        functions = conn.execute(
            "SELECT p.oid,a.privilege_type,a.is_grantable FROM pg_proc p,LATERAL aclexplode(p.proacl) a WHERE a.grantee=(SELECT oid FROM pg_roles WHERE rolname=%s) ORDER BY 1,2,3",
            (name,),
        ).fetchall()
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    return grants(world, name), functions, audits


def test_preparation_rollback_leaves_new_core_role_unchanged(world, file_core_prepared):
    role = world.role()
    before = snapshot(world, role)
    with Session(world.engine) as db:
        result = prepare_file_projection_core(
            db,
            world.actor,
            role_name=role,
            expected=file_core_prepared.identity,
            expected_state="active",
        )
        assert result.profile_prepared
        db.rollback()
    assert snapshot(world, role) == before


def test_actual_core_revoked_authority_refuses(world, file_core_prepared):
    import psycopg
    from psycopg import sql

    with world.connect() as conn:
        conn.execute(
            sql.SQL("REVOKE INSERT ON retrieval_projection_events FROM {}").format(
                sql.Identifier(file_core_prepared.core)
            )
        )
    with world.connect(file_core_prepared.core) as conn:
        with pytest.raises(psycopg.Error) as error:
            lock(conn, file_core_prepared.partition)
        assert error.value.sqlstate == "42501"
        assert error.value.diag.message_primary == "projection_core_authority_required"


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_fresh_capability_migration_round_trip_is_inactive(world):
    from alembic import command
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import sa_dsn

    config = _migration_config(sa_dsn(world.dsn))
    command.downgrade(config, "file_extraction_20261007")
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT to_regprocedure('public.miy_lock_file_projection_partition(uuid)')"
            ).fetchone()[0]
            is None
        )
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
    command.upgrade(config, "head")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_proc p,LATERAL aclexplode(p.proacl) a WHERE p.oid='public.miy_lock_file_projection_partition(uuid)'::regprocedure AND a.grantee=0)"
        ).fetchone()[0]
