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
from test_file_extraction_authority import seeded_request
from test_official_writer_roles import (
    world as current_head_world,  # noqa: F401
    role_template as role_template,
)
from test_official_writer_roles import move, denied
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


@pytest.mark.parametrize("mode", ["exact_replay", "caller_rollback", "partial"])
def test_preparation_is_exact_caller_transaction_no_expansion(world, file_core_prepared, mode):
    from miy_api.domains.official_apps.writer import WriterControlError
    from psycopg import sql

    role = file_core_prepared.core if mode == "exact_replay" else world.role()
    if mode == "partial":
        with world.connect() as conn:
            conn.execute(
                sql.SQL("GRANT SELECT(id) ON file_manager_files TO {}").format(sql.Identifier(role))
            )
    before = snapshot(world, role)
    with Session(world.engine) as db:
        if mode == "partial":
            with pytest.raises(WriterControlError, match="existing_profile"):
                prepare_file_projection_core(
                    db,
                    world.actor,
                    role_name=role,
                    expected=file_core_prepared.identity,
                    expected_state="active",
                )
        else:
            result = prepare_file_projection_core(
                db,
                world.actor,
                role_name=role,
                expected=file_core_prepared.identity,
                expected_state="active",
            )
            assert result.profile_prepared
            if mode == "exact_replay":
                db.commit()
            else:
                db.rollback()
    assert snapshot(world, role) == before


def test_existing_company_core_exact_replay_has_no_files_grant(world, file_core_prepared):
    from miy_api.domains.official_apps.projection_partition_roles import (
        install_company_partition_reader,
        prepare_company_projection_core,
    )

    drain = move(
        world,
        file_core_prepared.identity,
        "active",
        state="draining",
        artifact=file_core_prepared.identity.artifact,
    )
    owner = world.role(login=False)
    old_core = world.role()
    with Session(world.engine) as db:
        install_company_partition_reader(db, world.actor, reader_owner=owner, expected=drain)
        prepare_company_projection_core(
            db, world.actor, role_name=old_core, expected=drain, expected_state="draining"
        )
        db.commit()
    before = snapshot(world, old_core)
    with Session(world.engine) as db:
        result = prepare_file_projection_core(
            db, world.actor, role_name=old_core, expected=drain, expected_state="draining"
        )
        assert not result.profile_prepared
        db.commit()
    assert snapshot(world, old_core) == before
    with world.connect(old_core) as conn:
        denied(conn, "SELECT id FROM file_manager_files")
        denied(conn, "SELECT public.miy_lock_file_projection_partition(NULL)")


