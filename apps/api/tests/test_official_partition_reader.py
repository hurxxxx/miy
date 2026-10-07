"""Actual company-default read/SHARE authority in owned disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
import pytest
from sqlalchemy.orm import Session

from miy_api.domains.official_apps.projection_partition_roles import (
    LOCK_CORE_PARTITION,
    READ_COMPANY_PARTITION,
    company_partition_capability_contract,
    install_company_partition_reader,
    prepare_company_projection_core,
)
from miy_api.domains.official_apps.writer import WriterControlError, WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.official_apps.writer_roles import prepare_principal, revoke_principal
from miy_api.domains.retrieval.models import RetrievalPartition
from miy_api.domains.retrieval.partitioning import (
    ensure_default_partition,
    create_managed_partition,
)
from test_alembic_migrations import _migration_config
from test_official_writer_roles import ACTIVE, activate, denied, move, sa_dsn, wait_for_blocker
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster


def read_default(conn, namespace="docs", binding=None):
    return str(
        conn.execute(
            "SELECT public.miy_read_official_company_partition(%s,%s::uuid)",
            (namespace, binding),
        ).fetchone()[0]
    )


def lock_core(conn, identifier, namespace="docs"):
    return str(
        conn.execute(
            "SELECT public.miy_lock_official_projection_partition(%s::uuid,%s)",
            (identifier, namespace),
        ).fetchone()[0]
    )


def unavailable(
    conn, namespace="docs", binding=None, message="official_projection_partition_unavailable"
):
    with pytest.raises(psycopg.Error) as caught:
        with conn.transaction():
            read_default(conn, namespace, binding)
    assert caught.value.sqlstate == "55000"
    assert caught.value.diag.message_primary == message


@pytest.fixture
def prepared(world):
    old_source, _, _ = activate(world)
    with Session(world.engine) as db:
        defaults = {
            namespace: ensure_default_partition(
                db, source_namespace=namespace, candidate_scope_kind="company"
            ).id
            for namespace in ("docs", "pms", "meeting")
        }
        db.commit()
    drain = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    reader = world.role(login=False)
    with Session(world.engine) as db:
        install_company_partition_reader(db, world.actor, reader_owner=reader, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "b" * 64)
    with Session(world.engine) as db:
        principal = prepare_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
            company_projection=True,
        )
        source_oid = principal.role_oid
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    core = world.role()
    with Session(world.engine) as db:
        prepare_company_projection_core(
            db, world.actor, role_name=core, expected=identity, expected_state="active"
        )
        db.commit()
    return SimpleNamespace(
        source=source,
        old_source=old_source,
        source_oid=source_oid,
        reader=reader,
        core=core,
        identity=identity,
        defaults=defaults,
    )


def test_private_migration_is_inactive_and_preserves_original_guards(world):
    with world.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
        assert conn.execute("SELECT count(*) FROM official_writer_principals").fetchone()[0] == 0
        for signature in (READ_COMPANY_PARTITION, LOCK_CORE_PARTITION):
            row = conn.execute(
                "SELECT prosecdef,proconfig,EXISTS(SELECT 1 FROM aclexplode(COALESCE(proacl,acldefault('f',proowner))) WHERE grantee=0 AND privilege_type='EXECUTE') FROM pg_proc WHERE oid=%s::regprocedure",
                (signature,),
            ).fetchone()
            assert row == (True, ["search_path=pg_catalog, pg_temp"], False)
        assert conn.execute(
            "SELECT active_owner,state,generation FROM official_runtime_ownership WHERE scope='official.suite'"
        ).fetchone() == ("legacy", "active", 1)
    unprepared = world.role()
    with world.connect(unprepared) as conn:
        denied(conn, "SELECT miy_read_official_company_partition('docs',NULL)")
    command.downgrade(_migration_config(sa_dsn(world.dsn)), "recording_managed_20261007")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT to_regprocedure(%s)", (READ_COMPANY_PARTITION,)).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )


def test_actual_profiles_are_disjoint_and_return_only_uuid(world, prepared):
    with Session(world.engine) as db:
        company_partition_capability_contract(db)
    with world.connect(prepared.source) as conn:
        for namespace, identifier in prepared.defaults.items():
            assert read_default(conn, namespace) == identifier
            assert read_default(conn, namespace, identifier) == identifier
        for statement in (
            "SELECT id FROM retrieval_partitions",
            "UPDATE retrieval_partitions SET state=state WHERE false",
            "SELECT id FROM retrieval_partitions FOR SHARE",
            "SELECT scope FROM official_runtime_ownership",
            "SELECT role_oid FROM official_writer_principals",
            "UPDATE retrieval_projection_heads SET projection_version=projection_version WHERE false",
            "INSERT INTO official_projection_receipts(event_id) VALUES(gen_random_uuid())",
            "SELECT miy_lock_official_projection_partition(gen_random_uuid(),'docs')",
            "SELECT miy_recording_lock_producer(1,'forged',999,'forged')",
            f'SET ROLE "{prepared.reader}"',
        ):
            denied(conn, statement)
    with world.connect(prepared.core) as conn:
        for namespace, identifier in prepared.defaults.items():
            assert lock_core(conn, identifier, namespace) == identifier
        denied(conn, "SELECT miy_read_official_company_partition('docs',NULL)")
        denied(conn, "UPDATE docs_native_docs SET writer_scope=writer_scope WHERE false")
        denied(conn, "SELECT id FROM docs_native_docs FOR SHARE")
        denied(conn, "UPDATE retrieval_partitions SET state=state WHERE false")
        denied(conn, "SELECT id FROM retrieval_partitions FOR SHARE")
    with world.connect() as conn:
        # Even accidental function EXECUTE cannot make a Source role into Core.
        conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(LOCK_CORE_PARTITION), sql.Identifier(prepared.source)
            )
        )
    with world.connect(prepared.source) as conn:
        denied(conn, "SELECT miy_lock_official_projection_partition(gen_random_uuid(),'docs')")


def test_old_principal_exact_replay_never_expands_capability_or_audit(world, prepared):
    with world.connect() as conn:
        count = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(world.engine) as db:
        prepare_principal(
            db,
            world.actor,
            role_name=prepared.old_source,
            identity=ACTIVE,
            expected=prepared.identity,
            expected_state="active",
            company_projection=True,
        )
        db.commit()
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == count
        assert not conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')",
            (prepared.old_source, READ_COMPANY_PARTITION),
        ).fetchone()[0]
    with world.connect(prepared.old_source) as conn:
        denied(conn, "SELECT miy_read_official_company_partition('docs',NULL)")


@pytest.mark.parametrize("namespace", [None, "planner", "files", "docs;select 1"])
def test_namespace_is_fixed(world, prepared, namespace):
    with world.connect(prepared.source) as conn:
        unavailable(conn, namespace)


@pytest.mark.parametrize(
    "drift",
    ["missing", "inactive", "non_default", "wrong_scope", "wrong_binding", "wrong_namespace"],
)
def test_invalid_default_is_refused_without_repair(world, prepared, drift):
    binding = None
    with Session(world.engine) as db:
        row = db.get(RetrievalPartition, prepared.defaults["docs"])
        if drift == "missing":
            db.delete(row)
        elif drift == "inactive":
            row.state = "transitioning"
        elif drift == "non_default":
            row.is_default_ingest = False
        elif drift == "wrong_scope":
            row.candidate_scope_kind = "personal"
            row.candidate_user_id = world.user_id
        elif drift == "wrong_namespace":
            row.source_namespace = "other"
        else:
            binding = prepared.defaults["pms"]
        db.commit()
    with world.connect(prepared.source) as conn:
        unavailable(conn, binding=binding)


@pytest.mark.parametrize("principal", ["source", "core"])
def test_actual_partition_share_blocks_non_key_update_until_caller_commit(
    world, prepared, principal
):
    caller = world.connect(getattr(prepared, principal))
    identifier = prepared.defaults["docs"]
    try:
        assert (
            read_default(caller) if principal == "source" else lock_core(caller, identifier)
        ) == identifier

        def mutate():
            with world.connect() as conn:
                conn.execute("SET LOCAL statement_timeout='5s'")
                conn.execute(
                    "UPDATE retrieval_partitions SET state='transitioning',metadata_version=metadata_version+1 WHERE id=%s",
                    (identifier,),
                )
            return True

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(mutate)
            try:
                wait_for_blocker(world, caller.info.backend_pid)
                assert not future.done()
            finally:
                # Always release the caller before joining and surface worker errors.
                caller.commit()
                assert future.result(timeout=8)

        with world.connect(prepared.source) as conn:
            unavailable(conn)
        with world.connect(prepared.core) as conn:
            with pytest.raises(psycopg.Error) as caught:
                lock_core(conn, identifier)
            assert caught.value.sqlstate == "55000"
    finally:
        caller.close()


def test_current_identity_revocation_and_forged_guc_do_not_grant_capability(world, prepared):
    with world.connect(prepared.source) as conn:
        conn.execute("SET LOCAL miy.writer_generation='999'")
        assert read_default(conn) == prepared.defaults["docs"]
    with Session(world.engine) as db:
        revoke_principal(
            db,
            world.actor,
            role_oid=prepared.source_oid,
            expected=prepared.identity,
            expected_state="active",
        )
        db.commit()
    with world.connect(prepared.source) as conn:
        unavailable(conn, message="official_writer_fenced")


def test_core_preserves_company_managed_partition_but_source_requires_default(world, prepared):
    with Session(world.engine) as db:
        managed = create_managed_partition(
            db, source_namespace="docs", candidate_scope_kind="company"
        )
        identifier = managed.id
        db.commit()
    with world.connect(prepared.core) as conn:
        assert lock_core(conn, identifier) == identifier
    with world.connect(prepared.source) as conn:
        unavailable(conn, binding=identifier)


def test_capability_schema_downgrade_requires_explicit_grant_retirement(world, prepared):
    # Exercise this owned migration's gate independently of later append migrations.
    migration = ScriptDirectory.from_config(_migration_config(sa_dsn(world.dsn))).get_revision(
        "official_partition_20261007"
    )
    with pytest.raises(
        RuntimeError, match="official_projection_partition_requires_explicit_retirement"
    ):
        with world.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.module.downgrade()
    with world.connect(prepared.source) as conn:
        assert read_default(conn) == prepared.defaults["docs"]


@pytest.mark.parametrize(
    "hazard",
    [
        "guard_disabled",
        "guard_mixed",
        "public",
        "path",
        "invoker",
        "owner_login",
        "owner_column",
        "owner_other_function",
    ],
)
def test_new_source_profile_attestation_refuses_drift_before_grant(world, prepared, hazard):
    with world.connect() as conn:
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        statement = {
            "guard_disabled": "ALTER TABLE meetings DISABLE TRIGGER miy_official_source_writer",
            "guard_mixed": "DROP TRIGGER miy_official_source_writer ON meetings; CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON meetings FOR EACH STATEMENT EXECUTE FUNCTION public.miy_guard_official_source_writer('official.suite')",
            "public": f"GRANT EXECUTE ON FUNCTION {READ_COMPANY_PARTITION} TO PUBLIC",
            "path": f"ALTER FUNCTION {LOCK_CORE_PARTITION} SET search_path=public,pg_catalog",
            "invoker": f"ALTER FUNCTION {READ_COMPANY_PARTITION} SECURITY INVOKER",
            "owner_login": sql.SQL("ALTER ROLE {} LOGIN").format(sql.Identifier(prepared.reader)),
            "owner_column": sql.SQL("GRANT UPDATE(id) ON docs_native_docs TO {}").format(
                sql.Identifier(prepared.reader)
            ),
            "owner_other_function": sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_recording_publication_admit(uuid,uuid,text) TO {}"
            ).format(sql.Identifier(prepared.reader)),
        }[hazard]
        conn.execute(statement)
    role = world.role()
    with Session(world.engine) as db, pytest.raises(WriterControlError):
        prepare_principal(
            db,
            world.actor,
            role_name=role,
            identity=WriterIdentity(SUITE_SCOPE, "legacy", 6, "sha256:" + "c" * 64),
            expected=prepared.identity,
            expected_state="active",
            company_projection=True,
        )
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM official_writer_principals WHERE role_name=%s)", (role,)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'announcements','UPDATE')", (role,)
        ).fetchone()[0]
        if hazard != "public":
            assert not conn.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, READ_COMPANY_PARTITION)
            ).fetchone()[0]


@pytest.mark.parametrize(
    "hazard", ["column", "public", "membership", "other_definer", "reader_execute"]
)
def test_core_preparation_rejects_ambient_privileges_atomically(world, prepared, hazard):
    role = world.role()
    with world.connect() as conn:
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        if hazard == "column":
            statement = sql.SQL("GRANT UPDATE(id) ON docs_native_docs TO {}").format(
                sql.Identifier(role)
            )
        elif hazard == "public":
            statement = "GRANT SELECT ON users TO PUBLIC"
        elif hazard == "membership":
            member = world.role(login=False)
            statement = sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(member), sql.Identifier(role)
            )
        elif hazard == "other_definer":
            statement = sql.SQL(
                "GRANT EXECUTE ON FUNCTION public.miy_recording_publication_admit(uuid,uuid,text) TO {}"
            ).format(sql.Identifier(role))
        else:
            statement = sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(READ_COMPANY_PARTITION), sql.Identifier(role)
            )
        conn.execute(statement)
    with Session(world.engine) as db, pytest.raises(WriterControlError):
        prepare_company_projection_core(
            db, world.actor, role_name=role, expected=prepared.identity, expected_state="active"
        )
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_projection_receipts','INSERT')", (role,)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, LOCK_CORE_PARTITION)
        ).fetchone()[0]


def test_stale_open_connection_and_recreated_same_name_cannot_reuse_source_identity(
    world, prepared
):
    with world.connect(prepared.source) as retained:
        assert read_default(retained) == prepared.defaults["docs"]
        retained.commit()
        drain = move(
            world,
            prepared.identity,
            "active",
            state="draining",
            artifact=prepared.identity.artifact,
        )
        retained.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            ('{"owner":"legacy","generation":999}',),
        )
        unavailable(retained, message="official_writer_fenced")
        retained.rollback()
    with world.connect() as conn:
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(prepared.source)))
        conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(prepared.source)))
        from test_official_writer_roles import PASSWORD

        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(prepared.source), sql.Literal(PASSWORD))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(prepared.source))
        )
        conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(READ_COMPANY_PARTITION), sql.Identifier(prepared.source)
            )
        )
    with world.connect(prepared.source) as recreated:
        unavailable(recreated, message="official_writer_fenced")
    with (
        Session(world.engine) as db,
        pytest.raises(WriterControlError, match="writer_role_identity_immutable"),
    ):
        prepare_principal(
            db,
            world.actor,
            role_name=prepared.source,
            identity=prepared.identity,
            expected=drain,
            expected_state="draining",
            company_projection=True,
        )


def test_function_rejects_cooperative_guard_even_with_matching_forged_guc(world, prepared):
    with world.connect() as conn:
        conn.execute("DROP TRIGGER miy_official_source_writer ON meetings")
        conn.execute(
            "CREATE TRIGGER miy_official_source_writer BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON meetings FOR EACH STATEMENT EXECUTE FUNCTION public.miy_guard_official_source_writer('official.suite')"
        )
    with world.connect(prepared.source) as conn:
        import json

        conn.execute(
            "SELECT set_config('miy.official_writer',%s,true)",
            (
                json.dumps(
                    {
                        "owner": "legacy",
                        "generation": prepared.identity.generation,
                        "artifact": prepared.identity.artifact,
                    }
                ),
            ),
        )
        unavailable(conn, message="official_writer_fenced")


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_capability_rejects_stale_snapshot_isolation(world, prepared, isolation):
    with world.connect(prepared.source) as conn:
        conn.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL {}").format(sql.SQL(isolation)))
        unavailable(conn)


def test_read_capability_holds_current_ownership_until_caller_commit(world, prepared):
    caller = world.connect(prepared.source)
    try:
        assert read_default(caller) == prepared.defaults["docs"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                move,
                world,
                prepared.identity,
                "active",
                state="draining",
                artifact=prepared.identity.artifact,
            )
            try:
                wait_for_blocker(world, caller.info.backend_pid)
                assert not future.done()
            finally:
                caller.commit()
                assert future.result(timeout=8).generation == prepared.identity.generation + 1

        unavailable(caller, message="official_writer_fenced")
    finally:
        caller.close()


@pytest.mark.parametrize("signature", [READ_COMPANY_PARTITION, LOCK_CORE_PARTITION])
@pytest.mark.parametrize("profile", ["source", "core"])
def test_same_header_wrong_function_body_is_refused_before_grant(
    world, prepared, signature, profile
):
    arguments = (
        "source_namespace text,bound_partition_id uuid DEFAULT NULL"
        if signature == READ_COMPANY_PARTITION
        else "partition_id uuid,source_namespace text"
    )
    name = signature.split("(", 1)[0]
    with world.connect() as conn:
        before = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        owner = conn.execute(
            "SELECT proowner FROM pg_proc WHERE oid=%s::regprocedure", (signature,)
        ).fetchone()[0]
        conn.execute(
            sql.SQL(
                "CREATE OR REPLACE FUNCTION {}({}) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $body$ BEGIN RETURN NULL; END $body$"
            ).format(sql.SQL(name), sql.SQL(arguments))
        )
        # Headers, owner, defaults, PUBLIC ACL and type remain the same; only body differs.
        assert conn.execute(
            "SELECT proowner,prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
            (signature,),
        ).fetchone() == (owner, True, ["search_path=pg_catalog, pg_temp"])
    role = world.role()
    with (
        Session(world.engine) as db,
        pytest.raises(WriterControlError, match="official_projection_partition_function_invalid"),
    ):
        if profile == "source":
            prepare_principal(
                db,
                world.actor,
                role_name=role,
                identity=WriterIdentity(SUITE_SCOPE, "legacy", 6, "sha256:" + "c" * 64),
                expected=prepared.identity,
                expected_state="active",
                company_projection=True,
            )
        else:
            prepare_company_projection_core(
                db, world.actor, role_name=role, expected=prepared.identity, expected_state="active"
            )
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before
        assert not conn.execute(
            "SELECT EXISTS(SELECT 1 FROM official_writer_principals WHERE role_name=%s)", (role,)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, signature)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'announcements','UPDATE')", (role,)
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(%s,'official_projection_receipts','INSERT')", (role,)
        ).fetchone()[0]


def test_installed_reader_preserves_full90_guard_and_recording_contract(world, prepared):
    from miy_api.domains.official_apps.recording_roles import guard_contract
    from miy_api.domains.official_apps.writer_contracts import COVERED_SOURCE_TABLES
    from miy_api.domains.official_apps.writer_roles import ROLE_GUARD, _source_guard

    with Session(world.engine) as db:
        assert _source_guard(db) == ROLE_GUARD
        guard_contract(db)
        company_partition_capability_contract(db)
    with world.connect(prepared.source) as conn:
        for table in COVERED_SOURCE_TABLES:
            conn.execute(
                sql.SQL("UPDATE public.{} SET writer_scope=writer_scope WHERE false").format(
                    sql.Identifier(table)
                )
            )
        conn.execute("UPDATE recording_stage_commands SET state=state WHERE false")
        denied(
            conn,
            "UPDATE official_projection_outbox SET source_revision=source_revision WHERE false",
        )
        denied(conn, "DELETE FROM recording_stage_commands WHERE false")
        denied(conn, "UPDATE core_recording_publications SET state=state WHERE false")