@pytest.mark.parametrize("change", ["metadata_version", "state"])
def test_actual_core_share_holds_non_key_metadata_through_commit(world, file_core_prepared, change):
    from concurrent.futures import ThreadPoolExecutor
    from test_official_writer_roles import wait_for_blocker
    import psycopg

    with world.connect(file_core_prepared.core) as core:
        blocker = core.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert lock(core, file_core_prepared.partition) == file_core_prepared.partition

        def update():
            with world.connect() as writer:
                writer.execute("SET LOCAL statement_timeout='5s'")
                writer.execute(
                    "UPDATE retrieval_partitions SET "
                    + (
                        "metadata_version=metadata_version+1"
                        if change == "metadata_version"
                        else "state='retired',is_default_ingest=false"
                    )
                    + " WHERE id=%s",
                    (file_core_prepared.partition,),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(update)
            try:
                wait_for_blocker(world, blocker)
                assert not future.done()
            finally:
                core.commit()
                # Surface worker SQL errors even when waiter observation itself fails.
                future.result(timeout=5)
    with world.connect(file_core_prepared.core) as core:
        if change == "state":
            with pytest.raises(psycopg.Error) as error:
                lock(core, file_core_prepared.partition)
            assert error.value.sqlstate == "55000"
            assert error.value.diag.message_primary == "file_projection_partition_unavailable"
        else:
            assert lock(core, file_core_prepared.partition) == file_core_prepared.partition
            assert (
                core.execute(
                    "SELECT metadata_version FROM retrieval_partitions WHERE id=%s",
                    (file_core_prepared.partition,),
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize("drift", ["missing", "inactive", "namespace", "personal"])
def test_fixed_files_descriptor_denies_current_drift(world, file_core_prepared, drift):
    import psycopg
    from uuid import uuid4

    identifier = file_core_prepared.partition
    with world.connect() as conn:
        if drift == "missing":
            identifier = str(uuid4())
        elif drift == "inactive":
            conn.execute(
                "UPDATE retrieval_partitions SET state='transitioning' WHERE id=%s", (identifier,)
            )
        elif drift == "namespace":
            conn.execute(
                "UPDATE retrieval_partitions SET source_namespace='docs' WHERE id=%s", (identifier,)
            )
        else:
            conn.execute(
                "UPDATE retrieval_partitions SET candidate_scope_kind='personal',candidate_user_id=%s WHERE id=%s",
                (world.user_id, identifier),
            )
    with world.connect(file_core_prepared.core) as conn:
        with pytest.raises(psycopg.Error) as error:
            lock(conn, identifier)
        assert error.value.sqlstate == "55000"
        assert error.value.diag.message_primary == "file_projection_partition_unavailable"


def test_managed_company_descriptor_is_accepted(world, file_core_prepared):
    from miy_api.domains.retrieval.partitioning import create_managed_partition

    with Session(world.engine) as db:
        identifier = str(
            create_managed_partition(
                db, source_namespace="files", candidate_scope_kind="company"
            ).id
        )
        db.commit()
    with world.connect(file_core_prepared.core) as conn:
        assert lock(conn, identifier) == identifier


@pytest.mark.parametrize(
    "drift",
    [
        "public",
        "body",
        "path",
        "invoker",
        "owner_login",
        "guard_disabled",
        "owner_column",
        "owner_core",
        "owner_other_function",
        "stable",
        "strict",
        "parallel",
        "leakproof",
    ],
)
def test_capability_drift_refuses_before_grants_or_audit(world, file_core_prepared, drift):
    from psycopg import sql
    from miy_api.domains.official_apps.writer import WriterControlError
    from miy_api.domains.official_apps.file_projection_core_roles import LOCK_FILE_PARTITION

    fresh = world.role()
    before = snapshot(world, fresh)
    with world.connect() as conn:
        statement = {
            "stable": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " STABLE"),
            "strict": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " STRICT"),
            "parallel": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " PARALLEL SAFE"),
            "leakproof": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " LEAKPROOF"),
            "public": sql.SQL("GRANT EXECUTE ON FUNCTION " + LOCK_FILE_PARTITION + " TO PUBLIC"),
            "body": sql.SQL(
                "CREATE OR REPLACE FUNCTION public.miy_lock_file_projection_partition(partition_id uuid) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS 'BEGIN RETURN NULL; END'"
            ),
            "path": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " SET search_path=public"),
            "invoker": sql.SQL("ALTER FUNCTION " + LOCK_FILE_PARTITION + " SECURITY INVOKER"),
            "owner_login": sql.SQL("ALTER ROLE {} LOGIN").format(
                sql.Identifier(file_core_prepared.owner)
            ),
            "guard_disabled": sql.SQL(
                "ALTER TABLE file_manager_files DISABLE TRIGGER miy_official_source_writer"
            ),
            "owner_column": sql.SQL(
                "GRANT SELECT(created_at) ON official_writer_principals TO {}"
            ).format(sql.Identifier(file_core_prepared.owner)),
            "owner_core": sql.SQL("GRANT UPDATE ON retrieval_partitions TO {}").format(
                sql.Identifier(file_core_prepared.owner)
            ),
            "owner_other_function": sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_admit(uuid) TO {}"
            ).format(sql.Identifier(file_core_prepared.owner)),
        }[drift]
        conn.execute(statement)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            prepare_file_projection_core(
                db,
                world.actor,
                role_name=fresh,
                expected=file_core_prepared.identity,
                expected_state="active",
            )
    assert snapshot(world, fresh) == before


@pytest.mark.parametrize(
    "privilege",
    [
        "source_update_column",
        "private_column",
        "public_column",
        "grant_option",
        "membership",
        "definer",
        "create",
    ],
)
def test_fresh_core_profile_denies_unreviewed_effective_privilege(
    world, file_core_prepared, privilege
):
    from psycopg import sql
    from miy_api.domains.official_apps.writer import WriterControlError

    fresh = world.role()
    with world.connect() as conn:
        statement = {
            "source_update_column": sql.SQL(
                "GRANT UPDATE(extraction_status) ON file_manager_files TO {}"
            ),
            "private_column": sql.SQL("GRANT SELECT(storage_key) ON file_manager_files TO {}"),
            "public_column": sql.SQL("GRANT SELECT(storage_key) ON file_manager_files TO PUBLIC"),
            "grant_option": sql.SQL(
                "GRANT SELECT(id) ON file_manager_files TO {} WITH GRANT OPTION"
            ),
            "membership": sql.SQL("GRANT {} TO {}"),
            "definer": sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_file_extraction_admit(uuid) TO {}"
            ),
            "create": sql.SQL("GRANT CREATE ON SCHEMA public TO {}"),
        }[privilege]
        if privilege == "public_column":
            conn.execute(statement)
        elif privilege == "membership":
            conn.execute(
                statement.format(sql.Identifier(file_core_prepared.core), sql.Identifier(fresh))
            )
        else:
            conn.execute(statement.format(sql.Identifier(fresh)))
    before = snapshot(world, fresh)
    with Session(world.engine) as db:
        with pytest.raises(WriterControlError):
            prepare_file_projection_core(
                db,
                world.actor,
                role_name=fresh,
                expected=file_core_prepared.identity,
                expected_state="active",
            )
    assert snapshot(world, fresh) == before


def test_source_execute_injection_still_cannot_invoke_core_capability(world, file_core_prepared):
    from psycopg import sql
    import psycopg

    with world.connect() as conn:
        conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_lock_file_projection_partition(uuid) TO {}"
            ).format(sql.Identifier(file_core_prepared.source))
        )
    with world.connect(file_core_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            lock(conn, file_core_prepared.partition)
        assert error.value.sqlstate == "42501"
        assert error.value.diag.message_primary == "projection_core_authority_required"


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


def test_renamed_historical_source_oid_cannot_become_core_by_injected_grants(
    world, file_core_prepared
):
    import psycopg
    from psycopg import sql

    renamed = world.role()
    with world.connect() as conn:
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(renamed)))
        conn.execute(
            sql.SQL("ALTER ROLE {} RENAME TO {}").format(
                sql.Identifier(file_core_prepared.source), sql.Identifier(renamed)
            )
        )
        # Privileged fault injection in this disposable DB, never preparation grants.
        conn.execute(
            sql.SQL(
                "GRANT INSERT ON official_projection_receipts,retrieval_projection_events TO {}"
            ).format(sql.Identifier(renamed))
        )
        conn.execute(
            sql.SQL("GRANT UPDATE ON retrieval_projection_heads TO {}").format(
                sql.Identifier(renamed)
            )
        )
        conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_lock_file_projection_partition(uuid) TO {}"
            ).format(sql.Identifier(renamed))
        )
    # The shared fixture revokes parameter grants before DROP ROLE; retire only
    # the absent old name from its owned cleanup list after successful rename.
    world.roles.remove(file_core_prepared.source)
    with world.connect(renamed) as conn:
        with pytest.raises(psycopg.Error) as error:
            lock(conn, file_core_prepared.partition)
        assert error.value.sqlstate == "42501"
        assert error.value.diag.message_primary == "projection_core_authority_required"


def test_new_capability_downgrade_is_explicit_and_preserves_prior_schema(world, file_core_prepared):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from test_alembic_migrations import _migration_config
    from test_official_writer_roles import sa_dsn

    config = _migration_config(sa_dsn(world.dsn))
    migration = ScriptDirectory.from_config(config).get_revision("file_projection_20261007")
    with pytest.raises(RuntimeError, match="file_projection_requires_draining"):
        with world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.module.downgrade()
    move(
        world,
        file_core_prepared.identity,
        "active",
        state="draining",
        artifact=file_core_prepared.identity.artifact,
    )
    with pytest.raises(RuntimeError, match="file_projection_requires_explicit_retirement"):
        with world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.module.downgrade()
    with world.connect() as conn:
        assert conn.execute(
            "SELECT to_regprocedure('public.miy_lock_file_projection_partition(uuid)')"
        ).fetchone()[0]
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 0


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
